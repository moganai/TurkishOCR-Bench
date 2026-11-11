"""TOB-Skor (v3): ana skor = (Metin_TR + Tablo + Formül) / 3, eşit ağırlık; kategoriler karekök ağırlıklı ortalanır.

oku_puanla.py çıktısının üzerine çalışır (sonuç klasöründeki <model>_sayfa.jsonl, <model>_test.jsonl, ozet.json).

- Metin_TR = √(Doğruluk_metin × Kullanılabilirlik_metin), Türkçe ağırlıklı metin ölçüsü.
  - Doğruluk_metin: metin, turkce, sayi, tire test ailelerinin geçme oranı; aile içinde kategoriler karekök ağırlıklı,
    Türkçe alt türleri (şapka, büyük İ/I, diğer) eşit, aileler eşit.
  - Kullanılabilirlik_metin: oku_puanla'daki MQM cezası (Türkçe karakter 2,5), tablo_* ve formul* hata türleri çıkarılmış;
    paydada formül tokenı yok. Kapıya takılan sayfa 0.
- Tablo: OmniDocBench gibi TEDS. Sayfadaki her doğru tablo, model tablolarıyla tam hücre eşleşmesine göre Macar
  yöntemiyle eşlenir; eşleşen çiftin TEDS'i (eval.teds, hücre ızgarası ağacı, normalleştirilmiş hücre içeriği),
  eşi olmayan tablo 0. Sayfa puanı tabloların ortalaması.
- Formül: OmniDocBench gibi yalnız blok formüller (formul ailesi, tur=blok), bizim normalleştirmemizle:
  1. puanlayıcının formül testi geçtiyse (gösterim normalleştirmesi + KaTeX kanonik eşitlik) 1;
  2. değilse model çıktısındaki LaTeX formülleriyle Macar eşleştirmesi (görünüm-komutsuz edit benzerliği), eşi varsa CDM F1;
  3. model formülü LaTeX yazmadıysa ya da CDM formülü derleyemediyse puanlayıcının kısmi puanı.
  Sayfa puanı blok formüllerin ortalaması.
- Kapıya takılan sayfa (boş, kesik, döngü, yabancı alfabe) üç bileşende de 0.
- Her bileşen yalnız o öğeyi içeren sayfalarda ölçülür; kategori oranları √n ağırlığıyla ortalanır (n: kategoride o öğeyi
  içeren sayfa sayısı). Böylece iki sayfalık bir hücre altmış sayfalık hücreyle aynı ağırlığı almaz, ama yok da sayılmaz.

CDM sonuçları testler/cdm_onbellek.json'da saklanır; önbellekte olmayan çiftler için --cdm-calistir CDM'i çalıştırır
(kod/cdm, YAMALAR.md). Önbellek dışı çift varken --cdm-calistir verilmezse o çiftler 3. kurala düşer ve uyarı yazılır.

Kullanım:
  python tob_v3.py --sonuc ../sonuclar --testler ../testler --gt ../veri/dogru_metin --ocr ../model_ciktilari
"""
import argparse
import collections
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from rapidfuzz.distance import Levenshtein
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval as E  # noqa: E402
import oku_ortak as O  # noqa: E402
import oku_puanla as P  # noqa: E402

METIN_AILE = {"metin", "turkce", "sayi", "tire"}
HARIC_TUR = ("tablo_", "formul")
AYRAC = "\u0000"


# ---------------------------------------------------------------- yardımcılar
def karekok_ort(oran, n):
    """Kategori oranlarının √n ağırlıklı ortalaması (n: kategorideki sayfa sayısı). Boş kategori katılmaz; hepsi boşsa nan."""
    oran, n = np.asarray(oran, float), np.asarray(n, float)
    w = np.where((n > 0) & ~np.isnan(oran), np.sqrt(n), 0.0)
    return float((w * np.nan_to_num(oran)).sum() / w.sum()) if w.sum() else float("nan")


def makro(deger, meta, kat_ad):
    """{sayfa: 0..1} -> kategori içi sayfa ortalaması, kategoriler √n ağırlıklı (yüzde). Boşsa nan."""
    kat = collections.defaultdict(list)
    for s, v in deger.items():
        kat[meta[s]["kategori"]].append(v)
    return 100 * karekok_ort([np.mean(kat[k]) if kat[k] else np.nan for k in kat_ad], [len(kat[k]) for k in kat_ad])


def tex_temizle(tex):
    """CDM'e gidecek LaTeX: \\tag/\\label/\\displaystyle çıkar, {,} ve ˒ -> virgül, hizalama satırları \\\\ ile."""
    satir, _ = E.tex_on_isle(tex.replace("{,}", ",").replace("˒", ","))
    return " \\\\ ".join(satir).strip() if len(satir) > 1 else (satir[0] if satir else "")


# ---------------------------------------------------------------- sayfa işi (tablo + formül eşleştirme)
def _sayfa_is(a):
    model, kl, s, kat, gt_yol, bloklar = a
    p = Path(kl) / kat / f"{s}.md"
    ham = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
    y = {"model": model, "sayfa": s, "teds": None, "formul": []}
    g = O.kategori_normalle(Path(gt_yol).read_text(encoding="utf-8"), kat)
    G, H = E.coz(g), E.coz(O.kategori_normalle(ham, kat))
    gt_tab = [t for t, i, j in G.tablo if t.izgara and not (i < j and G.alan[i] in ("u", "a"))]  # üst/alt bilgideki tablo nötr
    hy_tab = [t for t, _, _ in H.tablo if t.izgara]
    if gt_tab:
        es = np.zeros((len(gt_tab), max(len(hy_tab), 1)))
        for i, x in enumerate(gt_tab):
            for j, z in enumerate(hy_tab):
                es[i, j] = E.tablo_es(x, z)
        r, c = linear_sum_assignment(-es)
        es_map = {i: j for i, j in zip(r, c) if hy_tab and es[i, j] > 0}
        y["teds"] = float(np.mean([E.teds(x, hy_tab[es_map[i]]) if i in es_map else 0.0 for i, x in enumerate(gt_tab)]))
    if bloklar:
        hf = [x for x in (tex_temizle(f) for f in E.formul_listesi(ham)) if x]
        gt = [tex_temizle(t["tex"]) for t in bloklar]
        esle = {}
        if hf:
            sim = np.array([[1 - Levenshtein.normalized_distance(O.gorunum_komutsuz(a_), O.gorunum_komutsuz(b_)) for b_ in hf] for a_ in gt])
            r, c = linear_sum_assignment(-sim)
            esle = {i: hf[j] for i, j in zip(r, c) if sim[i, j] > 0}
        y["formul"] = [{"test": t["id"], "gt": gt[i], "h": esle.get(i)} for i, t in enumerate(bloklar)]
    return y


# ---------------------------------------------------------------- CDM
def cdm_calistir(ciftler, onbellek, python, havuz):
    """ciftler: [(gt, pred)] önbellekte olmayanlar. kod/cdm/evaluation.py ile puanlar, önbelleğe ekler."""
    kok = Path(__file__).resolve().parent / "cdm"
    with tempfile.TemporaryDirectory() as d:
        girdi = [{"img_id": f"c{i}", "gt": g, "pred": h} for i, (g, h) in enumerate(ciftler)]
        json.dump(girdi, open(Path(d) / "girdi.json", "w"), ensure_ascii=False)
        subprocess.run([python, "evaluation.py", "-i", str(Path(d) / "girdi.json"), "-o", str(Path(d) / "cikti"), "-p", str(havuz)],
                       cwd=kok, check=True, stdout=subprocess.DEVNULL)
        c = Path(d) / "cikti/girdi"
        detay = json.load(open(c / "metrics_res.json")).get("details", {})
        derlendi = {os.path.splitext(f)[0] for f in os.listdir(c / "pred/bbox")} & {os.path.splitext(f)[0] for f in os.listdir(c / "gt/bbox")}
        for x in girdi:
            ok = x["img_id"] in derlendi and x["img_id"] in detay
            onbellek[x["gt"] + AYRAC + x["pred"]] = {"f1": float(detay[x["img_id"]]["F1_score"]) if ok else None, "derlendi": ok}


# ---------------------------------------------------------------- bileşenler
def metin_bileseni(model, son, testler, meta, kat_ad, sayfalar):
    gecen, toplam, sayfa_n = collections.Counter(), collections.Counter(), collections.defaultdict(set)
    for x in map(json.loads, open(son / f"{model}_test.jsonl", encoding="utf-8")):
        t = testler.get(x["id"])
        if not t or x["gecti"] is None or t["aile"] not in METIN_AILE or t["sayfa"] not in sayfalar:
            continue
        k = (O.birim(t), meta[t["sayfa"]]["kategori"])
        gecen[k] += x["gecti"]
        toplam[k] += 1
        sayfa_n[k].add(t["sayfa"])
    # birim (Türkçe alt türü) kategoriler boyunca √n ağırlıklı; aile = birimlerinin ortalaması; doğruluk = ailelerin ortalaması
    aile = collections.defaultdict(list)
    for b in sorted({b for b, _ in toplam}):
        aile[b.split("/")[0]].append(karekok_ort([gecen[b, k] / toplam[b, k] if toplam[b, k] else np.nan for k in kat_ad],
                                                 [len(sayfa_n[b, k]) for k in kat_ad]))
    d = float(100 * np.mean([np.mean(v) for v in aile.values()]))
    u = {}
    for x in map(json.loads, open(son / f"{model}_sayfa.jsonl", encoding="utf-8")):
        if x["sayfa"] not in sayfalar:
            continue
        tur = {k: v for k, v in x["tur"].items() if not k.split("/", 1)[1].startswith(HARIC_TUR)}
        z = dict(x, tur=tur, formul_token=0, **{s_: sum(v for k, v in tur.items() if k.startswith(s_ + "/")) for s_ in ("kritik", "orta", "hafif")})
        u[x["sayfa"]] = P.kullanilabilirlik(z)
    k = makro(u, meta, kat_ad)
    return {"dogruluk_metin": d, "kullanilabilirlik_metin": k, "metin_tr": float(np.sqrt(d * k)),
            "aile": {x: float(100 * np.mean(v)) for x, v in aile.items()}}, u


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sonuc", default=f"{O.V0}/sonuclar", help="oku_puanla.py çıktı klasörü")
    ap.add_argument("--testler", default=f"{O.V0}/testler")
    ap.add_argument("--gt", default=f"{O.V0}/veri/dogru_metin")
    ap.add_argument("--ocr", default=f"{O.V0}/model_ciktilari", help="model çıktıları kökü (<ocr>/<model>/<kategori>/<id>.md)")
    ap.add_argument("--cdm-onbellek", help="varsayılan: <testler>/cdm_onbellek.json")
    ap.add_argument("--cdm-calistir", action="store_true", help="önbellekte olmayan formül çiftleri için CDM'i çalıştır")
    ap.add_argument("--cdm-python", default=sys.executable, help="CDM bağımlılıklarının kurulu olduğu Python")
    ap.add_argument("--n", type=int, default=max((os.cpu_count() or 4) - 2, 1))
    a = ap.parse_args()
    son, tk = Path(a.sonuc), Path(a.testler)
    ob_yol = Path(a.cdm_onbellek or tk / "cdm_onbellek.json")
    onbellek = json.load(open(ob_yol, encoding="utf-8")) if ob_yol.exists() else {}

    meta = {m["sayfa"]: m for m in map(json.loads, open(tk / "sayfalar.jsonl", encoding="utf-8"))}
    kat_ad = sorted({m["kategori"] for m in meta.values()})
    testler = {t["id"]: t for t in map(json.loads, open(tk / "testler.jsonl", encoding="utf-8"))}
    bloklar = collections.defaultdict(list)
    for t in testler.values():
        if t["aile"] == "formul" and t.get("tur") == "blok":
            bloklar[t["sayfa"]].append(t)
    ozet = json.load(open(son / "ozet.json", encoding="utf-8"))
    modeller = list(ozet)

    # sayfa işleri
    isler = [(m, str(Path(a.ocr) / m), s, meta[s]["kategori"], str(Path(a.gt) / meta[s]["kategori"] / f"{s}.md"), bloklar.get(s, []))
             for m in modeller for s in meta]
    sayfa = {}
    with cf.ProcessPoolExecutor(a.n) as ex:
        for y in ex.map(_sayfa_is, isler, chunksize=16):
            sayfa[(y["model"], y["sayfa"])] = y
    kapi, gecti = {}, {}
    for m in modeller:
        kapi[m] = {x["sayfa"]: x["kapi"] for x in map(json.loads, open(son / f"{m}_sayfa.jsonl", encoding="utf-8"))}
        gecti[m] = {x["id"]: x["gecti"] for x in map(json.loads, open(son / f"{m}_test.jsonl", encoding="utf-8"))}

    # CDM gereken çiftler
    gerek = {}
    for (m, s), y in sayfa.items():
        for f in y["formul"]:
            if not kapi[m].get(s) and gecti[m].get(f["test"]) != 1 and f["h"]:
                k = f["gt"] + AYRAC + f["h"]
                if k not in onbellek:
                    gerek[k] = (f["gt"], f["h"])
    if gerek:
        if a.cdm_calistir:
            print(f"CDM: {len(gerek)} yeni çift puanlanıyor", flush=True)
            cdm_calistir(list(gerek.values()), onbellek, a.cdm_python, a.n)
            json.dump(onbellek, open(ob_yol, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        else:
            print(f"UYARI: {len(gerek)} formül çifti CDM önbelleğinde yok; --cdm-calistir verilmedi, bu çiftlerde puanlayıcının kısmi puanı kullanılır", flush=True)

    # model başına bileşenler
    sonuc, sayfa_kayit, formul_kayit = {}, [], []
    for m in modeller:
        tablo, formul = {}, {}
        for s in meta:
            y = sayfa[(m, s)]
            kp = bool(kapi[m].get(s))
            # tablo_istege_bagli: tablo da düz metin de savunulabilir; TEDS'e girmez, içerik Metin_TR'de puanlanır
            if y["teds"] is not None and not meta[s].get("tablo_istege_bagli"):
                tablo[s] = 0.0 if kp else y["teds"]
            if y["formul"]:
                v = []
                for f in y["formul"]:
                    g = gecti[m].get(f["test"])
                    if kp:
                        p, kaynak = 0.0, "kapi"
                    elif g == 1:
                        p, kaynak = 1.0, "test"
                    elif f["h"] and (onbellek.get(f["gt"] + AYRAC + f["h"]) or {}).get("derlendi"):
                        p, kaynak = onbellek[f["gt"] + AYRAC + f["h"]]["f1"], "cdm"
                    else:
                        p, kaynak = float(g or 0), "kismi"
                    v.append(p)
                    formul_kayit.append({"model": m, "sayfa": s, "test": f["test"], "gt": f["gt"], "h": f["h"], "puan": p, "kaynak": kaynak})
                formul[s] = float(np.mean(v))
        alt = {}
        for ad_, sec in (("tum", set(meta)), ("temel_degil", {s for s, x in meta.items() if x.get("temel") != O.TEMEL_MODEL.get(m)})):
            mt, u = metin_bileseni(m, son, testler, meta, kat_ad, sec)
            tb = makro({s: v for s, v in tablo.items() if s in sec}, meta, kat_ad)
            fm = makro({s: v for s, v in formul.items() if s in sec}, meta, kat_ad)
            alt[ad_] = dict(mt, tablo=tb, formul=fm, tob=(mt["metin_tr"] + tb + fm) / 3)
            if ad_ == "tum":
                for s in meta:
                    sayfa_kayit.append({"model": m, "sayfa": s, "u_metin": u.get(s), "teds": tablo.get(s), "formul": formul.get(s)})
        sonuc[m] = dict(alt["tum"], temel_degil=alt["temel_degil"]["tob"])
        print(f"{m}: TOB v3 {sonuc[m]['tob']:.1f}  metin_tr {sonuc[m]['metin_tr']:.1f}  tablo {sonuc[m]['tablo']:.1f}  formül {sonuc[m]['formul']:.1f}", flush=True)

    json.dump(sonuc, open(son / "tob_v3.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(son / "tob_v3_sayfa.jsonl", "w", encoding="utf-8") as f:
        for x in sayfa_kayit:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    with open(son / "tob_v3_formul.jsonl", "w", encoding="utf-8") as f:
        for x in formul_kayit:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    # ozet.json: ana skor v3; v2 değeri tob_v2'de saklanır (bir kez)
    for m in modeller:
        o = ozet[m]
        if "tob_v2" not in o:
            o["tob_v2"] = o["tob"]
        o["tob"] = {"skor": sonuc[m]["tob"], "metin_tr": sonuc[m]["metin_tr"], "tablo": sonuc[m]["tablo"], "formul": sonuc[m]["formul"],
                    "temel_degil": sonuc[m]["temel_degil"]}
    json.dump(ozet, open(son / "ozet.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ana = sorted(modeller, key=lambda m: -sonuc[m]["tob"])
    y = ["# TurkishOCR-Bench v3.1: TOB-Skor", "",
         "TOB-Skor = (Metin_TR + Tablo + Formül) / 3. Metin_TR = √(Doğruluk_metin × Kullanılabilirlik_metin); Tablo = TEDS; "
         "Formül = blok formüllerde puanlayıcı testi, değilse CDM. Kategoriler √n ağırlıklı ortalanır. Ayrıntı: PUANLAMA.md.", "",
         "| # | Model | **TOB-Skor** | Metin_TR | Doğruluk_metin | Kullanılabilirlik_metin | Tablo (TEDS) | Formül (CDM) | v2 TOB |",
         "|---|---|---|---|---|---|---|---|---|"]
    for i, m in enumerate(ana, 1):
        r = sonuc[m]
        y.append(f"| {i} | {m} | **{r['tob']:.1f}** | {r['metin_tr']:.1f} | {r['dogruluk_metin']:.1f} | {r['kullanilabilirlik_metin']:.1f} | "
                 f"{r['tablo']:.1f} | {r['formul']:.1f} | {ozet[m]['tob_v2']['skor']:.1f} |")
    n = collections.Counter(x["kaynak"] for x in formul_kayit)
    y += ["", f"Formül puanının kaynağı (blok formül × model): {dict(n)}"]
    open(son / "rapor_v3.md", "w", encoding="utf-8").write("\n".join(y) + "\n")
    print("\n".join(y[4:]))


if __name__ == "__main__":
    main()

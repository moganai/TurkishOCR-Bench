"""İki modelin sayfa sayfa karşılaştırması: B'nin puan kaybedip A'nın kazandığı yerleri gösteren yerel HTML.

Her sayfada: görsel, A'nın geçip B'nin kaldığı testler (doğru metin, A ve B çıktısındaki karşılık gelen yerle), tersi,
Vision'ın B'yi desteklediği kelimeler (doğru metin hatası adayı) ve üç metnin doğru metne göre işaretli farkı.
Görseller sayfaya gömülmez, veri/goruntu altından göreli yolla açılır: çıktı TurkishOCR-Bench altında bir klasörde olmalı.

Kullanım: python iki_model_karsilastir.py --a Muse --b gpt-6.1-sol --cikti ../analiz/muse_gpt.html
"""
import argparse
import collections
import difflib
import html
import json
import os
import re
from pathlib import Path

from rapidfuzz import fuzz, process

import eval as E
import oku_ortak as O

KOK = Path(__file__).resolve().parent.parent


def oku(p):
    return Path(p).read_text(encoding="utf-8", errors="ignore") if Path(p).exists() else ""


def anahtar(t):
    """Testin doğru metinde aranacak ham parçası ve kısa gösterimi."""
    a = t["aile"]
    if a == "metin":
        return t["ham"], t["ham"]
    if a in ("turkce", "tire"):
        return t["kelime"], t["kelime"]
    if a == "sadakat":
        return t["kelime"], f'{t["kelime"]} (düzeltilmiş hali: {t["duzgun"]})'
    if a == "sayi":
        return t["s"], t["s"]
    if a == "formul":
        return t["tex"], t["tex"]
    if a == "tablo":
        return t["hucre"], f'{t["hucre"]}  —{t["tur"]}→  {t["diger"]}'
    if a == "sira":
        return " ".join(t["once"][-4:]), " ".join(t["once"][-4:]) + "  ⟶  " + " ".join(t["sonra"][:4])
    if a == "kapsam":
        return None, t["capa"]
    return None, json.dumps({k: v for k, v in t.items() if k not in ("id", "sayfa", "kategori", "belge")}, ensure_ascii=False)[:120]


def baglam(gt, igne, pay=60):
    if not igne:
        return None
    i = gt.find(igne)
    if i < 0:
        al = fuzz.partial_ratio_alignment(igne, gt, score_cutoff=70)
        if not al:
            return None
        i, n = al.dest_start, al.dest_end - al.dest_start
    else:
        n = len(igne)
    return gt[max(0, i - pay):i + n + pay]


def karsilik(parca, metin):
    if not parca or not metin:
        return ""
    al = fuzz.partial_ratio_alignment(parca, metin, score_cutoff=50)
    return metin[al.dest_start:al.dest_end] if al else ""


GOSTER = str.maketrans({E.UST: "^{", E.ALT: "_{", E.KAP: "}", E.KESIR: "⁄", E.ORTA: "·", E.KOK_: "√{", E.KOKN: "√", E.SATIR: " ⏎ ", E.HUCRE: " │ "})


def norm_metin(md, kat):
    """Puanlayıcının gördüğü metin: biçim silinmiş, aynı dönüştürücüden geçmiş token dizisi."""
    return " ".join(E.coz(O.gosterim_normalle(md), E.NOKTA_DISI.get(kat, frozenset())).tok).translate(GOSTER)


def norm_satirli(md, kat):
    """Puanlayıcının gördüğü metin, paragraf başlarında satır sonuyla (tam metin farkı için)."""
    c = E.coz(O.gosterim_normalle(md), E.NOKTA_DISI.get(kat, frozenset()))
    bas = set(c.paragraf_bas)
    return "".join(("\n" if i in bas and i else " " if i else "") + t for i, t in enumerate(c.tok)).translate(GOSTER)


def norm_igne(t):
    if t["aile"] in ("metin",):
        return " ".join(t["parca"]).translate(GOSTER)
    i, _ = anahtar(t)
    return i


def fark_html(gt, h):
    """Kelime düzeyinde fark: doğru metinde olup çıktıda olmayan <del>, çıktıda fazla olan <ins>."""
    a, b = re.findall(r"\S+|\s+", gt), re.findall(r"\S+|\s+", h)
    y = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            y.append(html.escape("".join(b[j1:j2])))
            continue
        if i2 > i1:
            y.append("<del>" + html.escape("".join(a[i1:i2])) + "</del>")
        if j2 > j1:
            y.append("<ins>" + html.escape("".join(b[j1:j2])) + "</ins>")
    return "".join(y)


def vision_destek(gt, b, kutu):
    """B'nin yazdığı ama doğru metinde olmayan, Vision'ın gördüğü ve doğru metindeki Vision'ın görmediği bir kelimeye benzeyen kelimeler."""
    temiz = lambda w: w.strip(".,;:()[]\"'“”‘’!?*#|")
    v = {temiz(k[0]) for k in kutu}
    g = {temiz(w) for w in gt.split()}
    h = {temiz(w) for w in b.split()}
    gv = [w for w in g - v if len(w) >= 4 and w.isalpha()]
    y = []
    for w in sorted(h - g):
        if len(w) >= 4 and w.isalpha() and w in v and gv:
            e = process.extractOne(w, gv, scorer=fuzz.ratio, score_cutoff=80)
            if e:
                y.append((e[0], w))
    return y[:12]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--cikti", required=True)
    ap.add_argument("--sonuc", default=str(KOK / "sonuclar"), help="oku_puanla.py çıktı klasörü")
    ap.add_argument("--esik", type=float, default=0.02, help="sayfa gösterilir: kullanılabilirlik farkı (A − B) bundan büyükse")
    a = ap.parse_args()
    S, T, V = Path(a.sonuc), KOK / "testler", KOK / "veri"
    ozet = json.load(open(S / "ozet.json", encoding="utf-8"))
    meta = {json.loads(s)["sayfa"]: json.loads(s) for s in open(T / "sayfalar.jsonl", encoding="utf-8")}
    gorsel = {json.loads(s)["id"]: json.loads(s)["goruntu"] for s in open(V / "sayfalar.jsonl", encoding="utf-8")}
    testler = collections.defaultdict(list)
    for s in open(T / "testler.jsonl", encoding="utf-8"):
        t = json.loads(s)
        testler[t["sayfa"]].append(t)
    R = {m: {json.loads(s)["id"]: json.loads(s)["gecti"] for s in open(S / f"{m}_test.jsonl", encoding="utf-8")} for m in (a.a, a.b)}
    SY = {m: {json.loads(s)["sayfa"]: json.loads(s) for s in open(S / f"{m}_sayfa.jsonl", encoding="utf-8")} for m in (a.a, a.b)}
    cikti = Path(a.cikti).resolve()
    cikti.parent.mkdir(parents=True, exist_ok=True)

    sayfalar = []
    aile_say = collections.Counter()
    for sid, m in meta.items():
        ua, ub = SY[a.a][sid]["u"], SY[a.b][sid]["u"]
        for t in testler[sid]:
            ra, rb = R[a.a].get(t["id"]), R[a.b].get(t["id"])
            if ra == 1 and rb == 0:
                aile_say[(t["aile"], "a")] += 1
            elif ra == 0 and rb == 1:
                aile_say[(t["aile"], "b")] += 1
        if ua - ub <= a.esik:
            continue
        k = m["kategori"]
        gt = oku(V / "dogru_metin" / k / f"{sid}.md")
        ta, tb = oku(KOK / "model_ciktilari" / a.a / k / f"{sid}.md"), oku(KOK / "model_ciktilari" / a.b / k / f"{sid}.md")
        ng, na, nb = norm_metin(gt, k), norm_metin(ta, k), norm_metin(tb, k)
        satir = {"a": [], "b": []}
        for t in testler[sid]:
            ra, rb = R[a.a].get(t["id"]), R[a.b].get(t["id"])
            yon = "a" if (ra == 1 and rb == 0) else "b" if (ra == 0 and rb == 1) else None
            if not yon or len(satir[yon]) >= 40:
                continue
            igne, goster = anahtar(t)
            bg = baglam(gt, igne)
            nbg = baglam(ng, norm_igne(t), 40)
            satir[yon].append({"aile": t["aile"], "tur": t["tur"], "test": goster, "gt": bg or "", "a": karsilik(bg, ta), "b": karsilik(bg, tb),
                               "ngt": nbg or "", "na": karsilik(nbg, na), "nb": karsilik(nbg, nb)})
        sa, sb = SY[a.a][sid], SY[a.b][sid]
        sayfalar.append({
            "id": sid, "kat": k, "taslak": m["temel"], "ua": ua, "ub": ub,
            "ha": [sa["hukum"], sa["kritik"], sa["orta"]], "hb": [sb["hukum"], sb["kritik"], sb["orta"]],
            "tur_b": sorted(((v, t) for t, v in sb["tur"].items()), reverse=True)[:8],
            "tur_a": sorted(((v, t) for t, v in sa["tur"].items()), reverse=True)[:8],
            "img": os.path.relpath(V / gorsel[sid], cikti.parent),
            "satir": satir, "vision": vision_destek(gt, tb, E.kutu_oku(str(V / "kutu" / f"{sid}.js"))),
            "fa": fark_html(gt, ta), "fb": fark_html(gt, tb), "gt": html.escape(gt),
            "nfa": fark_html(norm_satirli(gt, k), norm_satirli(ta, k)), "nfb": fark_html(norm_satirli(gt, k), norm_satirli(tb, k)),
        })
    sayfalar.sort(key=lambda x: x["ub"] - x["ua"])

    oa, ob = ozet[a.a], ozet[a.b]
    taslak = []
    for tk in sorted({m["temel"] for m in meta.values()}):
        ids = [s for s in meta if meta[s]["temel"] == tk]
        taslak.append([tk or "—", len(ids), 100 * sum(SY[a.a][s]["u"] for s in ids) / len(ids), 100 * sum(SY[a.b][s]["u"] for s in ids) / len(ids)])
    veri = {
        "A": a.a, "B": a.b, "esik": a.esik,
        "ozet": {m: {"tob": o["tob"]["skor"], "dog": o["oku_skor"], "kul": o["kullanilabilirlik"]["skor"], "temiz": 100 * o["hukum"]["temiz"],
                     "aile": {k: (None if v != v else 100 * v) for k, v in o["aile"].items()},
                     "kat": {k: 100 * v for k, v in o["hukum"]["kategori_kullanilabilirlik"].items()}} for m, o in ((a.a, oa), (a.b, ob))},
        "aile_say": {f"{k}|{y}": v for (k, y), v in aile_say.items()}, "taslak": taslak, "sayfalar": sayfalar,
    }
    sablon = (Path(__file__).with_name("iki_model_sablon.html")).read_text(encoding="utf-8")
    cikti.write_text(sablon.replace("/*__VERI__*/null", json.dumps(veri, ensure_ascii=False).replace("</", "<\\/")), encoding="utf-8")
    print(cikti, f"{cikti.stat().st_size / 1e6:.1f} MB", len(sayfalar), "sayfa")


if __name__ == "__main__":
    main()

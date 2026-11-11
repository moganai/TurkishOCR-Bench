"""TurkishOCR-Bench v2 test üretici: doğru metin + Vision kutuları -> testler.jsonl (olmOCR-Bench tarzı birim testler).

Her test tek bir gerçeği sınar ve ya geçer ya kalır; bir hata yalnız kendi testini düşürür, sayfayı değil.
  metin   ~12 tokenlık gövde parçası çıktıda birebir var mı (aksan, büyük/küçük harf, noktalama dahil); parçalar görsele bakmadan
          tahmin edilmesi zor bir tokenin (sayı, kod, özel ad, eski imla, nadir kelime) çevresinden alınır
  turkce  ç ğ ı ö ş ü İ/I ve şapkalı harf içeren kelime doğru yazılmış mı (okunan kelimeler üzerinde)
  sayi    rakam içeren her dizi işaretiyle birebir mi (4,5 ile 4.5 farklı; görselde ne yazıyorsa o)
  sira    ardışık iki paragrafın sırası korunmuş mu (slayt, el yazısı, fiş hariç)
  tablo   hücre ile sağ/alt komşusu ve sütun/satır başlığı ilişkisi
  formul  blok ya da 3+ tokenlık formül satırı KaTeX kanonunda birebir mi
  tire    satır sonunda bölünmüş kelime tek parça yazılmış mı (Vision kutularından)
  sadakat doğru metindeki özgün yazım hatası (kitaap) korunmuş mu; model düzeltirse kalır
  olmamali [okunaksız] yerine uydurma yazılmamalı (görsel içi yazı nötr: OmniDocBench ve olmOCR gibi ne ödüllendirilir ne cezalandırılır)
  kapsam  gövdenin tamamı ~12 tokenlık parçalara bölünür; parça (aksansız, küçük harf, ~%90 benzerlikle) çıktıda var mı. Atlanan
          paragrafı yakalar; aile ortalamasına girmez, sayfa hükmünde eksik metin kritik hatadır
  temel   sayfa başına kapı: boş değil, kesilmemiş, tekrar döngüsü yok, uydurma metin yok, yabancı alfabe yok (kalırsa sayfanın bütün testleri kalır)
Üst/alt bilgi nötr: test üretilmez.

Kullanım: python oku_testler.py --cikti <klasor>
"""
import argparse
import collections
import json
import random
import shutil
from pathlib import Path

from rapidfuzz import fuzz

import eval as E
import oku_ortak as O


def tek_capa(n, tum):
    """Çapa doğru metinde bir kez geçmeli ve başka hiçbir yere bulanık eşleşmede de benzememeli."""
    if tum.count(" " + n + " ") != 1:
        return False
    return fuzz.partial_ratio(n, tum.replace(" " + n + " ", " | ", 1)) < O.SIRA_ESIK


def sayfa_testleri(sid, kat, gt, kutu):
    G = E.coz(gt, E.NOKTA_DISI.get(kat, frozenset()))
    T = []

    def ekle(aile, tur, **k):
        T.append({"aile": aile, "tur": tur, **k})

    # metin: zor tokenlerin çevresinden üst üste binmeyen ~12 tokenlık parçalar
    paragraflar = []
    for a, b in O.kosular(G):
        if sum(E.kelime_mi(G.tok[i]) for i in range(a, b)) >= 5:
            paragraflar.append((a, b))
        zor = [(i, n) for i in range(a, b) if (n := O.zor_neden(G, i, a))]
        son = a
        for i, _ in zor:
            if i < son:
                continue
            x = max(son, a, i - O.PARCA // 2)
            y = min(b, x + O.PARCA)
            x = max(son, a, y - O.PARCA)
            if any(E.kelime_mi(G.tok[j]) for j in range(x, y)):
                ekle("metin", "zor", parca=G.tok[x:y], ham=O.ham(G, x, y), zor=sorted({n for j, n in zor if x <= j < y}))
            son = y

    # turkce: gövde ve tablodaki hassas kelimeler
    ev = O.evren(G, ("g", "t"))
    for i, t in enumerate(G.tok):
        if ev[i] and O.hassas(t):
            ekle("turkce", "+".join(sorted({O.CIFT.get(frozenset((c, O.tr_fold(c))), "İ/I") for c in t if c in O.TR_HASSAS or c == "I"})),
                 kelime=t, sinif=O.tr_fold(t))

    # sadakat: doğru metindeki özgün yazım hataları (tek düzenlemeyle sık bir kelimeye dönüşen, sözlükte olmayan kelime)
    for i, t in enumerate(G.tok):
        if False and ev[i] and (d := O.sadakat_duzgun(t)):  # sadakat ailesi kaldırıldı (2026-11-07)
            ekle("sadakat", "yazim", kelime=t, duzgun=d)

    # kapsam: gövde baştan sona parçalanır (kısa kuyruk önceki parçaya katılır); 4 kelimeden kısa parça test edilmez
    for a, b in O.kosular(G):
        x = a
        while x < b:
            y = b if b - x < O.PARCA + O.PARCA // 2 else x + O.PARCA
            capa = O.capa_norm(G.tok[x:y])
            if len(capa.split()) >= 4:
                ekle("kapsam", "parca", capa=capa)
            x = y
    # olmamali: [okunaksız] yerine uydurma (iki yanındaki çapa arasında modelin yazdığı kelimeler)
    for i in sorted(set(G.okn)):
        once = [t for t in G.tok[max(0, i - 8):i] if E.kelime_mi(t)][-3:]
        sonra = [t for t in G.tok[i:i + 8] if E.kelime_mi(t)][:3]
        if len(once) >= 2 and len(sonra) >= 2:
            ekle("olmamali", "okunaksiz", once=once, sonra=sonra)

    # sayi
    vision = {k[0].strip(".,;:()[]") for k in kutu}
    dipnot = O.dipnot_isaretleri(G)  # bu sayıların o kadar geçişi dipnot işaretidir: eksikliği orta hata
    for s in O.sayi_dizileri(G, ("g", "t")):
        cekirdek = s.strip("".join(O.ISARET_ON | O.ISARET_SON))
        celiski = bool(vision) and cekirdek not in vision and O.ayirici_cevir(cekirdek) in vision
        dn = dipnot[s] > 0
        dipnot[s] -= dn
        ekle("sayi", "dipnot" if dn else "ondalik" if any(x in s for x in ",.") else "tam", s=s, vision_celiski=celiski)

    # sira: ardışık paragraflar; çapa doğru metinde tek olmalı
    if kat not in E.SIRA_DISI:
        tum = " " + O.capa_norm(G.tok) + " "
        for (a1, b1), (a2, b2) in zip(paragraflar, paragraflar[1:]):
            once, sonra = G.tok[max(a1, b1 - O.SIRA_CAPA):b1], G.tok[a2:min(b2, a2 + O.SIRA_CAPA)]
            n1, n2 = O.capa_norm(once), O.capa_norm(sonra)
            if len(n1.split()) >= 4 and len(n2.split()) >= 4 and tek_capa(n1, tum) and tek_capa(n2, tum):
                ekle("sira", "paragraf", once=once, sonra=sonra)

    # tablo: hücre ilişkileri (hücre metni tabloda tek olmalı)
    for ti, (t, ta, _) in enumerate(G.tablo):
        iz = t.izgara
        if not iz or (ta < len(G.alan) and G.alan[ta] in ("u", "a")):  # üst/alt bilgideki tablo (ajanda takvimi) nötr
            continue
        tek = collections.Counter(c for x in iz for c in x if c)
        aday = []
        for r, x in enumerate(iz):
            for c, h in enumerate(x):
                if not h or tek[h] > 1:
                    continue
                for tur in ("sag", "alt", "ust_baslik", "sol_baslik"):
                    d = O.iliski(iz, r, c, tur)
                    if d and d != h:
                        aday.append((tur, h, d))
        aday = sorted(set(aday))
        if len(aday) > O.TABLO_KOTA:
            aday = sorted(random.Random(f"{sid}/{ti}").sample(aday, O.TABLO_KOTA))
        for tur, h, d in aday:
            ekle("tablo", tur, tablo=ti, hucre=h, diger=d)

    # formul
    hata = 0
    for k, n, blok, bozuk, tex in O.formul_satirlari(gt):
        if bozuk:
            hata += 1
        elif blok or n >= 3:
            ekle("formul", "blok" if blok else "satir_ici", f=k, tex=tex)

    # tire
    sat = E.satirlar_kur(kutu)
    for i in (E.tire_testleri(G, sat) if sat else []):
        if G.alan[i] not in ("u", "a"):
            ekle("tire", "satir_sonu", kelime=G.tok[i])

    ekle("temel", "sayfa", betikler=sorted(O.betikler(gt) | O.betikler(" ".join(k[0] for k in kutu))))
    return T, hata


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cikti", required=True)
    ap.add_argument("--gt", default=f"{O.V0}/veri/dogru_metin")
    ap.add_argument("--secim", default=f"{O.V0}/veri/sayfalar.jsonl")
    ap.add_argument("--cikarilan", default=f"{O.V0}/cikarilan.jsonl")
    ap.add_argument("--kutu", default=f"{O.V0}/veri/kutu")
    ap.add_argument("--kart", default=f"{O.V0}/hakem/kart")
    ap.add_argument("--katex-onbellek", default=f"{O.V0}/testler/katex_onbellek.json", help="önceki render önbelleği (başlangıç)")
    a = ap.parse_args()
    cikti = Path(a.cikti)
    cikti.mkdir(parents=True, exist_ok=True)
    onbellek = cikti / "katex_onbellek.json"
    if not onbellek.exists() and Path(a.katex_onbellek).exists():
        shutil.copy(a.katex_onbellek, onbellek)

    cik = {json.loads(s)["id"] for s in open(a.cikarilan, encoding="utf-8")} if Path(a.cikarilan).exists() else set()
    sf = []
    for s in open(a.secim, encoding="utf-8"):
        e = json.loads(s)
        p = Path(a.gt) / e["kategori"] / f"{e['id']}.md"
        if e["id"] not in cik and p.exists():
            sf.append((e, O.kategori_normalle(p.read_text(encoding="utf-8"), e["kategori"])))
    E.kanon_doldur(sorted({t for _, g in sf for t in E.formul_listesi(g)}), onbellek)

    sayac = collections.defaultdict(collections.Counter)
    hata = 0
    with open(cikti / "testler.jsonl", "w", encoding="utf-8") as f, open(cikti / "sayfalar.jsonl", "w", encoding="utf-8") as fs:
        for e, g in sf:
            sid, kat = e["id"], e["kategori"]
            kp = Path(a.kart) / f"{sid}.json"
            temel = json.load(open(kp, encoding="utf-8")).get("temel", "") if kp.exists() else e.get("temel", "")
            meta = {"sayfa": sid, "kategori": kat, "belge": e.get("belge", sid), "temel": temel,
                    "incelenmedi": "incelenmedi" in e.get("etiket", []), "sentetik": "sentetik" in e.get("etiket", [])}
            # tablo_istege_bagli: tablo da düz metin de savunulabilir; sayfa Tablo bileşenine girmez (tob_v3.py)
            fs.write(json.dumps({**meta, **({"tablo_istege_bagli": True} if e.get("tablo_istege_bagli") else {})}, ensure_ascii=False) + "\n")
            T, h = sayfa_testleri(sid, kat, g, E.kutu_oku(f"{a.kutu}/{sid}.js"))
            hata += h
            for n, t in enumerate(T):
                f.write(json.dumps({"id": f"{sid}/{t['aile']}/{n}", **meta, **t}, ensure_ascii=False) + "\n")
                sayac[t["aile"]][kat] += 1
    kat_ad = sorted({e["kategori"] for e, _ in sf})
    print(f"{len(sf)} sayfa; render edilemeyen doğru metin formül satırı: {hata} (test dışı)")
    print("aile".ljust(8) + "".join(k[:9].rjust(10) for k in kat_ad) + "toplam".rjust(10))
    for ai in O.AILE + O.KAPI_KAPSAM:
        print(ai.ljust(8) + "".join(str(sayac[ai][k]).rjust(10) for k in kat_ad) + str(sum(sayac[ai].values())).rjust(10))
    json.dump({ai: dict(sayac[ai]) for ai in O.AILE + O.KAPI_KAPSAM}, open(cikti / "test_sayilari.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

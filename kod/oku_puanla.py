"""TurkishOCR-Bench puanlayıcı: testler.jsonl + model çıktıları -> sayfa hükmü, test sonuçları, rapor.

Bu betik birim testleri, sayfa hatalarını ve ek ölçüleri üretir; ana skoru (TOB-Skor) bunun üzerine tob_v3.py hesaplar.
Burada yazılan √(Doğruluk × Kullanılabilirlik) değeri eski v2 skorudur ve ozet.json içinde tob_v2 olarak saklanır.
  Doğruluk: birim test skoru (her aile kategori içinde geçme oranı, kategorilerin ortalaması, ailelerin ortalaması).
  Kullanılabilirlik: sayfa puanı 2^(−ceza/5), ceza = 100 × (5·kritik + 2,5·Türkçe karakter + 1·diğer orta + 0,1·hafif) / (kelime + formül tokenı)
  (MQM ağırlıkları, Freitag ve ark. 2021; Türkçe karakter hatası 2,5); kapıya takılan sayfa 0. Kategori makro.
İkincil: temiz sayfa oranı (kritik yok, 100 kelimede en fazla 1 orta hata), kategori makro.
temel bir kapıdır: sayfada boş çıktı, kesilme, tekrar döngüsü ya da yabancı alfabe varsa o sayfanın bütün testleri kalır.
Uydurma metin kapı değildir (sezgisel tespit, yanlış alarmda sayfanın bütün testleri gitmesin): sayfa hükmünde kritik hatadır.
kapsam: gövdenin her parçası çıktıda var mı; birim test ortalamasına girmez, eksik parça sayfa hükmünde kritik hatadır.
turkce paydası modelin okuduğu kelimelerdir (saf aksan doğruluğu); atlanan kelimeyi kapsam ölçer. Fazladan aksan (bilgi -> bılgi)
kalan test olarak eklenir.
Ek ölçüler: kapsam oranı, DER (eksik ve fazla aksan ayrı, İ/I noktası ayrı), kesinlik (kelime torbası fazlalığı, chrF P/R),
morfoloji (kök/ek), ayırt edici testler (bütün modellerin geçtiği testler hariç; model kümesine bağlı, yalnız ek analiz).

Kullanım: python oku_puanla.py --testler <klasor> --cikti <klasor> [ad=<cikti_klasoru> ...]
  model verilmezse --ocr klasöründeki (varsayılan: model_ciktilari) bütün klasörler değerlendirilir.
"""
import argparse
import bisect
import collections
import unicodedata
import concurrent.futures as cf
import json
import os
import re
import warnings
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

import eval as E
import oku_ortak as O


def sayfa_puanla(arg):
    sid, kat, gt, hyp, bitis, testler, kutu_yol = arg
    atla = E.NOKTA_DISI.get(kat, frozenset())
    G, H = E.coz(gt, atla), E.coz(hyp, atla)
    kutu = E.kutu_oku(kutu_yol)
    sonuc = {}  # test id -> 1 / 0 / None (kapsam dışı)
    teshis = collections.Counter()
    ek = []  # (aile, tur): modelin ürettiği ek kalan testler
    grup = collections.defaultdict(list)
    for t in testler:
        grup[t["aile"]].append(t)
    tablo_neden = {}

    # temel: kapı (önce hesaplanır; boş, kesik, döngü ya da yabancı alfabe varsa sayfanın bütün testleri sonunda 0 olur)
    kusur = []
    for t in grup["temel"]:
        if not any(E.kelime_mi(x) for x in H.tok):
            kusur.append("bos")
        if bitis in ("length", "max_tokens"):
            kusur.append("kesildi")
        if O.tekrar_dongusu(G, H):
            kusur.append("tekrar")
        if uydurma(G, H, kutu):
            kusur.append("uydurma")
        if yabanci_harf(hyp, set(t.get("betikler", []))) >= YABANCI_ESIK:
            kusur.append("yabanci_alfabe")
        sonuc[t["id"]] = int(not kusur)
        for k in kusur:
            teshis["temel_" + k] += 1
    kapi = [k for k in kusur if k != "uydurma"]

    # metin: parça çıktıda birebir (örtüşen sayım; aynı parça doğru metinde n kez varsa n kez aranır)
    hs = O.dizi(H.tok)
    hs_k = hs_f = None
    by = collections.defaultdict(list)
    for t in grup["metin"]:
        by[O.dizi(t["parca"])].append(t)
    h_kel_say = collections.Counter(x for x in H.tok if E.kelime_mi(x))
    g_kel_say = collections.Counter(x for x in G.tok if E.kelime_mi(x))
    hs_bosluksuz = None
    for p, ts in by.items():
        n = O.say_ortusen(hs, p)
        if n < len(ts):
            # boşluk ceza almaz (kullanıcı kararı): token sınırları farklı ama karakterler aynıysa (her hangi / herhangi) parça var
            if hs_bosluksuz is None:
                hs_bosluksuz = "".join(H.tok)
            n = max(n, O.say_ortusen(hs_bosluksuz, "".join(ts[0]["parca"])))
        if n < len(ts):  # parça içinde kelime sırası: her kategoride serbest (paragraf sırası sıra ailesinde ölçülür)
            # el yazısı: iki sütunlu liste satır satır da sütun sütun da okunabilir; parçanın kelimeleri (sayısıyla) çıktıda
            # varsa sıra farkı hata değildir
            # parçanın her kelimesi çıktıda doğru metindeki kadar geçmeli: aynı kelime sayfanın başka yerinde doğru yazıldı diye
            # yanlış okunan geçiş gizlenmesin
            k = collections.Counter(x for x in ts[0]["parca"] if E.kelime_mi(x))
            if k and all(h_kel_say[x] >= g_kel_say[x] for x in k):
                n = len(ts)
        for k, t in enumerate(ts):
            sonuc[t["id"]] = int(k < n)
        if n < len(ts):
            if hs_k is None:
                hs_k, hs_f = O.tr_kucuk(hs), O.tr_kucuk(O.tr_fold(hs))
            tani = "buyuk_kucuk" if O.tr_kucuk(p) in hs_k else "aksan" if O.tr_kucuk(O.tr_fold(p)) in hs_f else "diger"
            teshis["metin_" + tani] += len(ts) - n

    # turkce: aksansız sınıfta okunan kelime sayısı kadar test kapsanır
    ev = O.evren(G, ("g", "t"))
    g_bicim = collections.Counter(t for i, t in enumerate(G.tok) if ev[i] and E.kelime_mi(t))
    g_sinif = collections.defaultdict(collections.Counter)
    for t, n in g_bicim.items():
        g_sinif[O.tr_fold(t)][t] += n
    h_bicim = collections.Counter(t for t in H.tok if E.kelime_mi(t))
    h_sinif = collections.defaultdict(collections.Counter)
    for t, n in h_bicim.items():
        h_sinif[O.tr_fold(t)][t] += n
    by = collections.defaultdict(list)
    for t in grup["turkce"]:
        by[t["sinif"]].append(t)
    der = collections.Counter()
    for s, gs in g_sinif.items():
        # DER: okunan kelimelerde karakter düzeyinde eksik/fazla aksan ve İ/I noktası (aynı katlama sınıfında eşleşmeyenler eşlenir)
        hsn = h_sinif.get(s, collections.Counter())
        okunan_n = min(sum(gs.values()), sum(hsn.values()))
        if not okunan_n:
            continue
        ortak = gs & hsn
        kg, kh = list((gs - ortak).elements()), list((hsn - ortak).elements())
        for f, n in gs.items():
            pay = n * okunan_n / sum(gs.values())
            der["den_eksik"] += pay * sum(c in DIAKRITIK for c in f)
            der["den_fazla"] += pay * sum(c in TABAN for c in f)
            der["den_nokta"] += pay * sum(c in "İIıi" for c in f)
        for g_, h_ in zip(kg, kh):
            for a_, b_ in zip(g_, h_):
                if a_ == b_:
                    continue
                if {a_, b_} in ({"İ", "I"}, {"ı", "i"}):
                    der["nokta"] += 1
                elif a_ in DIAKRITIK:
                    der["eksik"] += 1
                elif b_ in DIAKRITIK:
                    der["fazla"] += 1
    for s, ts in by.items():
        gs, hsn = g_sinif[s], h_sinif.get(s, collections.Counter())
        okunan = min(sum(gs.values()), sum(hsn.values()))
        dogru = {f: min(n, hsn[f]) for f, n in gs.items()}
        yanlis = okunan - sum(dogru.values())
        fazla = [f for f in hsn if hsn[f] > gs.get(f, 0)]
        kul = collections.Counter()
        for t in ts:
            f = t["kelime"]
            if kul[f] < dogru[f]:
                sonuc[t["id"]] = 1
            elif yanlis > 0:
                sonuc[t["id"]] = 0
                yanlis -= 1
                h = next((x for x in fazla if len(x) == len(f)), None)
                for ad in (O.harf_farki(f, h) if h else ["diger"]):
                    teshis["turkce_" + ad] += 1
            else:
                sonuc[t["id"]] = None  # atlanan kelime: kapsam ölçer, turkce yalnız okunan kelimelerde aksanı ölçer
                teshis["turkce_atlanan"] += 1
            kul[f] += 1
    # fazladan aksan: doğru metinde aksansız yazılan kelimeye aksan eklenmiş
    g_tum = set(G.tok)
    for s, hsn in h_sinif.items():
        gs = g_sinif.get(s)
        if not gs or any(O.hassas(f) for f in gs):
            continue
        n = min(sum(gs.values()), sum(v for f, v in hsn.items() if O.hassas(f) and f not in g_tum))
        for _ in range(n):
            ek.append(("turkce", "fazla_aksan"))
        teshis["turkce_fazla_aksan"] += n

    # sayi: çoklu küme eşleşmesi (okuma sırasından bağımsız)
    # el yazısı notunda sayıdan önceki çizgi madde işaretidir (-5 Hececiler = - 5 Hececiler): baştaki çizgi karşılaştırılmaz
    madde = (lambda x: x.lstrip("-–")) if kat in SIRASIZ else (lambda x: x)
    h_sayi = collections.Counter(madde(x) for x in O.sayi_dizileri(H))
    by = collections.defaultdict(list)
    for t in sorted(grup["sayi"], key=lambda t: t["tur"] == "dipnot"):  # eksik geçiş önce dipnot işaretinden düşer
        by[madde(t["s"])].append(t)
    g_say = {s: len(ts) for s, ts in by.items()}
    artan = collections.Counter({s: n - g_say.get(s, 0) for s, n in h_sayi.items() if n > g_say.get(s, 0)})
    artan_rakam = collections.Counter()
    for s, n in artan.items():
        artan_rakam[re.sub(r"\D", "", s)] += n
    for s, ts in by.items():
        n = h_sayi[s]
        for k, t in enumerate(ts):
            sonuc[t["id"]] = int(k < n)
            if k >= n:
                v = O.ayirici_cevir(s)
                if artan[v] > 0:
                    artan[v] -= 1
                    teshis["sayi_ayirici_cevrildi"] += 1
                elif artan_rakam[re.sub(r"\D", "", s)] > 0:
                    artan_rakam[re.sub(r"\D", "", s)] -= 1
                    teshis["sayi_bicim"] += 1
                else:
                    teshis["sayi_eksik_yanlis"] += 1
                if t.get("vision_celiski"):
                    teshis["sayi_vision_celiskili_kalan"] += 1

    # sira: iki çapa da (aksansız, küçük harf, ~%90 benzerlikle) bulunmalı ve sıra korunmalı
    hn = " " + O.capa_norm(H.tok) + " "
    if grup["sira"]:
        for t in grup["sira"]:
            a, b = capa_bul(O.capa_norm(t["once"]), hn), capa_bul(O.capa_norm(t["sonra"]), hn)
            if not (a and b):
                sonuc[t["id"]] = None
                teshis["sira_bulunamadi"] += 1
                continue
            ok = min(a) < max(b)
            sonuc[t["id"]] = int(ok) if sira_olculur(kat) else None  # sıranın tek doğrusu olmayan kategoride yalnız tanı
            if not ok:
                teshis["sira_ters"] += 1

    # tablo: ilişki herhangi bir çıktı tablosunda sağlanmalı. Hücreler bulanık karşılaştırılır (aksansız, küçük harf, noktalamasız,
    # %85 benzerlik): hücre içindeki yazım farkı metin/sayi/sadakat ailelerinde ölçülür, tablo ailesi yalnız yapıyı ölçer
    if grup["tablo"]:
        izler = [t.izgara for t, _, _ in H.tablo if t.izgara]
        # aynı tablo, değerleri hücrede alt alta yazmak yerine rowspan'li ayrı satırlara bölünmüş olabilir: birleştirilmiş hali de aranır
        izler += [b for b in map(O.satir_birlestir, izler) if b]
        yer = collections.defaultdict(list)
        for k, iz in enumerate(izler):
            for r, x in enumerate(iz):
                for c, h in enumerate(x):
                    if h:
                        yer[hucre_norm(h)].append((k, r, c))
        for t in grup["tablo"]:
            konum = yer.get(hucre_norm(t["hucre"])) or bulanik_hucre(t["hucre"], yer) or onek_hucre(t["hucre"], izler)
            ok = any(hucre_ayni(O.iliski(izler[k], r, c, t["tur"]), t["diger"])
                     or (t["tur"] in ("sag", "alt") and onekli(O.iliski(izler[k], r, c, t["tur"]), t["diger"])) for k, r, c in konum)
            sonuc[t["id"]] = int(ok)
            if not ok:
                neden = "tablo_yok" if not izler else "hucre_yok" if not konum else "iliski"
                teshis["tablo_" + neden] += 1
                tablo_neden[t["id"]] = neden

    # formul: çıktıdaki formül satırları; LaTeX yerine Unicode yazılmışsa gövde token dizisinde sınırlı eşleşme
    if grup["formul"]:
        h_sat = [k for k, n, blok, bozuk, tex in O.formul_satirlari(hyp) if not bozuk]
        h_f = collections.Counter(h_sat)
        # satır bölme yeri farkı: doğru metin denklemi tek satır yazmış, model aligned ile başka yerden bölmüş (ya da tersi).
        # Satır birebir bulunamazsa çıktının formül satırları sırayla birleştirilip içinde aranır (kısa formüllerde değil)
        # (satır sonundaki denklem numarası atılır; büyük/küçük harf duyarlı: formülde S ile s ayrı değişkendir)
        h_akis = "".join(re.sub(r"\(\d{1,3}[a-z]?\)$", "", k) for k in h_sat)
        by = collections.defaultdict(list)
        for t in grup["formul"]:
            by[t["f"]].append(t)
        for f, ts in by.items():
            n = h_f[f]
            if n < len(ts):
                n += unicode_formul(H, f)
            if n < len(ts) and sozel_formul(ts[0]["tex"]):
                # sözel formül düz metin ya da yarı formül yazılmış (Ortalama hız = Toplam alınan yol / Zaman): aynı içerik, doğru
                n = max(n, sozel_duz(hyp).count(sozel_duz(ts[0]["tex"])))
            if n < len(ts) and (d := duz_formul(ts[0]["tex"])):
                # aynı LaTeX dolar sınırı farklı yazılmış olabilir ($P>0.05$ ~ $P$>0.05, $(4\pi OA)/OÇ^2$ ~ ($4\pi OA$)/$OÇ^2$)
                n = max(n, O.gorunum_komutsuz(hyp).count(d))
            if n < len(ts) and len(f) >= FORMUL_AKIS_EN_AZ:
                n = max(n, h_akis.count(f))
            # yalnız büyük/küçük harf farkı ([Δρ]_{EtOl} / _{Etol}): formül kalır ama kritik değil, orta sayılır
            n_bk = n
            if n < len(ts):
                kf = O.tr_kucuk(f)
                n_bk = max(n, sum(O.tr_kucuk(k) == kf for k in h_sat), O.tr_kucuk(h_akis).count(kf) if len(f) >= FORMUL_AKIS_EN_AZ else 0)
            # OmniDocBench gibi kısmi puan (CDM karşılığı): birebir bulunamayan formül, çıktıdaki en benzer formülle kanon
            # karakterleri üzerinden normalize edit benzerliği kadar puan alır (0-1)
            ben = formul_benzerlik(f, h_sat, h_akis) if n < len(ts) else 1.0
            for k, t in enumerate(ts):
                sonuc[t["id"]] = 1 if k < n else ben
                if n <= k < n_bk:
                    tablo_neden[t["id"]] = "formul_buyuk_kucuk"
            teshis["formul_kalan"] += max(0, len(ts) - n)

    # tire: kelime, doğru metindeki her geçişi kadar çıktıda tek parça olmalı
    if grup["tire"]:
        g_say = collections.Counter(G.tok)
        h_say = collections.Counter(H.tok)
        for t in grup["tire"]:
            sonuc[t["id"]] = int(h_say[t["kelime"]] >= g_say[t["kelime"]])

    # sadakat: özgün yazım hatası korunmalı; model düzgün biçimi yazdıysa kalır, ikisi de yoksa kapsam dışı (metin ailesi ölçer)
    if grup["sadakat"]:
        hc, gc = collections.Counter(H.tok), collections.Counter(G.tok)
        for t in grup["sadakat"]:
            if hc[t["duzgun"]] > gc[t["duzgun"]]:
                sonuc[t["id"]] = 0
                teshis["sadakat_duzeltti"] += 1
            elif hc[t["kelime"]] >= 1:
                sonuc[t["id"]] = 1
            else:
                sonuc[t["id"]] = None

    # olmamali: [okunaksız] yerine iki çapa arasına kelime uydurulmamalı (görsel içi yazı nötr)
    for t in grup["olmamali"]:
        if t["tur"] != "okunaksiz":
            continue
        n1, n2 = O.capa_norm(t["once"]), O.capa_norm(t["sonra"])
        a, b = capa_bul(n1, hn), capa_bul(n2, hn)
        if not (a and b and min(a) < max(b)):
            sonuc[t["id"]] = None
            continue
        ara = [w for w in hn[min(a) + len(n1) + 1:max(b)].split() if w not in ("okunaksiz",)]
        sonuc[t["id"]] = int(len(ara) < 2)
        if len(ara) >= 2:
            teshis["olmamali_okunaksiz_uyduruldu"] += 1

    # kapsam: gövde parçası çıktıda var mı (atlanan metin)
    # çıktının her kelimesi bir kez kullanılır: aynı cümleleri içeren paragraflardan biri atlandıysa (kesik çıktı, benzer ilanlar)
    # eksik paragrafın kelimeleri öbür paragrafların kelimeleriyle karşılanmasın
    h_kel = collections.Counter(hn.split())
    for t in grup["kapsam"]:
        k = collections.Counter(t["capa"].split())
        var = bool(capa_bul(t["capa"], hn)) or iki_parca(t["capa"].split(), hn, " ", " ")
        if not var:
            var = sum((k & h_kel).values()) >= KAPSAM_ORAN * sum(k.values())
        if var:
            h_kel -= k
        sonuc[t["id"]] = int(var)
        teshis["kapsam_eksik"] += 1 - sonuc[t["id"]]

    # kapı: felaket varsa sayfanın bütün testleri kalır
    if kapi:
        for t in testler:
            if t["aile"] == "sira" and not sira_olculur(kat):
                continue  # ölçülmeyen aile kapıda da ölçülmez (yoksa yalnız kapıya takılan sayfalardan 0 alır)
            sonuc[t["id"]] = 0
        ek = []

    # kesinlik: kelime torbası fazlalığı ve chrF (doğru metnin bütün tokenleri üzerinde)
    gk = collections.Counter(t for t in G.tok if E.kelime_mi(t))
    hk = collections.Counter(t for t in H.tok if E.kelime_mi(t))
    kesinlik = {"fazla": sum((hk - gk).values()), "cikti": sum(hk.values())}
    kesinlik["chrf_p"], kesinlik["chrf_r"], kesinlik["chrf"] = O.chrf(" ".join(G.tok), " ".join(H.tok))

    # tanı: üst/alt bilgi okuma (puana girmez)
    ua = [(x, y) for a, b in O.kosular(G, ("u", "a")) for x, y in O.bol(a, b)]
    teshis["ust_alt_parca"] += len(ua)
    teshis["ust_alt_bulunan"] += sum(O.dizi(G.tok[x:y]) in hs for x, y in ua)
    sd = siddet(G, H, grup, sonuc, tablo_neden, kat)
    sd.update(kapi=bool(kapi), der=dict(der), kesinlik=kesinlik,
              kapsam=[sum(sonuc[t["id"]] for t in grup["kapsam"]), len(grup["kapsam"])])
    sd["formul_token"] = sum(n for _, n, _, _, _ in O.formul_satirlari(gt))
    sd.update(ceza=sayfa_ceza(sd), u=kullanilabilirlik(sd))
    return sid, sonuc, ek, teshis, sd


DIAKRITIK = set("çğöşüâîûÇĞÖŞÜÂÎÛ")  # İ/ı nokta ayrı sayılır
TABAN = set("cgosuaiCGOSUAI")  # aksan alabilen düz harfler (fazla aksan paydası)
FORMUL_AKIS_EN_AZ = 10  # satırlar birleştirilerek aranacak formülün en az kanon uzunluğu (kısa formül her yerde geçer)
# okuma sırası yalnız paragrafların tek ve belirgin bir sırayla okunduğu kategorilerde ölçülür (kullanıcı kararı 2026-11-07).
# El yazısı, slayt, fiş/form ve tablo sayfalarında sütun/kutu sırasının tek doğrusu yoktur: sıra testi ve sıra hatası yok.
SIRA_KATEGORI = {"akademik", "kitap", "resmi_yeni", "resmi_eski", "taranmis", "formul"}


def sira_olculur(kat):
    return kat in SIRA_KATEGORI


SIRA_OLCULUR = False  # eski genel anahtar (artık kategoriye göre: sira_olculur); okuma sırası, sütun düzeni ve satır düzeni ceza almaz: sıra testleri
# ölçülmez, sıra hatası yazılmaz, metin parçası kelimeleri çıktıda varsa sırası farklı da olsa geçer
SIRASIZ = {"el_yazisi"}  # okuma sırası ölçülmeyen kategoriler (ders notu düzeni: sütun ya da satır sırası ikisi de geçerli)
KAPSAM_ORAN = 0.8  # kapsam parçası kelimelerinin bu oranı çıktıda varsa parça atlanmamış sayılır
HUKUM_ORTA = 1.0  # temiz sayfada 100 kelimede en fazla orta hata
SURUM = "3.1"  # puanlama kuralları dondurulmuştur (2026-11-11); değişiklik yeni sürüm ve test_gosterim.py güncellemesi ister
MQM_AGIRLIK = {"hafif": 0.1, "orta": 1, "kritik": 5}  # Freitag ve ark. 2021 (WMT MQM): minor/noktalama 0,1, minor 1, major 5
TURKCE_AGIRLIK = 2.5  # Türkçe karakter hatası (ı/i, ş/s, ğ/g, İ/I, â/a): Türkçe'de aksan ve nokta anlamı değiştirir
TURKCE_TUR = ("orta/turkce", "orta/turkce_kelime")
PAYDA_EK = 30  # kısa sayfa düzleştirmesi: paydaya 30 içerik birimi eklenir (tek hata 70 kelimelik formu sıfırlamasın; uzun sayfa neredeyse değişmez)
YARILANMA = 5  # 100 kelimede 5 ceza puanı (1 kritik ya da 2 Türkçe karakter hatası) sayfa puanını yarıya indirir


def sayfa_ceza(x, tr_agirlik=TURKCE_AGIRLIK):
    """100 içerik birimi başına MQM ağırlıklı hata yükü. İçerik = gövde/tablo kelimeleri + formül tokenları: formül hataları
    cezaya girdiğinden formül içeriği de paydaya girer (yoksa formül ağırlıklı kısa sayfada tek hata sayfayı sıfırlar)."""
    tr = sum(x["tur"].get(k, 0) for k in TURKCE_TUR)
    return 100 * (MQM_AGIRLIK["kritik"] * x["kritik"] + tr_agirlik * tr + MQM_AGIRLIK["orta"] * (x["orta"] - tr)
                  + MQM_AGIRLIK["hafif"] * x["hafif"]) / (x["kelime"] + x.get("formul_token", 0) + PAYDA_EK)


def kullanilabilirlik(x, yari=YARILANMA, tr_agirlik=TURKCE_AGIRLIK):
    """Sayfa puanı: hatasız 1, ceza her `yari` puanda yarıya iner; kapıya takılan sayfa (boş, kesik, döngü, yabancı alfabe) 0."""
    return 0.0 if x["kapi"] else 2 ** (-sayfa_ceza(x, tr_agirlik) / yari)


def siddet(G, H, grup, sonuc, tablo_neden, kat=""):
    """Kalan testleri MQM tarzı şiddete ayırır, sayfa hükmü verir: temiz / duzeltilebilir / guvenilmez."""
    say, tur_say = collections.Counter(), collections.Counter()
    ornek = []

    def yaz(sid_, tur, g="", h=""):
        if tur == "sira" and not sira_olculur(kat):
            return  # okuma sırası / sütun düzeni hata değildir
        if tur == "bolunme":
            return  # yalnız boşluk farkı (harfler aynı, kelime bitişik/bölünmüş) ceza almaz
        say[sid_] += 1
        tur_say[sid_ + "/" + tur] += 1
        if len(ornek) < 12:
            ornek.append([sid_, tur, g, h])
    # metin: kalan parçayı çıktıda en iyi bulanık konuma hizalayıp token farklarını sınıflar
    hstr, hbas = "", []
    for t in H.tok:
        hbas.append(len(hstr))
        hstr += t + " "
    morf = collections.Counter()
    ornek_tum = []  # metin parçalarında hata olarak sayılmış doğru metin kelimeleri
    gmap, hs = None, O.dizi(H.tok)
    on_ek = {O.tr_kucuk(x.rstrip("-‐")) for i, x in enumerate(H.tok) if len(x) > 2 and E.kelime_mi(x.rstrip("-‐"))
             and (x.endswith(("-", "‐")) or (i + 1 < len(H.tok) and H.tok[i + 1] in ("-", "‐")))}
    kume = (collections.Counter(O.tr_kucuk(x) for x in G.tok if E.kelime_mi(x)), collections.Counter(O.tr_kucuk(x) for x in H.tok if E.kelime_mi(x)),
            on_ek)
    for t in grup["metin"]:
        morf["kelime"] += sum(E.kelime_mi(x) for x in t["parca"])
        if sonuc.get(t["id"]) != 0:
            continue
        if iki_parca(t["parca"], hs, "\x1f", "\x1f"):
            yaz("orta", "sira", " ".join(t["parca"]))
            continue
        if gmap is None:
            gmap = genel_hizalama(G.tok, H.tok)
        for s_, tur, g, h in parca_farki(t["parca"], H.tok, hstr, hbas, konum_pencereleri(t["parca"], G.tok, gmap), kume):
            ornek_tum.extend(x for x in g.split() if x)
            if tur in ("turkce", "aksan", "buyuk_kucuk", "harf", "yanlis_kelime") and g and h:
                mt, gercek = O.morf_tur(g, h)
                morf[mt] += 1
                morf["gercek_kelime"] += gercek and mt != "buyuk_kucuk"
                if mt == "olumsuzluk":
                    s_ = "kritik"  # anlamı tersine çeviren ek (-ma/-me) kritik
            elif tur == "eksik":
                morf["eksik_kelime"] += len([x for x in g.split() if E.kelime_mi(x)])
            yaz(s_, tur, g, h)
    # Türkçe: kalan her hassas kelime (yanlış ya da atlanmış) orta hata; metin parçasında zaten sayılan kelime ikinci kez sayılmaz
    sayilan = collections.Counter()
    for o_ in ornek_tum:
        sayilan[o_] += 1
    h_kucuk = collections.Counter(O.tr_kucuk(x) for x in H.tok)
    for t in grup["turkce"]:
        if sonuc.get(t["id"]) == 0:
            if sayilan[t["kelime"]] > 0:
                sayilan[t["kelime"]] -= 1
                continue
            if h_kucuk[O.tr_kucuk(t["kelime"])] > 0:  # TÜM/Tüm, Ülkemiz/ülkemiz: Türkçe harf doğru, yalnız büyük/küçük farkı
                h_kucuk[O.tr_kucuk(t["kelime"])] -= 1
                yaz("hafif" if O.tum_buyuk(t["kelime"]) else "orta", "buyuk_kucuk_baslik" if O.tum_buyuk(t["kelime"]) else "buyuk_kucuk", t["kelime"])
                continue
            yaz("orta", "turkce_kelime", t["kelime"])
    for t in grup["sayi"]:
        if sonuc.get(t["id"]) == 0:
            yaz("orta" if t["tur"] == "dipnot" else "kritik", "dipnot_isareti" if t["tur"] == "dipnot" else "sayi", t["s"])
    for t in grup["formul"]:
        b_ = sonuc.get(t["id"])
        if b_ is not None and b_ < 1:
            if tablo_neden.get(t["id"]) == "formul_buyuk_kucuk":
                yaz("orta", "formul_buyuk_kucuk", t["tex"][:80])
            elif b_ >= FORMUL_ORTA_ESIK:
                yaz("orta", "formul_kucuk_fark", t["tex"][:80], f"{b_:.3f}")  # formülün %90+'ı doğru: tek simge/harf farkı
            else:
                yaz("kritik", "formul", t["tex"][:80], f"{b_:.3f}")
    tablo_orta = set()
    for t in grup["tablo"]:
        if sonuc.get(t["id"]) == 0:
            if tablo_neden.get(t["id"]) == "iliski" and t["tur"] in ("sag", "alt"):
                # veri hücresinin komşusu değişmiş: değer başka satıra/sütuna kaymış. Başlık ilişkisi (birleşik başlığın
                # kapsadığı sütunlar) yapı hatasıdır, orta
                yaz("kritik", "tablo_hucre_yeri", t["hucre"], t["diger"])
                tablo_orta.add(t["tablo"])
            elif t["tablo"] not in tablo_orta:
                tablo_orta.add(t["tablo"])
                yaz("orta", "tablo_yapisi", t["hucre"])
    for t in grup["sira"]:
        if sonuc.get(t["id"]) == 0:
            yaz("orta", "sira", " ".join(t["once"][-4:]), " ".join(t["sonra"][:4]))
    bolunmus = {O.tr_kucuk(O.tr_fold(x.replace("-", "").replace("‐", ""))) for x in H.tok if "-" in x or "‐" in x}
    for i in range(len(H.tok) - 1):
        a_, b_ = H.tok[i], H.tok[i + 1]
        bolunmus.add(O.tr_kucuk(O.tr_fold(a_.rstrip("-‐") + b_)))
        if b_ in ("-", "‐") and i + 2 < len(H.tok):
            bolunmus.add(O.tr_kucuk(O.tr_fold(a_ + H.tok[i + 2])))
    for t in grup["tire"]:
        if sonuc.get(t["id"]) == 0:
            if O.tr_kucuk(O.tr_fold(t["kelime"])) not in bolunmus:
                continue
            yaz("orta", "tire", t["kelime"])  # satır sonunda bölünmüş kelime tek parça yazılmamış (kullanıcı kararı: orta)
    for t in grup["temel"]:
        if sonuc.get(t["id"]) == 0:
            yaz("kritik", "felaket")
    for t in grup["sadakat"]:
        if sonuc.get(t["id"]) == 0:
            if sayilan[t["kelime"]] > 0:  # metin parçasında harf hatası olarak zaten sayıldı
                sayilan[t["kelime"]] -= 1
                continue
            yaz("bilgi", "sadakat_duzeltme", t["kelime"], t["duzgun"])  # sadakat Doğruluk'ta ölçülür, kullanılabilirliği düşürmez
    for t in grup["olmamali"]:
        if sonuc.get(t["id"]) == 0:
            yaz("kritik", "okunaksiz_uyduruldu", " ".join(t["once"]), " ".join(t["sonra"]))
    for t in grup["kapsam"]:
        if sonuc.get(t["id"]) == 0:
            yaz("kritik", "eksik_metin", t["capa"][:70])
    kelime = max(1, sum(1 for i, x in enumerate(O.evren(G, ("g", "t"))) if x and E.kelime_mi(G.tok[i])))
    hukum = "guvenilmez" if say["kritik"] else "temiz" if 100 * say["orta"] / kelime <= HUKUM_ORTA else "duzeltilebilir"
    return {"hukum": hukum, "kritik": say["kritik"], "orta": say["orta"], "hafif": say["hafif"], "kelime": kelime, "ornek": ornek, "morf": dict(morf), "tur": dict(tur_say)}


def genel_hizalama(gtok, htok):
    """Sayfanın bütün token dizileri arasında Levenshtein hizalaması: doğru metin token indisi -> çıktı token indisi."""
    kod = {}
    gi, hi = [kod.setdefault(x, len(kod)) for x in gtok], [kod.setdefault(x, len(kod)) for x in htok]
    m = [0] * (len(gtok) + 1)
    for op in Levenshtein.opcodes(gi, hi):
        for k in range(op.src_start, op.src_end):
            m[k] = op.dest_start + (k - op.src_start if op.tag in ("equal", "replace") else 0)
    m[len(gtok)] = len(htok)
    return m


def konum_pencereleri(parca, gtok, gmap):
    """Parçanın doğru metindeki her geçişine genel hizalamanın çıktıda karşılık getirdiği pencere [(a, b)]."""
    n = len(parca)
    return [(gmap[i], max(gmap[i + n] if i + n < len(gmap) else gmap[-1], gmap[i] + 1))
            for i in range(len(gtok) - n + 1) if gtok[i:i + n] == parca]


AGIRLIK = {"kritik": 10, "orta": 5, "hafif": 1, "bilgi": 0}


def kayma_mi(gk, hk, kume):
    """Farkın bütün kelimeleri sayfa toplamında dengede: kelime atlanmamış/uydurulmamış, yalnız yeri değişmiş."""
    if not kume or not (gk or hk):
        return False
    g_say, h_say, on_ek = kume[0], kume[1], (kume[2] if len(kume) > 2 else set())
    gk, hk = [O.tr_kucuk(x) for x in gk], [O.tr_kucuk(x) for x in hk]  # yer değiştirip büyük/küçük harfi de değişen kelime de kaymadır

    def bolunmus(w):
        # sütun/sayfa sonunda tireyle bölünmüş, araya başka metin girmiş kelime (Fakül- … tesi): baş ve son parça çıktıda var
        return any(w.startswith(p) and h_say[w[len(p):]] > 0 for p in on_ek if len(p) < len(w))
    def parca(x):
        # çıktıdaki bölünmüş kelimenin baş (Fakül) ya da son (tesi) parçası: birleşince doğru metinde olan kelime
        return x in on_ek or any(g_say[p + x] > 0 for p in on_ek)
    return all(h_say[x] >= g_say[x] or bolunmus(x) for x in gk) and all(g_say[x] >= h_say[x] or parca(x) for x in hk)


def parca_farki(parca, htok, hstr, hbas, konum=(), kume=None):
    """Kalan METİN parçasının hata listesi [(şiddet, tür, doğru, çıktı)]. Çıktıda bulunamayan parça eksiktir.
    Pencere adayları: bulanık eşleşmenin en iyi konumu ve genel hizalamanın verdiği konum(lar). Aynı ifade sayfada birden çok
    geçtiğinde bulanık eşleşme yanlış geçişe oturabilir; en az ceza veren pencere seçilir."""
    kel = sum(E.kelime_mi(x) for x in parca)
    aday = []
    al = fuzz.partial_ratio_alignment(" ".join(parca), hstr, score_cutoff=60 if kel >= 4 else 80)
    if al is not None:
        a = max(0, bisect.bisect_right(hbas, al.dest_start) - 1)
        aday.append((a, max(bisect.bisect_left(hbas, al.dest_end), a + 1)))
    aday += [(a, b) for a, b in konum if b - a <= 2 * len(parca) + 4 and a < len(htok)]
    if not aday:
        return [("kritik" if kel >= 3 else "orta", "eksik", " ".join(parca), "")]
    return min((pencere_farki(parca, htok[a:b], kume) for a, b in dict.fromkeys(aday)), key=lambda y: sum(AGIRLIK[x[0]] for x in y))


def apostrofsuz(w):
    return w.replace("'", "").replace("’", "").replace("ʼ", "")


def pencere_farki(parca, h, kume=None):
    kod = {}
    gi, hi = [kod.setdefault(x, len(kod)) for x in parca], [kod.setdefault(x, len(kod)) for x in h]
    y = []
    # bitişik farklılık bloklarını birleştir: hizalama "personeline anlatım" -> "personelineanlatım" gibi bir boşluk hatasını
    # iki ayrı işleme (değiştir + sil) bölebiliyor; boşluk hatası ancak blok bütün olarak karşılaştırılınca görünür
    ops = []
    for op in Levenshtein.opcodes(gi, hi):
        if op.tag == "equal":
            ops.append(["equal", op.src_start, op.src_end, op.dest_start, op.dest_end])
        elif ops and ops[-1][0] != "equal":
            ops[-1][2], ops[-1][4] = op.src_end, op.dest_end
            ops[-1][0] = "replace"
        else:
            ops.append([op.tag, op.src_start, op.src_end, op.dest_start, op.dest_end])
    harfler = lambda xs: "".join(x for x in xs if E.kelime_mi(x)).replace("-", "").replace("'", "").replace("’", "").replace("ʼ", "")
    for tag, s0, s1, d0, d1 in ops:
        if tag == "equal" or (s0 == s1 and s0 in (0, len(parca))):
            continue  # parçanın başında/sonunda araya giren token hizalama penceresinin taşmasıdır, hata değil
        g, hh = parca[s0:s1], h[d0:d1]
        gk, hk = [x for x in g if E.kelime_mi(x)], [x for x in hh if E.kelime_mi(x)]
        # boşluk hatası mı: harfler (boşluk ve tire hariç) birebir aynıysa yalnız boşluk/tire farkıdır; bir kelime ötesine kadar genişletilerek bakılır
        bosluk = harfler(g) == harfler(hh) or any(
            harfler(parca[max(0, s0 - i):s1 + j]) == harfler(h[max(0, d0 - k):d1 + l])
            for i, j, k, l in ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))
        if not gk and not hk:
            y.append(("hafif", "noktalama", " ".join(g), " ".join(hh)))
        elif bosluk:
            y.append(("hafif", "bolunme", " ".join(g), " ".join(hh)))
        elif O.tr_kucuk(harfler(g)) == O.tr_kucuk(harfler(hh)):
            # yalnız büyük/küçük harf: Türkçe karakter hatası değil; tamamen büyük harfli başlık yazımıysa hafif
            tb = any(O.tum_buyuk(x) for x in gk) or any(O.tum_buyuk(x) for x in hk)
            y.append(("hafif" if tb else "orta", "buyuk_kucuk_baslik" if tb else "buyuk_kucuk", " ".join(g), " ".join(hh)))
        elif O.tr_kucuk(O.tr_fold(harfler(g))) == O.tr_kucuk(O.tr_fold(harfler(hh))):
            # harfler aksansız aynı, yalnız bölünme/tırnak da farklı (Gök"ün ezelî -> Gök'ün ezeli): Türkçe karakter hatası, eksik değil
            y.append(("orta", "turkce", " ".join(g), " ".join(hh)))
        elif kayma_mi(gk, hk, kume):
            # yerinde harf farkı yukarıda ayrıldı; kalan, kelimelerin sayfanın başka yerinde durduğu blok kaymasıdır
            if not any(t[1] == "sira" for t in y):
                y.append(("orta", "sira", " ".join(g), " ".join(hh)))  # sütun sütun okuma, araya giren altyazı
        elif tag == "replace" and len(gk) == len(hk):
            for x, z in zip(gk, hk):
                if x == z:
                    continue
                if any(c.isdigit() for c in x + z):
                    continue  # sayi ailesinde kritik olarak sayılır
                if apostrofsuz(x) == apostrofsuz(z):
                    y.append(("hafif", "noktalama", x, z))  # yalnız kesme işareti (Tebliğ'in / Tebliğin)
                    continue
                d = Levenshtein.distance(x, z)
                tur = "buyuk_kucuk" if O.tr_kucuk(x) == O.tr_kucuk(z) else "turkce" if O.tr_fold(x) == O.tr_fold(z) else \
                    "aksan" if E.fold(x).lower() == E.fold(z).lower() else \
                    "harf" if d <= 2 and (d / max(len(x), len(z)) < 0.5 or min(len(x), len(z)) >= 4 or max(len(x), len(z)) <= 2) else \
                    "yanlis_kelime"
                if tur == "buyuk_kucuk" and (O.tum_buyuk(x) or O.tum_buyuk(z)):
                    y.append(("hafif", "buyuk_kucuk_baslik", x, z))  # ROMAN-HİKAYE / Roman-Hikaye: başlık yazımı
                    continue
                y.append(("kritik" if tur == "yanlis_kelime" else "orta", tur, x, z))
        else:
            n = max(len(gk), len(hk))
            y.append(("kritik" if n >= 3 else "orta", "eksik" if len(gk) > len(hk) else "fazla" if len(hk) > len(gk) else "yanlis_kelime", " ".join(g), " ".join(hh)))
    return y


def hukum_ozet(hukum, kat_ad):
    """Sayfa hükümlerinin kategori makro oranları."""
    kat = {k: [x for x in hukum if x["kategori"] == k] for k in kat_ad}
    oran = lambda h, xs: float(np.mean([x["hukum"] == h for x in xs])) if xs else np.nan
    y = {h: float(np.nanmean([oran(h, xs) for xs in kat.values()])) for h in ("temiz", "duzeltilebilir", "guvenilmez")}
    kt = {k: oran("temiz", xs) for k, xs in kat.items() if xs}
    y["kategori_temiz"] = kt
    y["en_kotu_kategori"] = min(kt, key=kt.get)
    y["en_kotu_kategori_temiz"] = kt[y["en_kotu_kategori"]]
    y["ceza"] = float(np.nanmean([np.mean([x["ceza"] for x in xs]) for xs in kat.values() if xs]))
    y["kategori_kullanilabilirlik"] = {k: float(np.mean([x["u"] for x in xs])) for k, xs in kat.items() if xs}
    tur = collections.Counter()
    for x in hukum:
        for o_ in x["ornek"]:
            tur[o_[0] + "/" + o_[1]] += 1
    y["ornek_turleri"] = dict(tur)
    return y


def capa_bul(capa, hn):
    """Çapanın çıktıdaki konumları: önce birebir (aksansız, küçük harf), yoksa en iyi bulanık eşleşme."""
    y = [m.start() for m in re.finditer("(?= " + re.escape(capa) + " )", hn)]
    if y:
        return y
    al = fuzz.partial_ratio_alignment(capa, hn, score_cutoff=O.SIRA_ESIK)
    return [al.dest_start] if al else []


def sozel_formul(tex):
    """Bütün terimleri \\text{} kelimesi olan formül (Ortalama hız = Toplam alınan yol / Zaman): düz metin yazımı da doğrudur."""
    kalan, n = re.subn(r"\\(?:text|textrm|textbf|textit|mathrm)\s*\{[^{}]*\}", "", tex)
    return n >= 2 and not re.search(r"[A-Za-z0-9]", re.sub(r"\\(?:d|t)?frac\b|\\(?:times|cdot|div)\b", "", kalan))


def sozel_duz(s):
    """Sözel formül karşılaştırması için: LaTeX sarmalı (\\text, \\frac, dolar, ayraç), kesir çizgisi ve boşluklar atılır, küçük harf."""
    s = re.sub(r"\\(?:text|textrm|textbf|textit|mathrm|[dt]?frac)\b", "", s)
    return re.sub(r"[\s${}()\[\]\\/]+", "", O.tr_kucuk(s))


def unicode_formul(H, f):
    """Formül gövdede düz metin olarak (E=mc², x̄) yazılmış: token dizisi, kelime ya da satır sınırıyla çevrili olmalı."""
    n = 0
    for a in range(len(H.tok)):
        if not f.startswith(H.tok[a]):
            continue
        s, b = "", a
        while b < len(H.tok) and len(s) < len(f):
            s += H.tok[b]
            b += 1
        if E.carpim_nokta(s) != f:
            continue
        sol = a == 0 or E.kelime_mi(H.tok[a - 1]) and len(H.tok[a - 1]) > 1 or "\n" in H.metin[H.bas[a - 1]:H.bas[a]]
        sag = b == len(H.tok) or E.kelime_mi(H.tok[b]) and len(H.tok[b]) > 1 or "\n" in H.metin[H.bas[b - 1]:H.bas[b]] or H.tok[b] in ".,;:"
        n += bool(sol and sag)
    return n


def hucre_norm(h):
    return re.sub(r"[\W_]+", "", O.tr_kucuk(O.tr_fold(h or "")))


def hucre_ayni(a, b):
    a, b = hucre_norm(a), hucre_norm(b)
    return a == b or (bool(a) and bool(b) and fuzz.ratio(a, b) >= 85)


def bulanik_hucre(h, yer):
    """Birebir bulunamayan hücrenin en benzer çıktı hücresindeki konumları (%85 ve üstü)."""
    n = hucre_norm(h)
    if not n:
        return []
    from rapidfuzz import process
    e = process.extractOne(n, list(yer), scorer=fuzz.ratio, score_cutoff=85)
    return yer[e[0]] if e else []


def onekli(uzun, kisa):
    """Ters yönde birleşik hücre: doğru metin değerleri ayrı satırlara bölmüş, model aynı hücrede alt alta yazmış. Modelin hücresi
    doğru metindeki hücrenin token token devamıysa ("0.2ᵃ 9.2ᵇ 1.4ᶜ" ⊃ "0.2ᵃ") eşleşir."""
    u, k = (uzun or "").split(), (kisa or "").split()
    return bool(k) and len(u) > len(k) and [hucre_norm(x) for x in u[:len(k)]] == [hucre_norm(x) for x in k]


def onek_hucre(h, izler):
    """Bulunamayan hücre, modelin birleştirdiği bir hücrenin ilk satırı olabilir: o hücrelerin konumları."""
    if len(hucre_norm(h)) < 2:
        return []
    return [(k, r, c) for k, iz in enumerate(izler) for r, x in enumerate(iz) for c, v in enumerate(x) if v and onekli(v, h)]


def iki_parca(tok, metin, ayrac, kapak):
    """Parça bir noktadan ikiye bölünüp iki yarısı da (en az 3'er token) metinde birebir bulunuyor mu: okuma sırası farkı
    (aynı satırdaki iki resim yazısını model ayrı yerlere koymuş), eksik değil."""
    return any(kapak + ayrac.join(tok[:k]) + kapak in metin and kapak + ayrac.join(tok[k:]) + kapak in metin for k in range(3, len(tok) - 2))


FORMUL_ORTA_ESIK = 0.9  # bu benzerliğin üstündeki formül farkı küçük farktır: orta (altı kritik)


def formul_benzerlik(f, h_sat, h_akis):
    """Doğru formülün çıktıdaki en benzer formüle benzerliği (OmniDocBench CDM'in edit karşılığı): satırlarla normalize edit
    benzerliği; uzun formülde satırları birleştirilmiş akışta en iyi eşleşen pencere de denenir."""
    en = max((Levenshtein.normalized_similarity(f, k) for k in h_sat), default=0.0)
    if len(f) >= FORMUL_AKIS_EN_AZ and h_akis:
        en = max(en, fuzz.partial_ratio(f, h_akis) / 100)
    return round(min(en, 0.9999), 4)  # birebir değilse tam puan almaz


def duz_formul(tex):
    """Formülün dolarsız, boşluksuz ve görünüm komutlarından arınmış LaTeX kaynağı: çıktıda aynı kaynak dolar sınırı ya da
    \\mathrm/\\left gibi yalnız görünüm komutlarıyla farklı yazılmışsa bulunur."""
    return O.gorunum_komutsuz(tex) or None


YABANCI_ESIK = 3  # tek bir Kiril homoglif (ekspansе) sayfayı sıfırlamasın: o bir harf hatasıdır


def yabanci_harf(hyp, izinli):
    """Doğru metinde olmayan yazı sistemlerinden harf sayısı."""
    n = 0
    for ch in hyp:
        if ord(ch) > 0x24F and ch.isalpha():
            ad = unicodedata.name(ch, "")
            n += any(ad.startswith(b) and b not in izinli for b in O.YABANCI_BETIK)
    return n


def uydurma(G, H, kutu):
    """Doğru metinde ve Vision'da olmayan, doğru metindeki hiçbir kelimeye benzemeyen art arda UYDURMA_KOSU kelime."""
    from rapidfuzz import process
    from rapidfuzz.distance import Levenshtein
    bilinen = {O.tr_kucuk(O.tr_fold(t)) for t in G.tok if E.kelime_mi(t)} | {O.tr_kucuk(O.tr_fold(k[0].strip(".,;:()[]\"'"))) for k in kutu}
    sozluk = sorted(bilinen)
    kosu = 0
    yabanci = {}
    # harf aralıklı yazılmış başlık (N İ F A K): art arda tek harfler birleştirilip tek kelime olarak denetlenir
    tok, alan, i = [], [], 0
    while i < len(H.tok):
        j = i
        while j < len(H.tok) and len(H.tok[j]) == 1 and H.tok[j].isalpha():
            j += 1
        if j - i >= 2:
            tok.append("".join(H.tok[i:j])); alan.append(H.alan[i]); i = j
        else:
            tok.append(H.tok[i]); alan.append(H.alan[i]); i += 1
    for t, a_ in zip(tok, alan):
        if not E.kelime_mi(t) or a_ in ("u", "a"):  # üst/alt bilgi nötr: logo yazısı uydurma sayılmaz
            continue
        n = O.tr_kucuk(O.tr_fold(t))
        if n not in yabanci:
            yabanci[n] = n not in bilinen and not any(c.isdigit() for c in n) and (
                not sozluk or process.extractOne(n, sozluk, scorer=Levenshtein.normalized_similarity, score_cutoff=0.7) is None)
        kosu = kosu + 1 if yabanci[n] else 0
        if kosu >= O.UYDURMA_KOSU:
            return True
    return False


def _pool_baslat(dosya):
    E.KANON.update(json.load(open(dosya, encoding="utf-8")))


def toplam_matris(satirlar, belgeler, kat_ad):
    """satirlar: [(belge, kategori, birim, gecti)] -> P, C dizileri [belge, birim, kategori]."""
    bi = {b: i for i, b in enumerate(belgeler)}
    ki = {k: i for i, k in enumerate(kat_ad)}
    ai = {a: i for i, a in enumerate(O.BIRIM)}
    P = np.zeros((len(belgeler), len(O.BIRIM), len(kat_ad)))
    C = np.zeros_like(P)
    for b, k, a, g in satirlar:
        C[bi[b], ai[a], ki[k]] += 1
        P[bi[b], ai[a], ki[k]] += g
    return P, C


def oranlar(P, C, w=None):
    """Aile x kategori oranı, aile makro, OKU-Skor. Birimler (turkce alt türleri) kategori içinde eşit ağırlıklı birleşir."""
    if w is not None:
        P, C = np.tensordot(w, P, 1), np.tensordot(w, C, 1)
    else:
        P, C = P.sum(0), C.sum(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(C > 0, P / C, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        r = np.stack([np.nanmean(r[..., [i for i, b in enumerate(O.BIRIM) if b.split("/")[0] == x], :], axis=-2) for x in O.AILE], axis=-2)
        aile = np.nanmean(r, axis=-1)
    return r, aile, 100 * np.nanmean(aile, axis=-1)


AYRIK = ("formul", "tablo")  # yalnız kendi ailesiyle puanlanan kategoriler


def ayrik_satir(satir):
    """Ayrık kategori skoru için test satırları: formül ve tablo kategorileri yalnız kendi aile testleriyle (formül sayfasında
    formül, tablo sayfasında tablo) puanlanır; bu sayfaların metin, Türkçe, sayı, sıra, tire ve temel testleri akademik
    kategorisine katılır. Diğer kategoriler bütün aileleriyle kalır."""
    return [(b, "akademik" if k in AYRIK and bi.split("/")[0] != k else k, bi, g) for b, k, bi, g, *_ in satir]


def ayrik_oranlar(P, C, w=None):
    """Kategori skoru: kategorideki ailelerin ortalaması (formül/tablo kategorisinde tek aile); genel skor kategorilerin ortalaması."""
    r, _, _ = oranlar(P, C, w)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        kat = np.nanmean(r, axis=-2)
    return kat, 100 * np.nanmean(kat, axis=-1)


def temiz_oran(T, N, w=None):
    """Temiz sayfa oranı: kategori içinde temiz sayfa payı, kategorilerin ortalaması. w: isteğe bağlı belge ağırlıkları."""
    if w is not None:
        T, N = w @ T, w @ N
    else:
        T, N = T.sum(0), N.sum(0)
    with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(np.where(N > 0, T / N, np.nan), axis=-1)


def ek_olculer(hukum, kat_ad):
    """Kapı oranı, kesinlik (kelime torbası fazlalığı, chrF P/R/F), DER (eksik/fazla aksan, İ/I noktası), morfoloji: kategori makro."""
    kat = {k: [x for x in hukum if x["kategori"] == k] for k in kat_ad}
    makro = lambda f: float(np.nanmean([f(xs) for xs in kat.values() if xs]))
    oran = lambda pay, payda: (lambda xs: (sum(pay(x) for x in xs) / s_) if (s_ := sum(payda(x) for x in xs)) else np.nan)
    y = {"kapi": makro(lambda xs: np.mean([x["kapi"] for x in xs])),
         "kapsam": makro(oran(lambda x: x["kapsam"][0], lambda x: x["kapsam"][1])),
         "fazlalik": makro(oran(lambda x: x["kesinlik"]["fazla"], lambda x: x["kesinlik"]["cikti"])),
         "chrf_p": makro(lambda xs: np.mean([x["kesinlik"]["chrf_p"] for x in xs])),
         "chrf_r": makro(lambda xs: np.mean([x["kesinlik"]["chrf_r"] for x in xs])),
         "chrf": makro(lambda xs: np.mean([x["kesinlik"]["chrf"] for x in xs]))}
    for ad_, pay, payda in (("der_eksik", "eksik", "den_eksik"), ("der_fazla", "fazla", "den_fazla"), ("nokta", "nokta", "den_nokta")):
        y[ad_] = makro(oran(lambda x, p_=pay: x["der"].get(p_, 0), lambda x, d_=payda: x["der"].get(d_, 0)))
    m = collections.Counter()
    for x in hukum:
        m.update(x.get("morf", {}))
    y["morf"] = dict(m)
    n = max(1, m["kelime"])
    y["kok_dogruluk"] = 1 - (m["kok"] + m["eksik_kelime"]) / n
    y["ek_dogruluk"] = 1 - (m["ek"] + m["olumsuzluk"]) / n
    return y


def ayirt_edici(ozet, satirlar, sonuclar, belgeler, kat_ad):
    """Ek analiz: bütün modellerin geçtiği testler (bilgi taşımaz) çıkarılınca birim test skoru. Doğru metin elle doğrulandığından
    az modelin geçtiği testler en zor testlerdir, çıkarılmaz. Seçim değerlendirilen modellere bağlıdır: liderlik tablosuna girmez."""
    ad = [m for m in sonuclar if m != "DOGRU_METIN"]
    if len(ad) < 3:
        return
    gecen = collections.Counter()
    bakan = collections.Counter()
    for m in ad:
        for i, g in sonuclar[m].items():
            if g is not None:
                bakan[i] += 1
                gecen[i] += g
    disari = {i for i in bakan if gecen[i] == bakan[i]}
    for m in ozet:
        sat = [x[:4] for x in satirlar[m] if x[5] is None or x[5] not in disari]
        P, C = toplam_matris(sat, belgeler, kat_ad)
        _, _, sk = oranlar(P, C)
        ozet[m]["ayirt_edici"] = {"skor": float(sk), "test": len(bakan) - len(disari), "hepsi_gecti": len(disari)}


def cikti_oku(klasor, kat, i):
    for p in (Path(klasor) / kat / f"{i}.md", Path(klasor) / f"{i}.md"):
        if p.exists():
            return O.kategori_normalle(p.read_text(encoding="utf-8", errors="ignore"), kat)
    return ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modeller", nargs="*", help="ad=klasor")
    ap.add_argument("--testler", default=f"{O.V0}/testler", help="oku_testler.py çıktı klasörü")
    ap.add_argument("--cikti", default=f"{O.V0}/sonuclar")
    ap.add_argument("--gt", default=f"{O.V0}/veri/dogru_metin")
    ap.add_argument("--kutu", default=f"{O.V0}/veri/kutu")
    ap.add_argument("--ocr", default=f"{O.V0}/model_ciktilari")
    ap.add_argument("--gt-kendisi", action="store_true", help="doğru metni model gibi değerlendirir (her aile 100 olmalı)")
    ap.add_argument("--n", type=int, default=max((os.cpu_count() or 4) - 2, 1))
    a = ap.parse_args()
    tk, cikti = Path(a.testler), Path(a.cikti)
    cikti.mkdir(parents=True, exist_ok=True)
    meta = {m["sayfa"]: m for m in map(json.loads, open(tk / "sayfalar.jsonl", encoding="utf-8"))}
    testler = collections.defaultdict(list)
    for s in open(tk / "testler.jsonl", encoding="utf-8"):
        t = json.loads(s)
        testler[t["sayfa"]].append(t)
    modeller = dict(m.split("=", 1) for m in a.modeller) or {p.name: str(p) for p in sorted(Path(a.ocr).iterdir()) if p.is_dir() and not p.name.startswith(".")}
    if a.gt_kendisi:
        modeller = {"DOGRU_METIN": a.gt, **modeller}
    gt = {s: O.kategori_normalle((Path(a.gt) / m["kategori"] / f"{s}.md").read_text(encoding="utf-8"), m["kategori"]) for s, m in meta.items()}
    kat_ad = sorted({m["kategori"] for m in meta.values()})
    belgeler = sorted({m["belge"] for m in meta.values()})

    onbellek = tk / "katex_onbellek.json"
    texler = {t for kl in modeller.values() for s, m in meta.items() for t in E.formul_listesi(cikti_oku(kl, m["kategori"], s))}
    yeni = E.kanon_doldur(sorted(texler), onbellek)
    print(f"{len(texler)} çıktı formülü, {len(yeni)} yeni render", flush=True)

    ozet, sonuclar, satirlar = {}, {}, {}
    bi = {b: i for i, b in enumerate(belgeler)}
    with cf.ProcessPoolExecutor(a.n, initializer=_pool_baslat, initargs=(str(onbellek),)) as ex:
        for ad, kl in modeller.items():
            bitis = {}
            kp = Path(kl) / "kayit.jsonl"
            if kp.exists():
                for s in open(kp, encoding="utf-8"):
                    try:
                        e = json.loads(s)
                        bitis[e.get("id")] = e.get("bitis")
                    except ValueError:
                        pass
            isler = [(s, m["kategori"], gt[s], cikti_oku(kl, m["kategori"], s), bitis.get(s), testler[s], f"{a.kutu}/{s}.js") for s, m in meta.items()]
            satir, teshis, sonuc = [], collections.Counter(), {}
            hukum = []
            for sid, r, ek, te, sd in ex.map(sayfa_puanla, isler, chunksize=8):
                m = meta[sid]
                hukum.append({"sayfa": sid, "kategori": m["kategori"], "belge": m["belge"], **sd})
                teshis.update(te)
                sonuc.update(r)
                for t in testler[sid]:
                    if t["aile"] not in O.KAPI_KAPSAM and r.get(t["id"]) is not None:
                        satir.append((m["belge"], m["kategori"], O.birim(t), r[t["id"]], sid, t["id"]))
                satir += [(m["belge"], m["kategori"], "turkce/diger" if aile == "turkce" else aile, 0, sid, None) for aile, _ in ek]
            sonuclar[ad] = sonuc
            P, C = toplam_matris([x[:4] for x in satir], belgeler, kat_ad)
            r, aile, skor = oranlar(P, C)
            o = {"oku_skor": float(skor),
                 "aile": {x: float(aile[i]) for i, x in enumerate(O.AILE)},
                 "aile_kategori": {x: {k: (None if np.isnan(r[i, j]) else float(r[i, j])) for j, k in enumerate(kat_ad)} for i, x in enumerate(O.AILE)},
                 "test_sayisi": {x: int(C[:, i].sum()) for i, x in enumerate(O.BIRIM)},
                 "birim_orani": {x: float(P[:, i].sum() / max(C[:, i].sum(), 1)) for i, x in enumerate(O.BIRIM)}, "teshis": dict(teshis)}
            # alt kümeler: temel seçilmeyen sayfalar, incelenmiş sayfalar, sentetik olmayan sayfalar
            for adi, kosul in (("temel_degil", lambda m: m["temel"] != O.TEMEL_MODEL.get(ad)), ("incelenmis", lambda m: not m["incelenmedi"]),
                               ("sentetik_haric", lambda m: not m["sentetik"])):
                P2, C2 = toplam_matris([x[:4] for x in satir if kosul(meta[x[4]])], belgeler, kat_ad)
                o["iz_" + adi] = float(oranlar(P2, C2)[2])
            P3, C3 = toplam_matris(ayrik_satir(satir), belgeler, kat_ad)
            kat_s, ay_s = ayrik_oranlar(P3, C3)
            o["ayrik"] = {"skor": float(ay_s),
                          "kategori": {k: (None if np.isnan(kat_s[j]) else float(100 * kat_s[j])) for j, k in enumerate(kat_ad)}}
            o["hukum"] = hukum_ozet(hukum, kat_ad)
            # temiz sayfa oranı (kategori makro)
            ki = {k: j for j, k in enumerate(kat_ad)}
            T, N = np.zeros((len(belgeler), len(kat_ad))), np.zeros((len(belgeler), len(kat_ad)))
            for x in hukum:
                N[bi[x["belge"]], ki[x["kategori"]]] += 1
                T[bi[x["belge"]], ki[x["kategori"]]] += x["hukum"] == "temiz"
            o["temiz"] = {"skor": float(100 * temiz_oran(T, N))}
            # ana skor: TOB = √(Doğruluk × Kullanılabilirlik)
            def u_matris(**k):
                U = np.zeros((len(belgeler), len(kat_ad)))
                for x in hukum:
                    U[bi[x["belge"]], ki[x["kategori"]]] += kullanilabilirlik(x, **k)
                return U
            K = 100 * temiz_oran(u_matris(), N)
            o["kullanilabilirlik"] = {"skor": float(K)}
            o["tob"] = {"skor": float(np.sqrt(skor * K))}
            o["duyarlilik"] = {f"yarilanma{y_}_turkce{t_}": float(np.sqrt(skor * 100 * temiz_oran(u_matris(yari=y_, tr_agirlik=t_), N)))
                               for y_, t_ in ((3, 2.5), (10, 2.5), (5, 1.0))}
            o["ek_olcu"] = ek_olculer(hukum, kat_ad)
            satirlar[ad] = satir
            ozet[ad] = o
            with open(cikti / f"{ad}_sayfa.jsonl", "w", encoding="utf-8") as f:
                for x in hukum:
                    f.write(json.dumps(x, ensure_ascii=False) + "\n")
            print(f"{ad}: TOB {o['tob']['skor']:.1f}  doğruluk {o['oku_skor']:.1f}  " + " ".join(f"{x} {100 * v:.0f}" for x, v in o["aile"].items()), flush=True)
            with open(cikti / f"{ad}_test.jsonl", "w", encoding="utf-8") as f:
                for i, g in sonuc.items():
                    f.write(json.dumps({"id": i, "gecti": g}) + "\n")
    ayirt_edici(ozet, satirlar, sonuclar, belgeler, kat_ad)
    json.dump(ozet, open(cikti / "ozet.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    denetim(testler, sonuclar, cikti)
    rapor(ozet, kat_ad, cikti)


def denetim(testler, sonuclar, cikti):
    """Bütün modellerin (en fazla biri hariç) kaldığı testler: doğru metin hatası adayı, elle bakılır."""
    ad = [m for m in sonuclar if m != "DOGRU_METIN"]
    if len(ad) < 5:
        return
    y = []
    for ts in testler.values():
        for t in ts:
            g = [sonuclar[m].get(t["id"]) for m in ad]
            g = [x for x in g if x is not None]
            if len(g) >= 5 and sum(g) <= 1 and t["aile"] != "temel":
                y.append({**{k: v for k, v in t.items() if k not in ("belge",)}, "gecen_model": sum(g), "bakilan_model": len(g)})
    with open(cikti / "denetim.jsonl", "w", encoding="utf-8") as f:
        for x in y:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"denetim: {len(y)} test bütün modellerde (en fazla biri hariç) kaldı -> {cikti / 'denetim.jsonl'}")


def kendall(a, b):
    c = d = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            q = (a[i] - a[j]) * (b[i] - b[j])
            c, d = c + (q > 0), d + (q < 0)
    return (c - d) / max(1, c + d)


def rapor(ozet, kat_ad, cikti):
    ad = sorted(ozet, key=lambda m: -ozet[m]["oku_skor"])
    p = lambda v: "-" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{100 * v:.1f}"
    y = []
    if all("tob" in ozet[m] for m in ad):
        ana = sorted(ad, key=lambda m: -ozet[m]["tob"]["skor"])
        y += [f"# TurkishOCR-Bench v{SURUM} sonuçları", "",
              "**Ana skor: TOB-Skor = √(Doğruluk × Kullanılabilirlik).** Doğruluk: birim test skoru (ailelerin kategori makro geçme oranı). "
              "Kullanılabilirlik: sayfa puanı 2^(−ceza/5), ceza = 100 × (5·kritik + 2,5·Türkçe karakter + 1·diğer orta + 0,1·hafif) / (kelime + formül tokenı); "
              "kapıya takılan sayfa 0; kategori makro. Temiz: kritik yok ve 100 kelimede en fazla 1 orta hata (katı ölçü). "
              "Kapı: boş, kesik, döngü ya da yabancı alfabe olan sayfa oranı. Kapsam: gövde parçalarının çıktıda bulunma oranı.", "",
              "| # | Model | **TOB-Skor** | Doğruluk | Kullanılabilirlik | Temiz | Düzeltilebilir | Güvenilmez | Kapı | Kapsam |", "|" + "---|" * 10]
        for i_, m in enumerate(ana, 1):
            o, e_, h_ = ozet[m], ozet[m]["ek_olcu"], ozet[m]["hukum"]
            y.append(f"| {i_} | {m} | **{o['tob']['skor']:.1f}** | {o['oku_skor']:.1f} | "
                     f"{o['kullanilabilirlik']['skor']:.1f} | {p(h_['temiz'])} | {p(h_['duzeltilebilir'])} | {p(h_['guvenilmez'])} | {p(e_['kapi'])} | {p(e_['kapsam'])} |")
        dk = list(ozet[ana[0]]["duyarlilik"])
        tau = lambda k: kendall([ozet[m]["tob"]["skor"] for m in ana], [ozet[m]["duyarlilik"][k] for m in ana])
        y += ["", "Duyarlılık (TOB sıralamasıyla Kendall τ): " + ", ".join(f"{k.replace('yarilanma', 'yarılanma ').replace('_turkce', ', Türkçe ağırlığı ')}: {tau(k):.3f}" for k in dk)]
        y += ["", "## Türkçe analizi (skora girmez)", "",
              "DER: okunan kelimelerde karakter düzeyinde eksik aksan (ş→s) ve fazla aksan (s→ş) oranı; İ/I ve ı/i nokta hatası ayrı. "
              "Kök/ek doğruluğu: zor metin parçalarındaki kelimelerde (Zeyrek). Fazlalık: çıktıda olup doğru metinde olmayan kelime oranı (kelime torbası).", "",
              "| Model | DER eksik | DER fazla | İ/I nokta | Kök doğr. | Ek doğr. | chrF P | chrF R | Fazlalık |", "|" + "---|" * 9]
        for m in ana:
            e_ = ozet[m]["ek_olcu"]
            y.append(f"| {m} | {p(e_['der_eksik'])} | {p(e_['der_fazla'])} | {p(e_['nokta'])} | {p(e_['kok_dogruluk'])} | {p(e_['ek_dogruluk'])} | "
                     f"{p(e_['chrf_p'])} | {p(e_['chrf_r'])} | {p(e_['fazlalik'])} |")
        mk = ("kok", "ek", "olumsuzluk", "yalniz_aksan", "buyuk_kucuk", "cozumsuz", "gercek_kelime", "eksik_kelime", "kelime")
        y += ["", "## Morfoloji (zor metin parçalarında kelime hataları, Zeyrek)", "",
              "kök: kök değişmiş; ek: kök doğru, ek yanlış; olumsuzluk: -ma/-me gibi anlamı tersine çeviren ek (kritik); yalnız aksan: harfler aynı, aksan/nokta farklı; "
              "çözümsüz: doğru kelime çözümlenemiyor (özel ad, yabancı); gerçek kelime: hatalı çıktı da geçerli bir Türkçe kelime.", "",
              "| Model | " + " | ".join(mk) + " |", "|" + "---|" * (len(mk) + 1)]
        for m in ana:
            mm = ozet[m]["ek_olcu"]["morf"]
            y.append(f"| {m} | " + " | ".join(str(mm.get(k, 0)) for k in mk) + " |")
        y += ["", "## Kategori bazında kullanılabilirlik", "", "| Model | " + " | ".join(kat_ad) + " |", "|" + "---|" * (len(kat_ad) + 1)]
        for m in ana:
            ku = ozet[m]["hukum"]["kategori_kullanilabilirlik"]
            y.append(f"| {m} | " + " | ".join(p(ku.get(k)) for k in kat_ad) + " |")
        y += ["", "## Kategori bazında temiz sayfa oranı", "", "| Model | " + " | ".join(kat_ad) + " |", "|" + "---|" * (len(kat_ad) + 1)]
        for m in ana:
            kt = ozet[m]["hukum"]["kategori_temiz"]
            y.append(f"| {m} | " + " | ".join(p(kt.get(k)) for k in kat_ad) + " |")
        y += [""]
    y += ["## Doğruluk: birim test aileleri", "", "Her aile: kategori içinde geçen test oranı, kategorilerin ortalaması. Doğruluk: ailelerin ortalaması. Üst/alt bilgi nötr; temel kapıdır, ortalamaya girmez.", "",
          "| Model | Doğruluk | " + " | ".join(O.AILE) + " |", "|" + "---|" * (len(O.AILE) + 2)]
    for m in ad:
        o = ozet[m]
        y.append(f"| {m} | {o['oku_skor']:.1f} | " + " | ".join(p(o["aile"][x]) for x in O.AILE) + " |")
    y += ["", "Test sayısı: " + ", ".join(f"{x} {ozet[ad[0]]['test_sayisi'][x]}" for x in O.BIRIM) + " (turkce paydası modele göre değişir)"]
    if all("ayrik" in ozet[m] for m in ad):
        ka = list(ozet[ad[0]]["ayrik"]["kategori"])
        y += ["", "## Ek: ayrık kategori skoru", "",
              "Formül kategorisi yalnız formül testleriyle, tablo kategorisi yalnız tablo testleriyle puanlanır; bu sayfaların metin, Türkçe, "
              "sayı, sıra, tire ve temel testleri akademik kategorisine katılır. Diğer kategoriler bütün aileleriyle. Skor: kategorilerin ortalaması.", "",
              "| Model | Ayrık skor | " + " | ".join(ka) + " |", "|" + "---|" * (len(ka) + 2)]
        for m in sorted(ad, key=lambda m: -ozet[m]["ayrik"]["skor"]):
            a_ = ozet[m]["ayrik"]
            y.append(f"| {m} | {a_['skor']:.1f} | "
                     + " | ".join("-" if a_["kategori"][k] is None else f"{a_['kategori'][k]:.1f}" for k in ka) + " |")
    ae = ozet[ad[0]].get("ayirt_edici")
    if ae:
        y += ["", "## Ek: ayırt edici testler", "",
              f"Bütün modellerin geçtiği {ae['hepsi_gecti']} test çıkarıldı, {ae['test']} test kaldı. Model kümesine bağlıdır: yeni model eklenince değişir, liderlik tablosuna girmez.", "",
              "| Model | Ayırt edici |", "|---|---|"]
        for m in sorted(ad, key=lambda m: -ozet[m].get("ayirt_edici", {}).get("skor", 0)):
            a_ = ozet[m].get("ayirt_edici")
            if a_:
                y.append(f"| {m} | {a_['skor']:.1f} |")
    y += ["", "## Türkçe alt türleri (havuzlanmış oran; turkce puanı bunların kategori içinde eşit ağırlıklı ortalaması)", "", "| Model | şapka (â î û) | büyük İ/I | diğer (ı ş ğ ç ö ü, fazla aksan) |", "|---|---|---|---|"]
    for m in ad:
        b = ozet[m]["birim_orani"]
        y.append(f"| {m} | {p(b['turkce/sapka'])} | {p(b['turkce/buyuk_I'])} | {p(b['turkce/diger'])} |")
    y += ["", "## Sayfa hükmü (MQM tarzı şiddet)", "",
          "Temiz: kritik hata yok ve 100 kelimede en fazla 1 orta hata. Güvenilmez: en az bir kritik hata (yanlış sayı, uydurma ya da başka kelime, "
          "3+ kelime eksik/fazla, atlanan metin parçası, [okunaksız] yerine uydurma, formül, tablo hücresi yanlış yerde, felaket). Kategori ortalaması.", "",
          "| Model | Temiz | Düzeltilebilir | Güvenilmez | En kötü kategoride temiz | Ceza / 100 kelime |", "|---|---|---|---|---|---|"]
    for m in sorted(ad, key=lambda m: -ozet[m]["hukum"]["temiz"]):
        h = ozet[m]["hukum"]
        y.append(f"| {m} | {p(h['temiz'])} | {p(h['duzeltilebilir'])} | {p(h['guvenilmez'])} | {p(h['en_kotu_kategori_temiz'])} ({h['en_kotu_kategori']}) | {h['ceza']:.1f} |")
    y += ["", "## Alt kümeler", "", "| Model | Tümü | Temel seçilmediği sayfalar | İncelenmiş sayfalar | Sentetik hariç |", "|---|---|---|---|---|"]
    for m in ad:
        o = ozet[m]
        y.append(f"| {m} | {o['oku_skor']:.1f} | {o['iz_temel_degil']:.1f} | {o['iz_incelenmis']:.1f} | {o['iz_sentetik_haric']:.1f} |")
    tk = sorted({k for m in ad for k in ozet[m]["teshis"]})
    y += ["", "## Tanı sayaçları", "", "| Model | " + " | ".join(k.replace("_", " ") for k in tk) + " |", "|" + "---|" * (len(tk) + 1)]
    for m in ad:
        y.append(f"| {m} | " + " | ".join(str(ozet[m]["teshis"].get(k, 0)) for k in tk) + " |")
    for x in O.AILE:
        y += ["", f"## {x}: kategori", "", "| Model | " + " | ".join(kat_ad) + " |", "|" + "---|" * (len(kat_ad) + 1)]
        for m in ad:
            y.append(f"| {m} | " + " | ".join(p(ozet[m]["aile_kategori"][x][k]) for k in kat_ad) + " |")
    (cikti / "rapor.md").write_text("\n".join(y) + "\n", encoding="utf-8")
    print("\n".join(y[:len(ad) + 6]))


if __name__ == "__main__":
    main()

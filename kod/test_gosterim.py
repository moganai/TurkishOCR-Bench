"""TurkishOCR-Bench regresyon testleri: gösterim eşdeğerlikleri ve puanlama kuralları.

Her satır, aynı içeriğin iki yazımının puanlayıcıda aynı tokenlara indiğini (ya da bilerek farklı kaldığını) sınar. Kural
değiştirilirse bu testler değişikliğin hangi eşdeğerliği bozduğunu gösterir. Kurallar dondurulmuştur: bir test
düşerse ya değişiklik geri alınır ya da sürüm yükseltilip test bilinçli olarak güncellenir.

Kullanım: python test_gosterim.py   (hepsi geçerse 0 ile çıkar)
"""
import sys

import eval as E
import oku_ortak as O
import oku_puanla as P

GOSTER = str.maketrans({E.UST: "^{", E.ALT: "_{", E.KAP: "}"})


def tok(md, kat="akademik"):
    return " ".join(E.coz(O.kategori_normalle(md, kat), E.NOKTA_DISI.get(kat, frozenset())).tok).translate(GOSTER)


# (açıklama, doğru metin, model çıktısı, kategori, aynı mı olmalı)
ESDEGER = [
    # basit satır içi matematik = Unicode = HTML
    ("alt simge LaTeX/Unicode", "ak hava ($O_2$ ve $N_2$)", "ak hava (O₂ ve N₂)", "akademik", True),
    ("alt simge LaTeX/HTML", "HNO$_3$ eklendi", "HNO<sub>3</sub> eklendi", "akademik", True),
    ("üst simge LaTeX/Unicode", "x² + y", "$x^2$ + y", "akademik", True),
    ("birim üst simge", "10 m² alan", "10 m$^{2}$ alan", "akademik", True),
    ("üs", "10⁵ Pa", "$10^{5}$ Pa", "akademik", True),
    ("derece", "25$^\\circ$C sıcak", "25°C sıcak", "akademik", True),
    ("Yunan harfi", "$\\alpha$ değeri", "α değeri", "akademik", True),
    ("\\mathbf sarmal", "$\\mathbf{C_e}$: denge", "**Cₑ:** denge", "akademik", True),
    ("iç içe \\mathrm (kimya)", "Verim: C₁₉H₃₂ClN₃O₂ (", "Verim: $\\mathrm{C_{19}H_{32}ClN_3O_2}$ (", "formul", True),
    ("\\text{} kimya", "$\\text{H}_2\\text{O}$ ile", "H₂O ile", "formul", True),
    ("aksan komutu", "Burada, $H_{i,\\ddot{o}}$ and $H_{i,h}$ sırasıyla", "Burada, Hᵢ,ö and Hᵢ,ₕ sırasıyla", "formul", True),
    ("matematikte harf arası boşluk", "$\\Delta W$ mg cinsinden", "ΔW mg cinsinden", "formul", True),
    ("çarpma işareti", "$(365 \\times 1) / 160$ gün", "(365 x 1) / 160 gün", "formul", True),
    # dipnot/kaynak üst simgesi: üst simgenin her yazımı aynı, düz yazı farklı
    ("kaynak listesi LaTeX/Unicode", "bildirilmiştir. $^{28,38}$ Sonografi", "bildirilmiştir.²⁸, ³⁸ Sonografi", "akademik", True),
    ("kaynak listesi LaTeX/HTML", "bildirilmiştir. $^{28,38}$ Sonografi", "bildirilmiştir.<sup>28, 38</sup> Sonografi", "akademik", True),
    ("kaynak listesi düz yazı", "bildirilmiştir. $^{28,38}$ Sonografi", "bildirilmiştir. 28,38 Sonografi", "akademik", False),
    # biçim etiketleri ve semboller
    ("altı çizili atama", "CH$_2$CH$_2$CH$_3$ x", "CH₂<u>CH₂</u>CH₃ x", "formul", True),
    ("HTML kalın/italik", "a kalın ve eğik b", "a <b>kalın</b> ve <i>eğik</i> b", "akademik", True),
    ("satır başı madde işareti", "Deprem sigortası", "■ Deprem sigortası", "akademik", True),
    ("ok çeşidi", "A → B", "A ➜ B", "akademik", True),
    # el yazısında büyük/küçük harf serbest; Yunan harfi ve İ/I noktası değil
    ("el yazısı büyük/küçük", "Özel Durum ve Gerekçelerinden", "özel durum ve gerekçelerinden", "el_yazisi", True),
    ("el yazısı Δ/δ", "Δ ile δ", "δ ile δ", "el_yazisi", False),
    ("el yazısı İ/I noktası", "ISTANBUL", "istanbul", "el_yazisi", False),
    ("akademikte büyük/küçük", "Özel Durum", "özel durum", "akademik", False),
    # Türkçe karakter ve ondalık ayırıcı farkı korunur
    ("Türkçe karakter", "çalışmada", "calismada", "akademik", False),
    ("ondalık virgül", "4,5 kg", "4.5 kg", "akademik", False),
]


def main():
    hata = 0
    for ad, g, h, kat, ayni in ESDEGER:
        a, b = tok(g, kat), tok(h, kat)
        if (a == b) != ayni:
            hata += 1
            print(f"KALDI  {ad}: beklenen {'aynı' if ayni else 'farklı'}\n       {a!r}\n       {b!r}")
    # tablo: boş hücre komşuluğu bozmaz
    iz = [["599 ÖDENEN", "", "22.500.000"], ["", "", ""]]
    if O.iliski(iz, 0, 0, "sag") != "22.500.000":
        hata += 1; print("KALDI  boş hücre sağ komşuluğu bozmamalı")
    # tablo: rowspan ile bölünmüş satırlar birleştirilmiş hali verir
    bol = [["Parametre", "Ocak"], ["Sıcaklık", "0.2"], ["", "9.2"]]
    if O.satir_birlestir(bol) != [["Parametre", "Ocak"], ["Sıcaklık", "0.2 9.2"]]:
        hata += 1; print("KALDI  rowspan satır birleştirme")
    # dipnot listesi ondalık sayı değil dipnot işaretidir
    c = E.coz(O.gosterim_normalle("bildirilmiştir.$^{28,38}$ Sonografi"), frozenset())
    if dict(O.dipnot_isaretleri(c)) != {"28,38": 1}:
        hata += 1; print("KALDI  dipnot listesi tanınmalı")
    # harf aralıklı başlık uydurma sayılmaz
    G = E.coz("NİFAK şiiri", frozenset())
    H = E.coz("N İ F A K şiiri", frozenset())
    if P.uydurma(G, H, []):
        hata += 1; print("KALDI  harf aralıklı başlık uydurma sayılmamalı")
    # olumsuzluk: iki anlamlı kelime olumsuzluk sayılmaz, gerçek olumsuzluk sayılır
    if O.morf_tur("okuma", "okumu")[0] == "olumsuzluk" or O.morf_tur("gelmedi", "geldi")[0] != "olumsuzluk":
        hata += 1; print("KALDI  olumsuzluk eki tespiti")
    # kullanılabilirlik: hatasız sayfa 1, kapı 0, kısa sayfa düzleştirmesi
    s = {"kritik": 0, "orta": 0, "hafif": 0, "kelime": 300, "tur": {}, "kapi": False}
    if P.kullanilabilirlik(s) != 1.0 or P.kullanilabilirlik({**s, "kapi": True}) != 0.0:
        hata += 1; print("KALDI  kullanılabilirlik sınırları")
    k1 = P.kullanilabilirlik({**s, "kritik": 1, "kelime": 70})
    if not 0.49 < k1 < 0.51:
        hata += 1; print(f"KALDI  70 kelimede 1 kritik ≈ 0,50 olmalı ({k1:.3f})")
    # sıra yalnız tek doğal okuma sırası olan kategorilerde ölçülür
    if not P.sira_olculur("akademik") or P.sira_olculur("el_yazisi") or P.sira_olculur("tablo"):
        hata += 1; print("KALDI  sıra ölçülen kategoriler")
    # sadakat ve sıra Doğruluk ailelerinde değil
    if "sadakat" in O.AILE or "sira" in O.AILE or "sira" not in O.KAPI_KAPSAM:
        hata += 1; print("KALDI  aile listesi (sadakat yok, sıra yalnız sayfa hatası)")
    toplam = len(ESDEGER) + 9
    print(f"{toplam - hata}/{toplam} test geçti" + ("" if not hata else f", {hata} kaldı"))
    return 1 if hata else 0


if __name__ == "__main__":
    sys.exit(main())

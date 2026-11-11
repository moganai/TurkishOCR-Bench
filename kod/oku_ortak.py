"""OKU-Bench v1 ortak parçalar. Dönüştürücü (coz, KaTeX kanonu, tablo ızgarası) eval.py'den gelir; burada test birimleri kurulur.

Aileler: metin, turkce, sayi, sira, tablo, formul, tire, temel. Üst/alt bilgi nötr: test üretilmez, puanı etkilemez.
"""
import collections
import math
import re
import unicodedata

import eval as E

if not E.KATEX.exists():
    E.KATEX = E.KOK / "katex/katex.min.js"


def bicim_sil(s):
    """eval.bicim_sil ile aynı, tek fark: kalın/eğik işareti satır içinde eşlenir. Satır aşan eşleşme '*, ** ve ***' gibi içerik yıldızını
    iki paragraf aşağıdaki kalın başlıkla eşliyor, ikisini de bozuyordu. ** kelime içinde kapanabilir (**tedavisi**nde)."""
    s = re.sub(rf"</?(?:{E.ETIKET}|{E.TABLO_ET}|br)\b[^<>]*>", " ", s, flags=re.I)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"^[ \t]*#{1,6}[ \t]+", "", s, flags=re.M)
    s = re.sub(r"^[ \t]*(?:[-*_][ \t]*){3,}$", "", s, flags=re.M)
    s = re.sub(r"^[ \t]*>[ \t]+(?=\D)", "", s, flags=re.M)
    s = re.sub(r"^[ \t]*\|[ \t]*|[ \t]*\|[ \t]*$", "", s, flags=re.M)
    s = re.sub(r"^[ \t]*(?:[-*+•·▪◦‣●○][ \t]+)+(?=\S)", "", s, flags=re.M)
    for _ in range(2):
        s = re.sub(r"(?<!\*)\*\*\*(?=[^\s*])([^\n]+?)(?<=[^\s*])\*\*\*(?!\*)", r"\1", s)
        s = re.sub(r"(?<!\*)\*\*(?=[^\s*])([^\n]+?)(?<=[^\s*])\*\*(?!\*)", r"\1", s)
        s = re.sub(r"(?<![\w*])\*(?=[^\s*])([^\n]+?)(?<=[^\s*])\*(?![\w*])", r"\1", s)
        s = re.sub(r"(?<![\w_])__(?=\S)([^\n]+?)(?<=\S)__(?![\w_])", r"\1", s)
        s = re.sub(r"(?<![\w_])_(?=[^\s_])([^\n]+?)(?<=[^\s_])_(?![\w_])", r"\1", s)
        s = re.sub(r"~~(?=\S)([^\n]+?)(?<=\S)~~", r"\1", s)
    s = re.sub(r"\\([*_#\[\]()\-.!~|+%&$`{}>])", r"\1", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)
    s = re.sub(r"\[([^\]\n]+)\]\((?:https?:[^)]*|#[^)]*)\)", r"\1", s)
    return E.html.unescape(s)


E.bicim_sil = bicim_sil

V0 = E.V0
# temel aile değil kapıdır: sayfada felaket (boş, kesik, döngü, yabancı alfabe) varsa sayfanın bütün testleri kalır.
# kapsam da aile değildir: atlanan metni sayfa hükmüne taşır, birim test ortalamasına girmez.
# sadakat ailesi kaldırıldı (kullanıcı kararı 2026-11-07): görseldeki yazım hatasını düzeltmek sıradan okuma hatasıdır,
# metin testinde kalır ve sayfa cezasına harf/kelime hatası olarak girer
# sıra Doğruluk ortalamasına girmez (kullanıcı kararı 2026-11-07): tavanda bir aile ortalamayı şişirmesin; ters sıra sayfa
# hatası olarak kullanılabilirliği düşürmeye devam eder (kapsam gibi)
AILE = ("metin", "turkce", "sayi", "tablo", "formul", "tire", "olmamali")
# Puanlama birimleri: turkce üç zorluk alt türünün eşit ağırlıklı ortalamasıdır (117K kolay ı/ş/ğ testi şapkayı ve İ/I'yı ezmesin)
BIRIM = ("metin", "turkce/sapka", "turkce/buyuk_I", "turkce/diger", "sayi", "tablo", "formul", "tire", "olmamali")
KAPI_KAPSAM = ("temel", "kapsam", "sira")  # Doğruluk ortalamasına girmeyen, yalnız sayfa hatası olan aileler
NADIR_ZIPF = 3.0  # wordfreq Türkçe listesinde bu sıklığın altı (listede olmayan kelime) nadir sayılır
CUMLE_SONU = set(".!?:…;")
PARCA = 12  # METİN testinin en fazla token sayısı
SIRA_CAPA = 8  # okuma sırası testinde paragraf ucundan alınan token
SIRA_ESIK = 90  # çapa bulma benzerliği (aksansız, küçük harf)
TABLO_KOTA = 40  # tablo başına en fazla ilişki testi
UYDURMA_KOSU = 4  # sayfada olmayan art arda kelime sayısı
# taban metin modeli: değerlendirmedeki ad (klasör adı ya da kısa ad) -> sayfalar.jsonl'daki "temel" değeri
TEMEL_MODEL = {"muse-spark-1.3-contributor": "Muse", "gemma-4-31b": "Gemma", "qwen3.8-flash-next": "Qwen", "deepseek-v4.1-flash": "DeepSeek",
               "Muse": "Muse", "Gemma": "Gemma", "Qwen3.8": "Qwen", "Qwen": "Qwen", "DeepSeek": "DeepSeek"}

TR_HASSAS = set("çğıöşüÇĞİÖŞÜâîûÂÎÛ")
ISARET_ON = set("-+±<>≤≥~≈")  # '=' sayının işareti değildir ("=2,01" ile "= 2,01" aynı)
ISARET_BITISIK = set("-+±")  # yalnız bitişikse işaret (aksi tire/ayraç); karşılaştırma işaretleri boşluktan bağımsız bağlanır
ISARET_SON = set("%‰°")
CIFT = {}
for (_a, _b), _ad in ("ıi", "ı/i"), ("İI", "İ/I"), ("şs", "ş/s"), ("ŞS", "ş/s"), ("ğg", "ğ/g"), ("ĞG", "ğ/g"), ("çc", "ç/c"), ("ÇC", "ç/c"), \
        ("öo", "ö/o"), ("ÖO", "ö/o"), ("üu", "ü/u"), ("ÜU", "ü/u"), ("âa", "şapka"), ("îi", "şapka"), ("îı", "şapka"), ("ûu", "şapka"), \
        ("ÂA", "şapka"), ("ÎI", "şapka"), ("Îİ", "şapka"), ("ÛU", "şapka"):
    CIFT[frozenset((_a, _b))] = _ad
YABANCI_BETIK = ("CJK", "HIRAGANA", "KATAKANA", "HANGUL", "ARABIC", "HEBREW", "CYRILLIC", "DEVANAGARI", "THAI", "BENGALI", "TAMIL", "ARMENIAN", "GEORGIAN")


def tr_fold(t):
    """Türkçe harfleri ve şapkayı katlar; büyük/küçük harf korunur (İ->I, ı->i)."""
    return t.translate(E.FOLD)


def tr_kucuk(s):
    return s.replace("I", "ı").replace("İ", "i").lower()


def hassas(t):
    """Türkçe karakter testi gereken kelime: ç ğ ı ö ş ü İ, şapkalı harf ya da noktasız büyük I (kısa ASCII kısaltmalar hariç)."""
    if not E.kelime_mi(t):
        return False
    if any(c in TR_HASSAS for c in t):
        return True
    return "I" in t and not (t.isascii() and t.isupper() and len(t) <= 4)


def birim(t):
    if t["aile"] != "turkce":
        return t["aile"]
    k = t["kelime"]
    return "turkce/sapka" if any(c in "âîûÂÎÛ" for c in k) else "turkce/buyuk_I" if any(c in "İI" for c in k) else "turkce/diger"


def harf_farki(g, h):
    """Aynı katlamaya inen iki kelimenin farklı harf çiftleri -> alt tür adları."""
    return [CIFT.get(frozenset((a, b)), "diger") for a, b in zip(g, h) if a != b]


def kisa_formul(c):
    """1-2 tokenlık satır içi formül ($x$, $\\alpha$): formül sayılmaz, metindir."""
    y = set()
    for f in c.formul:
        if not f["blok"] and f["b"] - f["a"] < 3:
            y.update(range(f["a"], f["b"]))
    return y


def evren(c, alanlar=("g",)):
    """Metin testlerinin token evreni: istenen alanlar + kısa satır içi formül."""
    kf = kisa_formul(c)
    return [c.alan[i] in alanlar or i in kf for i in range(len(c.tok))]


def kosular(c, alanlar=("g",)):
    """Paragraf, görsel ve okunaksız sınırında kesilen ardışık token aralıkları [(a, b)]."""
    ok = evren(c, alanlar)
    sinir = set(c.paragraf_bas) | set(c.fig) | set(c.okn)
    y, a = [], None
    for i in range(len(c.tok) + 1):
        if a is not None and (i == len(c.tok) or i in sinir or not ok[i]):
            y.append((a, i))
            a = None
        if i < len(c.tok) and ok[i] and a is None:
            a = i
    return y


def bol(a, b, n=PARCA):
    """Aralığı en fazla n tokenlık eşit parçalara böler."""
    k = max(1, math.ceil((b - a) / n))
    s = [a + round(i * (b - a) / k) for i in range(k + 1)]
    return [(s[i], s[i + 1]) for i in range(k) if s[i + 1] > s[i]]


def ham(c, a, b):
    return c.metin[c.bas[a]:c.bas[b - 1] + len(c.tok[b - 1])]


def dizi(tok):
    return "\x1f" + "\x1f".join(tok) + "\x1f"


def say_ortusen(metin, parca):
    return len(re.findall("(?=" + re.escape(parca) + ")", metin))


def capa_norm(tok):
    return " ".join(tr_kucuk(tr_fold(t)) for t in tok if E.kelime_mi(t))


def sayi_dizileri(c, alanlar=None):
    """Rakam içeren her token, bitişik işaretleriyle (-4,5  %10  25°). Para birimi yeri biçimdir, sayıya katılmaz.
    Tablo sayıları hücre hücre alınır: hücre metni token boşluğuyla birleşik olduğundan işaret hücre içinde bitişik sayılır, komşu hücreye geçmez."""
    y = []
    for i, t in enumerate(c.tok):
        if (alanlar and c.alan[i] not in alanlar) or c.alan[i] == "t" or not any(ch.isdigit() for ch in t) or E.YAPI.search(t):
            continue
        a, b = i, i
        while a > 0 and c.tok[a - 1] in ISARET_ON and (c.tok[a - 1] not in ISARET_BITISIK or _bitisik(c, a - 1, a)):
            a -= 1
        while b + 1 < len(c.tok) and c.tok[b + 1] in ISARET_SON and _bitisik(c, b, b + 1):
            b += 1
        y.append(_harften_ayir("".join(c.tok[a:b + 1])))
    if not alanlar or "t" in alanlar:
        for t, _, _ in c.tablo:
            for x in t.izgara:
                for h in x:
                    y += _hucre_sayilari(h.split(" "))
    return y


DIPNOT_LISTE = re.compile(r"\d{1,3}(?:[,;–-]\d{1,3})*")  # 25 · 28,38 · 8-10: tek dipnot ya da kaynak listesi


def dipnot_isaretleri(c):
    """Gövdedeki dipnot işaretleri: kelime ya da noktalamadan hemen sonra üst simgedeki 1-3 haneli tam sayı (metin²⁵, cümle.²⁶).
    Üs (10⁵) ve birim (m², cm³: önceki token 3 harften kısa) dışarıda. Sayı -> adet."""
    y = collections.Counter()
    for i in range(2, len(c.tok) - 1):
        t, onc = c.tok[i], c.tok[i - 2]
        if c.tok[i - 1] == E.UST and c.tok[i + 1] == E.KAP and DIPNOT_LISTE.fullmatch(t) and c.alan[i] != "t" \
                and ((E.kelime_mi(onc) and len(onc) >= 3 and not any(ch.isdigit() for ch in onc)) or onc in ".,;:)\"'’”"):
            y[t] += 1
    return y


_SAYI_HARF = re.compile(r"^(.*?\d)((?=[^\W\d_]*[a-zçğıöşüâîû])[^\W\d_]{3,})$|^((?=[^\W\d_]*[a-zçğıöşüâîû])[^\W\d_]{3,})(\d.*)$")


def _harften_ayir(t):
    """Boşluksuz yazılmış sayı+kelime (35Kontrol) ya da kelime+sayı (hatırlamalıyız71): sayı kısmı. Kısa birim/kod (4-CH, CO2, 5km) korunur."""
    m = _SAYI_HARF.match(t)
    return (m.group(1) or m.group(4)) if m else t


def _hucre_sayilari(tok):
    y = []
    for i, t in enumerate(tok):
        if not any(ch.isdigit() for ch in t) or E.YAPI.search(t):
            continue
        a, b = i, i
        while a > 0 and tok[a - 1] in ISARET_ON:
            a -= 1
        while b + 1 < len(tok) and tok[b + 1] in ISARET_SON:
            b += 1
        y.append(_harften_ayir("".join(tok[a:b + 1])))
    return y


def _bitisik(c, i, j):
    return c.metin[c.bas[i] + len(c.tok[i]):c.bas[j]] == ""


def ayirici_cevir(s):
    return s.translate(str.maketrans({",": ".", ".": ","}))


DIPNOT = re.compile(r"\s*\^\s*\{?\s*[\w*†‡,\s–-]{1,8}\}?\s*")


def formul_satirlari(md):
    """[(kanon, token_sayisi, blok, hata, tex)]: her satır ayrı birimdir (aligned ile ayrı $$ satırları aynı sayılır), numara ayrılır."""
    s = E.latex_tablo(E.ozel_temizle(md))
    y = []
    for m in E.MAT_RE.finditer(s):
        tex = E.tex_al(m)
        if not tex:
            continue
        blok = m.group("a") is not None or m.group("b") is not None or m.group("c") is not None
        for sat in E.tex_on_isle(tex)[0]:
            k = E.KANON.get(sat) or E.BOZUK + sat
            tok = E.tokenler(k)
            if not blok and DIPNOT.fullmatch(sat):
                continue  # tabansız üst simge ($^{23}$): dipnot numarası, formül değil
            y.append((E.carpim_nokta("".join(tok)).replace("×", "x"), len(tok), blok, k.startswith(E.BOZUK), sat))  # \\times = x
    return y


def baslik_ust(izgara, c):
    """Sütun başlığı: ilk satırda soldaki ilk dolu hücre (birleşik başlık birden çok sütunu kapsar)."""
    for k in range(c, -1, -1):
        if izgara[0][k]:
            return izgara[0][k]
    return ""


def baslik_sol(izgara, r):
    """Satır başlığı: ilk sütunda yukarıdaki ilk dolu hücre (birleşik satır başlığı)."""
    for k in range(r, -1, -1):
        if izgara[k][0]:
            return izgara[k][0]
    return ""


def satir_birlestir(izgara):
    """rowspan ile alt alta bölünmüş satırları (ilk sütunu boş devam satırları) bir üst satırla birleştirir: aynı tablo hücrede
    alt alta (<br>) yazılmışsa bu biçimle eşleşir. Değişiklik yoksa None."""
    y, degisti = [], False
    for x in izgara:
        if y and x and not x[0] and any(x[1:]) and len(x) == len(y[-1]):
            y[-1] = [a if not b else (b if not a else a + " " + b) for a, b in zip(y[-1], x)]
            degisti = True
        else:
            y.append(list(x))
    return y if degisti else None


def iliski(izgara, r, c, tur):
    # sağ/alt komşu boş hücreleri atlar: borç/alacak sütunlu kayıtta tutarın boş sütundan sonra gelmesi, rowspan'in bıraktığı
    # boşluk gibi düzen tercihleri komşuluğu bozmaz
    if tur == "sag":
        return next((v for v in izgara[r][c + 1:] if v), "")
    if tur == "alt":
        return next((x[c] for x in izgara[r + 1:] if c < len(x) and x[c]), "")
    if tur == "ust_baslik":
        return baslik_ust(izgara, c) if r > 0 else ""
    if tur == "sol_baslik":
        return baslik_sol(izgara, r) if c > 0 else ""
    return ""


def betikler(s):
    """Metindeki Latin/Yunan dışı yazı sistemleri."""
    y = set()
    for ch in set(s):
        if ord(ch) > 0x24F and ch.isalpha():
            ad = unicodedata.name(ch, "")
            for b in YABANCI_BETIK:
                if ad.startswith(b):
                    y.add(b)
    return y


def tekrar_dongusu(G, H):
    """8'li dizi 4'ten fazla ve doğru metinden çok geçiyor, fazlalık sayfayı şişiriyor."""
    if len(H.tok) - len(G.tok) < max(40, 0.2 * len(G.tok)):
        return False
    say = collections.Counter(tuple(H.tok[i:i + 8]) for i in range(len(H.tok) - 7))
    say_g = collections.Counter(tuple(G.tok[i:i + 8]) for i in range(len(G.tok) - 7))
    return any(n > 4 and n > say_g[g] and sum(E.kelime_mi(t) for t in g) >= 2 for g, n in say.items())


# --- sıklık, zor token, morfoloji (v2) ---
_ZIPF = {}


def zipf(t, dil="tr"):
    """wordfreq Zipf sıklığı (0: listede yok)."""
    k = (t, dil)
    if k not in _ZIPF:
        from wordfreq import zipf_frequency
        _ZIPF[k] = zipf_frequency(tr_kucuk(t) if dil == "tr" else t.lower(), dil)
    return _ZIPF[k]


def zor_neden(c, i, bas):
    """Tokenin görsele bakmadan tahmin edilmesi zor olma nedeni: sayi, kod, eski_imla, ozel_ad, nadir; değilse None."""
    t = c.tok[i]
    if any(ch.isdigit() for ch in t):
        return "sayi"
    if not E.kelime_mi(t):
        return None
    harf = [ch for ch in t if ch.isalpha()]
    if len(harf) >= 2 and (t.isupper() or any(ch in "_/@" for ch in t)):
        return "kod"
    if any(ch in "âîûÂÎÛ" for ch in t):
        return "eski_imla"
    if t[0].isupper() and i > bas and c.tok[i - 1] not in CUMLE_SONU and c.tok[i - 1] not in "\"“‘'(":
        return "ozel_ad"
    if len(t) >= 4 and zipf(t) < NADIR_ZIPF:
        return "nadir"
    return None


_MORF, _ANALIZ = None, {}


def morf(w):
    """Zeyrek (Zemberek) çözümlemeleri [(kök, ekler)]; çözümlenemeyen kelimede boş liste."""
    global _MORF
    if w in _ANALIZ:
        return _ANALIZ[w]
    if _MORF is None:
        import logging
        logging.getLogger("zeyrek").setLevel(logging.ERROR)  # her çözümlemede uyarı düzeyinde satır basıyor
        import zeyrek
        _MORF = zeyrek.MorphAnalyzer()
    # analyze() metni NLTK punkt_tab ile böler; veri yoksa hata verir ve her kelime "çözümsüz" görünür (sadakat testleri hiç üretilmez).
    # Tek kelime verdiğimizden kelime düzeyindeki _parse doğrudan çağrılır.
    try:
        y = [(tr_kucuk(a.dict_item.lemma), tuple(m[0].id_ for m in a.morphemes)) for a in _MORF._parse(w) if a is not None]
    except (KeyError, ValueError, IndexError):
        y = []
    _ANALIZ[w] = y
    return y


def morf_tur(g, h):
    """Yanlış okunan kelimenin morfolojik türü: yalniz_aksan, buyuk_kucuk, kok, ek, olumsuzluk (anlamı tersine çeviren ek),
    cozumsuz (doğru kelime çözümlenemiyor: özel ad, yabancı kelime). gercek: çıktı da geçerli bir Türkçe kelime."""
    if tr_fold(g) == tr_fold(h):
        return "yalniz_aksan", bool(morf(h))
    if tr_kucuk(g) == tr_kucuk(h):
        return "buyuk_kucuk", False
    ag, ah = morf(g), morf(h)
    gercek = bool(ah)
    if not ag:
        return "cozumsuz", gercek
    kg = {k for k, _ in ag}
    if not ah:
        # geçersiz çıktı: kökü sağlam kalmışsa ek hatası
        return ("ek" if any(tr_kucuk(h).startswith(k[:max(2, len(k) - 2)]) for k in kg) else "kok"), False
    if not kg & {k for k, _ in ah}:
        return "kok", gercek
    # olumsuzluk ancak bir tarafın bütün çözümlemeleri olumsuz, öbürününkilerin hiçbiri değilse: "okuma" hem isim hem oku-ma
    # olabildiğinden tek bir olumsuz çözümleme yetmez
    neg = lambda m: "Neg" in m or "Unable" in m  # yeterlilik olumsuzu (olamadığını, duyulamaz) da olumsuzdur
    hep = lambda a: all(neg(m) for _, m in a)
    hic = lambda a: not any(neg(m) for _, m in a)
    return ("olumsuzluk" if (hep(ag) and hic(ah)) or (hic(ag) and hep(ah)) else "ek"), gercek


HARFLER = "abcçdefgğhıijklmnoöprsştuüvyzâîû"


def sadakat_duzgun(t):
    """Doğru metindeki özgün yazım hatası: kelime sözlükte yok ve Zeyrek'le çözümlenmiyor, tek düzenlemeyle sık ve geçerli bir
    kelimeye dönüşüyor (kitaap -> kitap). Düzgün biçim döner; değilse None. Özel ad, büyük harf, yabancı kelime dışarıda."""
    if not E.kelime_mi(t) or len(t) < 4 or not t.isalpha() or not t.islower():
        return None
    if zipf(t) > 0 or zipf(t, "en") > 0 or morf(t):
        return None
    aday = set()
    for k in range(len(t)):
        aday.add(t[:k] + t[k + 1:])
        if k + 1 < len(t):
            aday.add(t[:k] + t[k + 1] + t[k] + t[k + 2:])
        for h in HARFLER:
            aday.add(t[:k] + h + t[k + 1:])
    for k in range(len(t) + 1):
        for h in HARFLER:
            aday.add(t[:k] + h + t[k:])
    aday.discard(t)
    iyi = sorted(((zipf(a), a) for a in aday if zipf(a) >= 3.5), reverse=True)
    for _, a in iyi[:3]:
        if morf(a):
            return a
    return None


def yazim_duzeltme_mi(g, h):
    """Model görseldeki baskı/yazım hatasını düzeltmiş mi: doğru metindeki kelime sözlükte yok ve çözümlenmiyor, modelin yazdığı
    ona en çok 2 harf uzaklıkta sık ya da çözümlenen bir kelime (göstegesi -> göstergesi, Swhwartz -> Shwartz). Sadakat
    hatasıdır: Doğruluk'ta kalır, sayfanın kullanılabilirliğini düşürmez."""
    gk, hk = tr_kucuk(g), tr_kucuk(h)
    if gk == hk or len(gk) < 4 or not gk.isalpha() or not hk.isalpha():
        return False
    from rapidfuzz.distance import Levenshtein
    if Levenshtein.distance(gk, hk) > 2:
        return False
    if zipf(gk) > 0 or zipf(gk, "en") > 0 or morf(gk):
        return False
    return zipf(hk) >= 3.0 or bool(morf(hk))


def tum_buyuk(w):
    """Tamamen büyük harfle yazılmış kelime (en az iki harf): başlık, ilan başlığı, kısaltma."""
    h = [c for c in w if c.isalpha()]
    return len(h) >= 2 and all(c.isupper() for c in h)


def chrf(ref, hyp, n=6, beta=2.0):
    """chrF (Popović 2015): karakter 1..6-gram kesinlik ve duyarlılık ortalamaları, F-beta. (kesinlik, duyarlılık, F) döner."""
    r, h = ref.replace(" ", ""), hyp.replace(" ", "")
    P, R = [], []
    for k in range(1, n + 1):
        rc = collections.Counter(r[i:i + k] for i in range(len(r) - k + 1))
        hc = collections.Counter(h[i:i + k] for i in range(len(h) - k + 1))
        ort = sum((rc & hc).values())
        if hc:
            P.append(ort / sum(hc.values()))
        if rc:
            R.append(ort / sum(rc.values()))
    p, rr = (sum(P) / len(P) if P else 0.0), (sum(R) / len(R) if R else 0.0)
    f = (1 + beta ** 2) * p * rr / (beta ** 2 * p + rr) if p + rr else 0.0
    return p, rr, f


# --- gösterim normalleştirme (v2.1): aynı şeyin farklı yazımı ceza almasın ---
# Doğru metne ve model çıktısına karşılaştırmadan önce aynı ön işlem uygulanır (dosyalara dokunulmaz).
YUNAN = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ",
         "vartheta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ",
         "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ",
         "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
         "times": "×", "cdot": "·", "pm": "±", "mp": "∓", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
         "approx": "≈", "sim": "~", "infty": "∞", "degree": "°", "circ": "°", "rightarrow": "→", "to": "→", "leftarrow": "←",
         "Rightarrow": "⇒", "leftrightarrow": "↔", "rightleftharpoons": "⇌", "ldots": "…", "dots": "…", "cdots": "⋯",
         "partial": "∂", "nabla": "∇", "prime": "′", "%": "%", "#": "#", "&": "&", "_": "_", "$": "$"}
SARMAL = r"\\(?:mathrm|mathbf|mathit|mathsf|mathtt|text|textbf|textit|textrm|boldsymbol|bm|operatorname)\s*"
_SARMAL_BAS = re.compile(SARMAL + r"\{")


def sarmal_ac(s):
    """Yalnız yazı biçimini değiştiren komutları (\\mathrm{…}, \\text{…}) dengeli parantezle açar: içindeki alt simgeli kimyasal
    formül de çözülür (\\mathrm{C_{19}H_{32}ClN_3O_2} = C_{19}H_{32}ClN_3O_2 = C₁₉H₃₂ClN₃O₂)."""
    while (m := _SARMAL_BAS.search(s)):
        derinlik, j = 1, m.end()
        while j < len(s) and derinlik:
            derinlik += {"{": 1, "}": -1}.get(s[j], 0)
            j += 1
        if derinlik:
            break  # kapanmayan parantez: olduğu gibi bırak
        s = s[:m.start()] + s[m.end():j - 1] + s[j:]
    return s
_SATIR_ICI = re.compile(r"(?<![\\$])\$(?!\$)([^$\n]{1,200}?)(?<!\\)\$(?!\$)")
_MADDE = re.compile(r"(?m)^(\s*)[■□▪▫●○◆◇►▶➤➢◦‣⁃✹✱✳]+\s*")  # onay kutuları (☐ ☑ ✓ ✔) madde işareti değil: işaret bilgisi taşır
_SAG_OK = re.compile(r"[➜➔➙➛➝➞➟➠➡⟶⇨⟹⇒➨➧]")
_ARA_NOKTA = re.compile(r"(?<=\s)[·•■□▪▫●○◆◇►▶➤➢◦‣⁃✹✱✳]+(?=\s)")  # satır içinde maddeleri ayıran işaretler


# aksan komutları: \\ddot{o} -> ö, \\dot{I} -> İ, \\hat{a} -> â, \\c{c} -> ç (birleştirici işaret + NFC)
AKSAN = {"ddot": "\u0308", "\"": "\u0308", "dot": "\u0307", ".": "\u0307", "hat": "\u0302", "^": "\u0302", "bar": "\u0304", "=": "\u0304",
         "tilde": "\u0303", "~": "\u0303", "breve": "\u0306", "u": "\u0306", "check": "\u030c", "v": "\u030c", "acute": "\u0301",
         "'": "\u0301", "grave": "\u0300", "`": "\u0300", "c": "\u0327", "vec": "\u20d7"}
_AKSAN = re.compile(r"\\(ddot|dot|hat|bar|tilde|breve|check|acute|grave|vec|[\"'.^=~`]|[cuv](?=\s*\{))\s*(?:\{\s*(\\[ij]|[A-Za-z])\s*\}|(?<=[\"'.^=~`])([A-Za-z]))")
E.ALT_K.setdefault("\ua700", "c")  # ꜀ (U+A700) alt simge c gibi kullanılıyor (Iₛ꜀ = I_{sc})
ALT_HARF = "".join(E.ALT_K)
UST_HARF = "".join(E.UST_K)
# Unicode alt/üst simge dizileri: virgülle ayrılmış parçalar tek simgedir (Hᵢ,ₕ = H_{i,h}); Unicode'da alt simge karşılığı olmayan
# son harf virgülden sonra düz yazılmışsa (Hᵢ,ö) o da simgeye dahildir
_ALT_DIZI = re.compile(f"[{ALT_HARF}]+(?:,[{ALT_HARF}]+)*(?:,[^\\W\\d_](?![^\\W\\d_]))?")
_UST_DIZI = re.compile(f"[{UST_HARF}]+(?:[,ʼ’'˒][{UST_HARF}]+)*")


def aksan_coz(s):
    def f(m):
        h = m.group(2) or m.group(3)
        h = {"\\i": "ı", "\\j": "ȷ"}.get(h, h)
        return unicodedata.normalize("NFC", h + AKSAN[m.group(1)])
    return _AKSAN.sub(f, s)


def unicode_simge(md):
    md = _ALT_DIZI.sub(lambda m: "<sub>" + "".join(E.ALT_K.get(c, c) for c in m.group(0)) + "</sub>", md)
    return _UST_DIZI.sub(lambda m: "<sup>" + "".join(E.UST_K.get(c, "," if c in "ʼ’'˒" else c) for c in m.group(0)) + "</sup>", md)


def _simge(ic, etiket):
    ic = re.sub(r"^\{(.*)\}$", r"\1", ic.strip())
    return f"<{etiket}>{ic}</{etiket}>"


def basit_matematik(ic):
    """Komut içermeyen satır içi formülün metin karşılığı (O_2 -> O<sub>2</sub>, ^{8,9} -> <sup>8,9</sup>, \\alpha -> α); değilse None."""
    s = aksan_coz(re.sub(r"\^\s*\{?\s*\\circ\s*\}?", "°", ic))
    s = re.sub(r"(\\(?:text|textrm|textbf|textit|operatorname)\s*\{)([^{}]*)\}", lambda m: m.group(1) + m.group(2).replace(" ", "\x01") + "}", s)
    s = sarmal_ac(s)
    s = re.sub(r"\\([A-Za-z]+|[%#&_$])", lambda m: YUNAN.get(m.group(1), m.group(0)) + ("\x02" if m.group(1) not in YUNAN else ""), s)
    s = re.sub(r"\\[,;:! ]", "\x01", s)
    # matematik kipinde harfler arası boşluk çizilmez ($\\Delta W$ = ΔW); rakam ve işaret çevresindeki boşluk tokenleri ayırır, kalır
    s = re.sub(r"(?<=[^\W\d_])\s+(?=[^\W\d_])", "", s)
    s = s.replace("\x02", " ").replace("\x01", " ").replace("{}", "")
    if "\\" in s:
        return None  # \frac, \sqrt, \sum...: gerçek formül, formül ailesinde ölçülür
    s = re.sub(r"_\s*(\{[^{}]*\}|[^\s{}])", lambda m: _simge(m.group(1), "sub"), s)
    s = re.sub(r"\^\s*(\{[^{}]*\}|[^\s{}])", lambda m: _simge(m.group(1), "sup"), s)
    return None if re.search(r"[{}_^]", s) else s


# 2026-11-06 denetimi (Muse/GPT, 134 sayfa) sonrası eklenen gösterim eşdeğerlikleri
_TAG_DISARI = re.compile(r"\$\$((?:(?!\$\$).)*?)\\tag\*?\{([^{}]*)\}((?:(?!\$\$).)*?)\$\$", re.S)
_ITALIK_KELIME_ICI = re.compile(r"(?<![\w*])\*([^\s*$][^*$\n]{0,200}?[^\s*$])\*(?=[^\W\d_])")  # *Mercüssofer*deki, *“mülk-i Rûm”*un
_SUB = re.compile(r"<sub\b[^<>]*>(.*?)</sub>", re.S | re.I)
_SUP = re.compile(r"<sup\b[^<>]*>(.*?)</sup>", re.S | re.I)
_BICIM_ETIKET = re.compile(r"</?(?:u|ins|mark|span|small|big|font|b|strong|i|em)\b[^<>]*>", re.I)
_CAPTION = re.compile(r"(<table\b[^<>]*>)\s*<caption\b[^<>]*>(.*?)</caption>", re.S | re.I)


def gosterim_normalle(md):
    """Satır içi basit formülleri metne çevirir, madde işaretlerini siler, ok ve ara nokta çeşitlerini birleştirir.
    Denetim (2026-11-06) eklemeleri: ˒ = virgül; LaTeX {,} = virgül; denklem numarası \\tag{n} = metindeki (n); kelimeye bitişik
    italik yıldızları silinir; alt simge düz yazıya iner ve küçük harfe çevrilir (H_{i,h} = Hᵢ,ₕ; NO_X = NOₓ; I_d = Id; V_1 = V1:
    alt simge kaybı gösterim farkıdır); tablo <caption>'ı tablonun önüne paragraf olur; hücrede tireyle biten satırdan sonraki <br>
    birleştirilir (4-4-5-<br>6-6 = 4-4-5-6-6)."""
    md = md.replace("\u02d2", ",").replace("{,}", ",").replace("{.}", ".")
    # satır içi HTML biçim etiketleri iz bırakmadan silinir: CH₂<u>CH₂</u>CH₃ (NMR'de altı çizili atama) = CH₂CH₂CH₃; etiketin
    # bıraktığı token sınırı kelimeyi bölmesin
    md = _BICIM_ETIKET.sub("", md)
    md = _TAG_DISARI.sub(lambda m: f"$${m.group(1)}{m.group(3)}$$ ({m.group(2).strip('() ')})", md)
    md = mat_disi(md, lambda t: _ITALIK_KELIME_ICI.sub(r"\1", t))  # formül içindeki çarpım yıldızı italik işareti değildir
    md = _CAPTION.sub(r"\2\n\n\1", md)
    md = re.sub(r"(?<=\w-)\s*<br\s*/?>\s*", "", md, flags=re.I)
    md = _SATIR_ICI.sub(lambda m: basit_matematik(m.group(1)) or m.group(0), md)
    md = unicode_simge(md)
    # üst simge içindeki boşluk ve virgülle ayrılmış komşu üst simgeler: ^{28,38} = ^{28, 38} = ²⁸,³⁸ = ²⁸, ³⁸ = <sup>28, 38</sup>
    md = re.sub(r"</sup>\s*([,;])\s*<sup>", r"\1", md, flags=re.I)
    md = _SUP.sub(lambda m: "<sup>" + re.sub(r"\s+", "", m.group(1)) + "</sup>", md)
    md = _SUB.sub(lambda m: tr_kucuk(m.group(1)), md)
    md = md.replace("×", "x")  # çarpma işareti: görselde x de × de yazılır, model hangisini seçerse seçsin aynıdır
    md = _MADDE.sub(r"\1", md)
    md = _SAG_OK.sub("→", md)
    return _ARA_NOKTA.sub("", md)


BUYUK_KUCUK_SERBEST = {"el_yazisi"}  # el yazısında büyük/küçük harf ayırt edilmez (c/C, o/O, s/S elde aynı yazılır)
# formül aralıkları: $$ $$, $ $ ve \\[ \\], \\( \\) ayraçları (DeepSeek, Nemotron bu ayraçlarla yazar; korunmazsa el yazısında
# formül küçük harfe çevrilir, a*b*c içindeki yıldızlar italik sanılıp silinir)
_MATEMATIK = re.compile(r"\$\$.*?\$\$|(?<!\\)\\\[.+?(?<!\\)\\\]|(?<!\\)\\\(.+?(?<!\\)\\\)|(?<!\\)\$[^$\n]*?(?<!\\)\$", re.S)


def mat_disi(md, f):
    """f'yi yalnız formül dışındaki metne uygular; formüller olduğu gibi kalır."""
    y, son = [], 0
    for m in _MATEMATIK.finditer(md):
        y += [f(md[son:m.start()]), m.group(0)]
        son = m.end()
    return "".join(y + [f(md[son:])])


_LATIN_BUYUK = re.compile(r"[A-ZÇĞİÖŞÜÂÎÛ]+")


def kucuk_metin(md):
    """Matematik dışındaki Latin/Türkçe harfleri Türkçe kurallarıyla küçültür (İ -> i, I -> ı). Formül ve Yunan harfleri
    (Δ/δ) olduğu gibi kalır: orada büyük/küçük harf farklı değişkendir."""
    k = lambda t: _LATIN_BUYUK.sub(lambda m: tr_kucuk(m.group(0)), t)
    y, son = [], 0
    for m in _MATEMATIK.finditer(md):
        y += [k(md[son:m.start()]), m.group(0)]
        son = m.end()
    return "".join(y + [k(md[son:])])


def kategori_normalle(md, kat):
    """Kategoriye özgü kurallar (el yazısında büyük/küçük harf; normalleştirmeden önce, formüller dokunulmadan) + gösterim
    normalleştirmesi."""
    return gosterim_normalle(kucuk_metin(md) if kat in BUYUK_KUCUK_SERBEST else md)


def gorunum_komutsuz(tex):
    """Formülün yalnız görünümü değiştiren komutlardan arınmış, boşluksuz hali (\\mathrm{W} = W, \\left( = (, _{1} = _1, \\ln = ln)."""
    s = sarmal_ac(tex.replace("$", ""))
    s = re.sub(r"\\(left|right|big|Big|bigg|Bigg)\b", "", s)
    s = re.sub(r"\\(ln|log|exp|sin|cos|tan|lim|max|min)\b", r"\1", s)
    s = re.sub(r"\\[,;:! ]", "", s)
    s = re.sub(r"([_^])\{(\\?[A-Za-z0-9])\}", r"\1\2", s)
    return re.sub(r"\s+", "", s)

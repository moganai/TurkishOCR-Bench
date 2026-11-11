"""OKU-Bench katı değerlendirici. Kurallar KURALLAR.md'de; kısaca:

- Doğru metin ve model çıktısı aynı dönüştürücüden geçer (Markdown, HTML, LaTeX, Unicode yazımı puanı değiştirmez).
- Formül KaTeX'in ürettiği yapıyla karşılaştırılır: x^2, x², <sup>2</sup> aynı; bir işaret farkı formülün tamamını yanlış yapar.
- Her kelime sayılır, kısmi puan yoktur: bir harf yanlışsa kelime yanlıştır. NED/TEDS/CDM yalnız yardımcıdır.
- Sayfa düzeni: taşınan blok (sütun, üst bilgi) kelime hatası sayılmaz, sıra ekseninde ölçülür.

Kullanım: python eval.py --cikti <klasor> ad=<cikti_klasoru> [ad=<cikti_klasoru> ...]
Çıktı klasöründe <kategori>/<id>.md ya da <id>.md aranır; kayit.jsonl varsa kesilme bilgisi ("bitis") oradan okunur.
"""
import argparse
import bisect
import collections
import concurrent.futures as cf
import heapq
import html
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np
from apted import APTED, Config
from bs4 import BeautifulSoup
from lxml import etree
from rapidfuzz.distance import Levenshtein
from scipy.optimize import linear_sum_assignment

KOK = Path(__file__).resolve().parent
# Depo kökü (kod/ klasörünün üstü); varsayılan veri yolları buna göredir
V0 = os.environ.get("TOB_KOK") or str(KOK.parent)
KATEX = KOK / "katex/katex.min.js"

# --- Özel karakterler: tokenlaştırıcı bunları tek işaret sayar (kullanıcı metninde geçmez) ---
UST, ALT, KAP, KESIR, ORTA, KOK_, KOKN, SATIR, HUCRE = (chr(0xE101 + i) for i in range(9))
AKSAN_AC = {"bar": "\uE110", "hat": "\uE111", "tilde": "\uE112", "vec": "\uE113", "dot": "\uE114", "ddot": "\uE115"}
YAPI = re.compile("[\uE100-\uE1FF]")
M_AC, M_KAP, T_AC, T_KAP, FIG, H_AC, H_KAP, F_AC, F_KAP, OKUNAKSIZ = (chr(0xE200 + i) for i in range(10))

ORTAK = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-", "∗": "*", "⋅": "·", "∙": "·", "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "′": "'", "“": '"', "”": '"', "„": '"', "‟": '"', "∣": "|", "∥": "‖", "⩽": "≤", "⩾": "≥", "≦": "≤", "≧": "≥", "ϕ": "φ", "ϵ": "ε", "ϑ": "θ", "ϱ": "ρ",
    "∆": "Δ", "∑": "Σ", "∏": "Π", "µ": "μ", "Ω": "Ω", "Å": "Å", "⟶": "→", "⟹": "⇒", "\u00a0": " ", "\u2009": " ", "\u200a": " ", "\u2002": " ", "\u2003": " ", "\u202f": " ",
    "\u00ad": "", "\u200b": "", "\u200c": "", "\u200d": "", "\u2060": "", "\u2061": "", "\u2062": "", "\u2063": "", "\ufeff": "",
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "…": "...", "⋯": "...", "ﬅ": "st", "☐": " ", "☒": "X", "☑": "X", "☓": "X", "✗": "X", "✘": "X",
})
UST_K = dict(zip("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱᵃᵇᶜᵈᵉᶠᵍʰʲᵏˡᵐᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ", "0123456789+-=()niabcdefghjklmoprstuvwxyzABDEGHIJKLMNOPRTUVW"))
ALT_K = dict(zip("₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼ", "0123456789+-=()aeoxhklmnpstij"))
KESIR_K = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5", "⅙": "1/6", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8"}
AKSAN_B = {"ˉ": "\u0304", "¯": "\u0304", "‾": "\u0304", "ˆ": "\u0302", "^": "\u0302", "˜": "\u0303", "~": "\u0303", "˙": "\u0307", "¨": "\u0308", "˘": "\u0306", "´": "\u0301", "`": "\u0300", "ˋ": "\u0300", "ˇ": "\u030c", "˚": "\u030a", "⃗": "\u20d7", "→": "\u20d7"}
AKSAN_ADI = {"\u0304": "bar", "\u0302": "hat", "\u0303": "tilde", "\u20d7": "vec", "\u0307": "dot", "\u0308": "ddot"}
MAT_BASI = {"script": 0x1D49C, "bold-script": 0x1D49C, "double-struck": 0x1D538, "fraktur": 0x1D504, "bold-fraktur": 0x1D504}
KELIME = r"(?:[^\W_]|[\u0300-\u036f\u20d7])+"
# ondalık/oran ayırıcısı yalnız iki rakam arasında birleştirir (4,5 · 2012:146 · 1/2); harften sonra gelen "murâd,5-6" ya da
# "Cilt:2" bölünür, yoksa içindeki sayı ayrı token olmaz ve sayı testi üretilmez/kalır
TOKEN = re.compile(rf"{KELIME}(?:(?:(?<=\d)[.,:/](?=\d)|[-'](?={KELIME})){KELIME})*|[\uE100-\uE1FF]|\S")
KRITIK_ISARET = set("<>≤≥=≠±%+×÷≈‰°")
TURKCE = set("çğıöşüÇĞİÖŞÜ")
FOLD = str.maketrans("çğıöşüâîûÇĞİÖŞÜÂÎÛ", "cgiosuaiuCGIOSUAIU")
OKUNAKSIZ_RE = re.compile(r"\[\s*(?:okunaks[ıi]z|okunam[ıa]yan|unreadable|illegible|unclear|\.\.\.)\s*\]", re.I)
ETIKET = ("div|p|span|center|font|b|i|u|em|strong|small|big|mark|section|article|main|figcaption|h[1-6]|li|ul|ol|blockquote|code|pre|a|hr|title|"
          "page_?number|page-number|page_?header|page-header|page_?footer|page-footer|nav|aside|body|html|s|del|ins|abbr|cite|q|dl|dt|dd")
TABLO_ET = "table|thead|tbody|tfoot|tr|td|th|caption|colgroup|col"
TIRE_KALDI = {"silme", "bolunme", "birlesme"}  # satir sonu testini gecemeyen durumlar


# --- Formül: LaTeX -> KaTeX MathML -> kanonik dizi ---
def yazi_tipi(taban, c):
    """Kaligrafik, çift çizgili, fraktur harfler düz harften ayrı tek karakter olur (kalın ve eğik sayılmaz)."""
    if "A" <= c <= "Z":
        return chr(taban + ord(c) - 65)
    if "a" <= c <= "z":
        return chr(taban + 26 + ord(c) - 97)
    return c


def tex_on_isle(tex):
    """Numarayı ayırır, hizalama ortamını satırlara böler. Döner: (satirlar, numara)."""
    t = tex.strip()
    t = re.sub(r"\\(nonumber|notag|displaystyle|textstyle)\b", " ", t)
    t = re.sub(r"\\label\{[^{}]*\}", " ", t)
    no = []

    def al(m):
        no.append(m.group(1))
        return " "
    t = re.sub(r"\\tag\*?\{((?:[^{}]|\{[^{}]*\})*)\}", lambda m: no.append("(" + m.group(1).strip("() ") + ")") or " ", t)
    t = re.sub(r"\\tag\*?\s*(\d{1,3}[a-z]?)(?![\dA-Za-z])", lambda m: no.append("(" + m.group(1) + ")") or " ", t)  # süslü parantezsiz: \tag*4
    # nokta dizisiyle sağa yaslanmış denklem numarası (... ... ... 1): noktalar düzen, sayı numaradır
    t = re.sub(r"\s*(?:\.{4,}|(?:(?:\.{2,}|…|\\[lc]?dots)\s*){2,})\s*\(?\s*(\d{1,3}[a-z]?)\s*\)?\s*$", lambda m: no.append("(" + m.group(1) + ")") or " ", t)
    t = re.sub(r"\\eqno\s*\{?\s*(\(?[^{}$]*?\)?)\s*\}?\s*$", al, t)
    t = re.sub(r"(?:\\quad|\\qquad|\\hfill|\\hspace\{[^{}]*\}|\\,|\\;|~)+\s*(\(\s*[\dA-Za-z]+(?:[.\-]\d+)*[a-z]?\s*\))\s*$", al, t)
    # boşluk komutu olmadan, kapanan ayraçtan sonra yazılmış numara: ... n_{land}) (4)
    t = re.sub(r"(?<=[)\]}])\s+(\(\s*\d{1,3}[a-z]?\s*\))\s*$", al, t)
    # formülün sonundaki cümle noktalaması (virgül, nokta) formülün parçası değildir; alt simgenin içinde kalmış olsa da
    # (\eta_{ID.} = \eta_{ID}.). Üç nokta ve \, komutu korunur
    t = re.sub(r"(?<![.,;\\])[.,;](\}*)\s*$", r"\1", t)
    m = re.fullmatch(r"\s*\\begin\{(aligned|align\*?|alignat\*?|gather\*?|gathered|split|multline\*?|eqnarray\*?|equation\*?)\}(.*)\\end\{\1\}\s*", t, re.S)
    if m or "\\\\" in t:
        ortam = bool(m)
        satirlar, derin, b = [], 0, ""
        i, g = 0, m.group(2) if m else t
        while i < len(g):
            if g.startswith("\\begin", i):
                derin += 1
            elif g.startswith("\\end", i):
                derin -= 1
            elif g[i] == "{":
                derin += 1
            elif g[i] == "}":
                derin -= 1
            if g[i] == "\\" and i + 1 < len(g):
                if g[i + 1] == "\\" and derin == 0:
                    satirlar.append(b)
                    b = ""
                else:
                    b += g[i:i + 2]
                i += 2
                continue
            b += "" if (g[i] == "&" and derin == 0 and ortam) else g[i]
            i += 1
        satirlar.append(b)
        satirlar = [s.strip() for s in satirlar if s.strip()]
        if len(satirlar) > 1 or ortam:
            temiz = []
            for s in satirlar:  # numara her satirin sonunda olabilir
                ic, n = tex_on_isle(s)
                temiz += ic
                no += [n] if n else []
            return temiz, " ".join(no)
    return ([t.strip()] if t.strip() else []), " ".join(no)


NODE = """
const k=require(process.argv[1]);const G=JSON.parse(require('fs').readFileSync(0,'utf8'));
const O={output:'mathml',displayMode:true,throwOnError:true,strict:'ignore',trust:false,macros:{'\\\\degree':'^{\\\\circ}','\\\\celsius':'^{\\\\circ}C'}};
console.log(JSON.stringify(G.map(t=>{try{return k.renderToString(t,O)}catch(e){return null}})));
"""


def katex_toplu(texler):
    r = subprocess.run(["node", "-e", NODE, str(KATEX)], input=json.dumps(texler), capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def mml(e):
    t = etree.QName(e).localname if isinstance(e.tag, str) else ""
    k = list(e)
    if t in ("annotation", "annotation-xml", "mphantom", "mspace", ""):
        return ""
    if t in ("mi", "mn", "mo", "mtext", "ms"):
        s = (e.text or "").translate(ORTAK)
        if t == "mtext":
            return s
        v = MAT_BASI.get(e.get("mathvariant"))
        if v:
            return "".join(yazi_tipi(v, c) for c in s)
        return f" {s} " if t == "mi" and len(s) > 1 else s
    if t == "mfrac":
        return KESIR + mml(k[0]) + ORTA + mml(k[1]) + KAP
    if t == "msqrt":
        return KOK_ + "".join(mml(c) for c in k) + KAP
    if t == "mroot":
        return KOKN + mml(k[1]) + ORTA + mml(k[0]) + KAP
    if t in ("msup", "mover", "msub", "munder", "msubsup", "munderover"):
        taban = mml(k[0])
        if t == "mover" and e.get("accent") == "true":
            return aksan(taban, mml(k[1]))
        if t == "munder" and e.get("accentunder") == "true":
            return taban
        if t in ("msup", "mover"):
            return taban + ust_yaz(mml(k[1]))
        if t in ("msub", "munder"):
            return taban + ALT + mml(k[1]) + KAP
        return taban + ALT + mml(k[1]) + KAP + ust_yaz(mml(k[2]))
    if t == "mtable":
        # Satir kirilmasi cizimi degistirmez; yalniz gercek matris ayraci korunur
        matris = not (e.get("columnalign") or "").startswith("left") and max((len(tr) for tr in k), default=0) > 1
        return (SATIR if matris else "").join((HUCRE if matris else "").join(mml(td) for td in tr) for tr in k)
    return "".join(mml(c) for c in k)


def ust_yaz(s):
    y = s.strip()
    if y and set(y) <= {"'"}:
        return y
    if y == "∘":
        return "°"
    return UST + s + KAP


def aksan(taban, isaret):
    b = AKSAN_B.get(isaret.strip(), isaret.strip())
    if len(taban.strip()) == 1:
        return unicodedata.normalize("NFC", taban.strip() + b)
    return AKSAN_AC.get(AKSAN_ADI.get(b, ""), "\uE116") + taban + KAP


def mathml_kanon(m):
    x = re.search(r"<math.*?</math>", m, re.S)
    k = etree.fromstring(x.group(0).encode(), etree.XMLParser(recover=True))
    # KaTeX formül içindeki ç ve ş harflerini "c\\c", "c¸" diye verir; tek harfe döner
    return unicodedata.normalize("NFC", mml(k).replace("\\c", "\u0327").replace("¸", "\u0327"))


KANON = {}
BOZUK = "\uE1FE"  # render edilemeyen LaTeX'in başına konur: hiçbir doğru formülle eşleşmez, içindeki kelimeler sayılır


def tex_kanon(tex):
    """Döner: (dogrusal, numara, hata). Render edilemeyen LaTeX ham kalır, hiçbir doğru formülle eşleşmez."""
    satirlar, no = tex_on_isle(tex)
    y, hata = [], False
    for s in satirlar:
        k = KANON.get(s) or BOZUK + s
        hata = hata or k.startswith(BOZUK)
        y.append(k)
    return " ".join(y), no, hata


def kanon_doldur(texler, dosya=None):
    """Tüm LaTeX'leri bir kez render eder; sonuç diske yazılır."""
    if dosya and Path(dosya).exists():
        KANON.update(json.load(open(dosya, encoding="utf-8")))
    yeni = sorted({s for t in texler for s in tex_on_isle(t)[0]} - KANON.keys())
    for i in range(0, len(yeni), 5000):
        p = yeni[i:i + 5000]
        for s, m in zip(p, katex_toplu(p)):
            KANON[s] = mathml_kanon(m) if m else BOZUK + re.sub(r"\\[a-zA-Z]+|[\\{}^_&$]", " ", s)
    if dosya and yeni:
        json.dump(KANON, open(dosya, "w", encoding="utf-8"), ensure_ascii=False)
    return yeni


# --- Metin: çıktı biçimlerini ortak forma çevirme ---
def ozel_temizle(s):
    s = re.sub(r"<think>.*?</think>", " ", s, flags=re.S)
    s = re.sub(r"^[ \t]*```[\w-]*[ \t]*$", "", s, flags=re.M)
    s = re.sub(r"\[[xX]\]", "X", s)  # isaret kutusu: [x], X, ☒ aynı; [ ] ve ☐ boş
    s = s.replace("[ ]", " ")
    return unicodedata.normalize("NFC", s).translate(ORTAK)


MAT_RE = re.compile(
    r"\$\$(?P<a>.+?)\$\$|\\\[(?P<b>.+?)\\\]|(?P<c>\\begin\{(?P<ad>equation\*?|align\*?|alignat\*?|gather\*?|multline\*?|eqnarray\*?)\}.+?\\end\{(?P=ad)\})"
    r"|\\\((?P<d>.+?)\\\)|(?<![\\$])\$(?P<e>[^$\n]+?)(?<!\\)\$(?!\$)", re.S)
TEX_IZ = re.compile(r"[\\^_{}=]")


def tex_al(m):
    """Yakalanan LaTeX; para birimi gibi duran $...$ için None. Boşluklu $ x $ yazımı da formüldür."""
    tex = next(v for k, v in m.groupdict().items() if v and k != "ad")
    if m.group("e") is None or TEX_IZ.search(tex):
        return tex
    if tex != tex.strip() and len(tex.strip()) > 3:
        return None
    if m.end() < len(m.string) and m.string[m.end()].isdigit():
        return None
    return tex


def latex_tablo(s):
    """\\begin{tabular} -> HTML (matematik korunmadan önce çalışır)."""
    def cevir(m):
        g = re.sub(r"\\(hline|toprule|midrule|bottomrule)\b|\\c(?:line|midrule)(?:\([^)]*\))?\{[^}]*\}", "", m.group(1))
        satirlar = [x for x in re.split(r"(?<!\\)\\\\(?:\[[^\]]*\])?", g) if x.strip()]
        y = "<table>"
        for x in satirlar:
            y += "<tr>"
            for h in re.split(r"(?<!\\)&", x):
                c, r = 1, 1
                mc = re.match(r"\s*\\multicolumn\{(\d+)\}\{[^{}]*\}\{(.*)\}\s*$", h, re.S)
                if mc:
                    c, h = int(mc.group(1)), mc.group(2)
                mr = re.match(r"\s*\\multirow\{(\d+)\}\{[^{}]*\}\{(.*)\}\s*$", h, re.S)
                if mr:
                    r, h = int(mr.group(1)), mr.group(2)
                h = re.sub(r"\\text(?:bf|it|rm|sc|tt)\{((?:[^{}]|\{[^{}]*\})*)\}", r"\1", h).replace("\\&", "&").replace("\\%", "%").replace("\\_", "_")
                y += f'<td colspan="{c}" rowspan="{r}">{h.strip()}</td>'
            y += "</tr>"
        return y + "</table>"
    return re.sub(r"\\begin\{tabular\*?\}(?:\{[^{}]*\})*(?:\[[^\]]*\])?(.*?)\\end\{tabular\*?\}", cevir, s, flags=re.S)


def formul_listesi(md):
    """Yalnız LaTeX dizgileri (toplu render için)."""
    s = latex_tablo(ozel_temizle(md))
    return [t for t in (tex_al(m) for m in MAT_RE.finditer(s)) if t]


def ust_alt_cevir(s):
    def ces(m):
        return UST + "".join(UST_K[c] for c in m.group(0)) + KAP

    def ces2(m):
        return ALT + "".join(ALT_K[c] for c in m.group(0)) + KAP
    s = re.sub("[" + "".join(UST_K) + "]+", ces, s)
    s = re.sub("[" + "".join(ALT_K) + "]+", ces2, s)
    s = re.sub("[" + "".join(KESIR_K) + "]", lambda m: KESIR + KESIR_K[m.group(0)].replace("/", ORTA) + KAP, s)
    s = re.sub(r"√(" + KELIME + ")", lambda m: KOK_ + m.group(1) + KAP, s)
    s = re.sub(r"<sup\b[^<>]*>(.*?)</sup>", lambda m: ust_yaz(m.group(1)), s, flags=re.S | re.I)
    s = re.sub(r"<sub\b[^<>]*>(.*?)</sub>", lambda m: ALT + m.group(1) + KAP, s, flags=re.S | re.I)
    return s


def harf_kanon(s):
    """Matematik yazı tipleri: kalın ve eğik düzle aynı, kaligrafik/çift çizgili/fraktur ayrı."""
    if s.isascii():
        return s
    y = []
    for c in s:
        if ord(c) >= 0x2100 and c.isalpha():
            ad = unicodedata.name(c, "")
            b = MAT_BASI["double-struck"] if "DOUBLE-STRUCK" in ad else MAT_BASI["script"] if "SCRIPT" in ad else MAT_BASI["fraktur"] if ("FRAKTUR" in ad or "BLACK-LETTER" in ad) else 0
            if b or ad.startswith("MATHEMATICAL"):
                d = unicodedata.normalize("NFKC", c)
                y.append(yazi_tipi(b, d) if b else d)
                continue
        y.append(c)
    return "".join(y)


def bicim_sil(s):
    """Kalın, eğik, başlık, madde ve kaçış işaretleri; birebir metin kalır."""
    s = re.sub(rf"</?(?:{ETIKET}|{TABLO_ET}|br)\b[^<>]*>", " ", s, flags=re.I)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"^[ \t]*#{1,6}[ \t]+", "", s, flags=re.M)
    s = re.sub(r"^[ \t]*(?:[-*_][ \t]*){3,}$", "", s, flags=re.M)
    s = re.sub(r"^[ \t]*>[ \t]+(?=\D)", "", s, flags=re.M)
    s = re.sub(r"^[ \t]*\|[ \t]*|[ \t]*\|[ \t]*$", "", s, flags=re.M)
    s = re.sub(r"^[ \t]*(?:[-*+•·▪◦‣●○][ \t]+)+(?=\S)", "", s, flags=re.M)
    for _ in range(2):
        s = re.sub(r"(?<![\w*])\*\*(?=\S)(.+?)(?<=\S)\*\*(?![\w*])", r"\1", s, flags=re.S)
        s = re.sub(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])", r"\1", s)
        s = re.sub(r"(?<![\w_])__(?=\S)(.+?)(?<=\S)__(?![\w_])", r"\1", s, flags=re.S)
        s = re.sub(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])", r"\1", s)
        s = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"\1", s)
    s = re.sub(r"\\([*_#\[\]()\-.!~|+%&$`{}>])", r"\1", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)
    s = re.sub(r"\[([^\]\n]+)\]\((?:https?:[^)]*|#[^)]*)\)", r"\1", s)
    return html.unescape(s)


def yer_tutucu_ac(s, formuller):
    """Hücre ya da satır içi metindeki formül yer tutucularını doğrusal biçimle değiştirir."""
    def f(m):
        return tex_kanon(formuller[int(m.group(1))][0])[0] + " " + tex_kanon(formuller[int(m.group(1))][0])[1]
    return re.sub(rf"{M_AC}(\d+){M_KAP}", f, s)


def dolgu(s):
    """Noktalı, çizgili dolgu: sayısı okunamaz, tek biçime iner (görselde ........ uzunluğu ölçülmez)."""
    s = re.sub(r"\.(?:[ \t]*\.){2,}", "...", s)
    s = re.sub(r"_(?:[ \t]*_){2,}", "___", s)
    return re.sub(r"-(?:[ \t]*-){2,}", "---", s)


def tokenler(s):
    return TOKEN.findall(dolgu(s))


def hucre_kanon(metin, formuller):
    s = harf_kanon(bicim_sil(ust_alt_cevir(metin).strip()))
    s = yer_tutucu_ac(s, formuller)
    return " ".join(tokenler(OKUNAKSIZ_RE.sub(" ", s)))


class Tablo:
    """Hücre ızgarası. Birleşik hücrenin metni sol üstte, kalan hücreler boş: colspan'lı HTML ile boş hücreli boru tablosu aynı olur."""

    def __init__(self, satirlar):
        izgara, dolu = [], {}
        for r, sat in enumerate(satirlar):
            c, y = 0, []
            for metin, cs, rs in sat:
                while (r, c) in dolu:
                    y.append(dolu.pop((r, c)))
                    c += 1
                y.append(metin)
                for i in range(1, cs):
                    y.append("")
                    c += 1
                for rr in range(1, rs):
                    for i in range(cs):
                        dolu[(r + rr, c - cs + 1 + i)] = ""
                c += 1
            while (r, c) in dolu:
                y.append(dolu.pop((r, c)))
                c += 1
            izgara.append(y)
        g = max((len(x) for x in izgara), default=0)
        izgara = [x + [""] * (g - len(x)) for x in izgara]
        izgara = [x for x in izgara if any(x)]
        if izgara:
            sut = [c for c in range(g) if any(x[c] for x in izgara)]
            izgara = [[x[c] for c in sut] for x in izgara]
        self.izgara = izgara
        self.hucre = sum(1 for x in izgara for c in x if c)


def html_tablo(h, formuller):
    temiz = re.sub(rf"<(?!/?(?:{TABLO_ET}|br)\b)", "&lt;", h, flags=re.I)
    temiz = re.sub(r"<br\s*/?>", " ", temiz, flags=re.I)
    t = BeautifulSoup(temiz, "html.parser").find("table")
    if t is None:
        return Tablo([])
    for c in t.find_all("caption"):
        c.decompose()
    sat = []
    for tr in t.find_all("tr"):
        y = []
        for td in tr.find_all(["td", "th"]):
            try:
                cs, rs = max(int(td.get("colspan", 1) or 1), 1), max(int(td.get("rowspan", 1) or 1), 1)
            except ValueError:
                cs, rs = 1, 1
            y.append((hucre_kanon(td.get_text(" "), formuller), min(cs, 100), min(rs, 200)))
        sat.append(y)
    return Tablo(sat)


def boru_tablolari(s, formuller, ofset):
    """Boru tablolarını yer tutucuya çevirir: ayırıcı satırlı ya da art arda en az iki çok sütunlu satır."""
    sat, cikti, tablolar, i = s.split("\n"), [], [], 0
    ayirici = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
    cok = lambda x: x.count("|") - x.count("\\|") >= 2
    while i < len(sat):
        j = i
        if "|" in sat[i] and (i + 1 < len(sat) and ayirici.match(sat[i + 1]) and "|" in sat[i + 1] or (cok(sat[i]) and i + 1 < len(sat) and cok(sat[i + 1]))):
            j = i + 1
            while j < len(sat) and "|" in sat[j]:
                j += 1
            y = []
            for x in sat[i:j]:
                if ayirici.match(x):
                    continue
                x = re.sub(r"^\s*\||\|\s*$", "", x)
                y.append([(hucre_kanon(c.replace("\\|", "|"), formuller), 1, 1) for c in re.split(r"(?<!\\)\|", x)])
            cikti.append(f"{T_AC}{ofset + len(tablolar)}{T_KAP}")
            tablolar.append(Tablo(y))
            i = j
        else:
            cikti.append(sat[i])
            i += 1
    return "\n".join(cikti), tablolar


class Cozum:
    """Düz metin + token dizisi + alanlar. alan: 'g' gövde, 'u' üst, 'a' alt, 't' tablo, 'f' formül."""

    def __init__(self):
        self.tok, self.alan = [], []
        self.bas = []  # token başlangıç konumu
        self.formul = []  # {a, b, blok, hata}
        self.tablo = []  # (Tablo, a, b)
        self.fig = []  # token konumu (bu konumdan önce görsel var)
        self.okn = []  # okunaksız konumu
        self.paragraf_bas = set()
        self.metin = ""


def coz(md, atla=frozenset()):
    s = latex_tablo(ozel_temizle(md))
    formuller = []

    def mat(m):
        tex = tex_al(m)
        if not tex:
            return m.group(0)
        blok = m.group("a") is not None or m.group("b") is not None or m.group("c") is not None
        formuller.append((tex, blok))
        return f"{M_AC}{len(formuller) - 1}{M_KAP}"
    s = MAT_RE.sub(mat, s)
    s = ust_alt_cevir(s)
    # Görseller: içerik atılır, altyazı kalır
    s = re.sub(r"<figure\b[^<>]*/>", FIG, s, flags=re.I)

    def figur(m):
        alt = re.search(r"<figcaption[^<>]*>(.*?)</figcaption>", m.group(0), re.S | re.I)
        return FIG + (" " + alt.group(1) if alt else "")
    s = re.sub(r"<figure\b[^<>]*>.*?</figure>", figur, s, flags=re.S | re.I)
    s = re.sub(r"</?figure\b[^<>]*>|<img\b[^<>]*>", FIG, s, flags=re.I)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", FIG, s)
    s = OKUNAKSIZ_RE.sub(OKUNAKSIZ, s)
    # Tablolar
    tablolar = []

    def tab(m):
        tablolar.append(html_tablo(m.group(0) if m.group(0).lower().endswith("</table>") else m.group(0) + "</table>", formuller))
        return f"\n{T_AC}{len(tablolar) - 1}{T_KAP}\n"
    s = re.sub(r"<table\b.*?(?:</table>|\Z)", tab, s, flags=re.S | re.I)
    s, boru = boru_tablolari(s, formuller, len(tablolar))
    tablolar += boru
    s = re.sub(r"<header\b[^<>]*>", f"\n{H_AC}\n", s, flags=re.I)
    s = re.sub(r"</header>", f"\n{H_KAP}\n", s, flags=re.I)
    s = re.sub(r"<footer\b[^<>]*>", f"\n{F_AC}\n", s, flags=re.I)
    s = re.sub(r"</footer>", f"\n{F_KAP}\n", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = harf_kanon(bicim_sil(s))
    c = Cozum()
    parca = []
    uz = 0
    aralik = []  # (bas, son, alan, ek)
    bolge = "g"
    bolge_bas = 0

    def yaz(x):
        nonlocal uz
        x = dolgu(x)
        parca.append(x)
        uz += len(x)
    isaret = []  # (konum, tur)
    for p in re.split(f"({M_AC}\\d+{M_KAP}|{T_AC}\\d+{T_KAP}|[{FIG}{H_AC}{H_KAP}{F_AC}{F_KAP}{OKUNAKSIZ}])", s):
        if not p:
            continue
        if p[0] == M_AC:
            tex, blok = formuller[int(p[1:-1])]
            lin, no, hata = tex_kanon(tex)
            if blok:
                yaz("\n")
            a = uz
            yaz(lin)
            aralik.append((a, uz, "f", {"blok": blok, "hata": hata}))
            yaz(" " + no + " " if no else "")
            if blok:
                yaz("\n")
        elif p[0] == T_AC:
            t = tablolar[int(p[1:-1])]
            yaz("\n")
            a = uz
            for sat in t.izgara:
                yaz(" ".join(x for x in sat if x) + "\n")
            aralik.append((a, uz, "t", {"tablo": t}))
        elif p == FIG or p == OKUNAKSIZ:
            isaret.append((uz, p))
            yaz(" ")
        elif p in (H_AC, F_AC):
            yaz("\n")
            bolge, bolge_bas = ("u" if p == H_AC else "a"), uz
        elif p in (H_KAP, F_KAP):
            if bolge != "g":
                aralik.append((bolge_bas, uz, bolge, {}))
            yaz("\n")
            bolge = "g"
        else:
            yaz(p)
    if bolge != "g":
        aralik.append((bolge_bas, uz, bolge, {}))
    metin = "".join(parca)
    c.metin = metin
    for m in TOKEN.finditer(metin):
        if m.group(0) in atla:
            continue
        c.tok.append(m.group(0))
        c.bas.append(m.start())
    c.alan = ["g"] * len(c.tok)
    for a, b, tur, ek in aralik:
        i, j = bisect.bisect_left(c.bas, a), bisect.bisect_left(c.bas, b)
        if tur == "f":
            c.formul.append({"a": i, "b": j, **ek})
        elif tur == "t":
            c.tablo.append((ek["tablo"], i, j))
        for k in range(i, j):
            if tur != "f" or c.alan[k] == "g":
                c.alan[k] = tur
    for konum, tur in isaret:
        (c.fig if tur == FIG else c.okn).append(bisect.bisect_left(c.bas, konum))
    for i, b in enumerate(c.bas):
        if i == 0 or "\n" in metin[c.bas[i - 1]:b]:
            c.paragraf_bas.add(i)
    return c


# --- Hizalama: blok taşıma (tile) + token Levenshtein ---
def tile_bul(G, H, M, g_izin=None, g_dolu=None, h_dolu=None):
    """Greedy String Tiling: en uzundan kısaya örtüşmeyen ortak bloklar. Eşit uzunlukta konumu yakın olan önce."""
    n, m = len(G), len(H)
    g_dolu = g_dolu if g_dolu is not None else [False] * n
    h_dolu = h_dolu if h_dolu is not None else [False] * m
    if n < M or m < M:
        return [], g_dolu, h_dolu
    idx = collections.defaultdict(list)
    for i in range(n - M + 1):
        if g_izin is None or g_izin[i]:
            idx[tuple(G[i:i + M])].append(i)
    kosu = []
    for j in range(m - M + 1):
        for i in idx.get(tuple(H[j:j + M]), ()):
            if i and j and G[i - 1] == H[j - 1]:
                continue
            L = M
            while i + L < n and j + L < m and G[i + L] == H[j + L]:
                L += 1
            kosu.append((-L, abs(i / max(n, 1) - j / max(m, 1)), i, j))
    heapq.heapify(kosu)
    tiles = []
    while kosu:
        L, _, i, j = heapq.heappop(kosu)
        L = -L
        parca, bas = [], None
        for k in range(L + 1):
            bos = k < L and not g_dolu[i + k] and not h_dolu[j + k] and (g_izin is None or g_izin[i + k])
            if bos and bas is None:
                bas = k
            if not bos and bas is not None:
                parca.append((bas, k - bas))
                bas = None
        if parca == [(0, L)]:
            for k in range(L):
                g_dolu[i + k] = h_dolu[j + k] = True
            tiles.append((i, j, L))
        else:
            for b, u in parca:
                if u >= M:
                    heapq.heappush(kosu, (-u, abs((i + b) / max(n, 1) - (j + b) / max(m, 1)), i + b, j + b))
    return tiles, g_dolu, h_dolu


def yeniden_dizim(n_h, tiles):
    """Taşınan blokları doğru metin sırasına koyar; aradaki token'lar önceki bloğa bağlı kalır."""
    sirali = sorted(tiles, key=lambda t: t[1])
    bas, ek = [], {}
    son = 0
    onceki = None
    for t in sirali:
        ara = list(range(son, t[1]))
        if onceki is None:
            bas += ara
        else:
            ek[onceki] = ara
        onceki = t
        son = t[1] + t[2]
    ara = list(range(son, n_h))
    if onceki is None:
        bas += ara
    else:
        ek[onceki] = ara
    y = list(bas)
    for t in sorted(tiles, key=lambda t: t[0]):
        y += list(range(t[1], t[1] + t[2]))
        y += ek.get(t, [])
    return y


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.translate(FOLD)) if not unicodedata.combining(c))


def benzerlik(a, b):
    return 1 - Levenshtein.normalized_distance(a, b)


def kume_es(gs, hs):
    """Hatalı bölgeyi kelime kelime eşler. Hamleler: 1-1, 1-0, 0-1, 1-çok (bölünme), çok-1 (birleşme)."""
    n, m = len(gs), len(hs)
    if n == 0 or m == 0:
        return [([i], []) for i in range(n)] + [([], [j]) for j in range(m)]
    if n * m > 40000:
        k = min(n, m)
        return [([i], [i]) for i in range(k)] + [([i], []) for i in range(k, n)] + [([], [j]) for j in range(k, m)]
    D = np.zeros((n + 1, m + 1))
    Y = {}
    for i in range(n + 1):
        for j in range(m + 1):
            en, yol = -1e9 if (i or j) else 0, None
            aday = []
            if i:
                aday.append((D[i - 1, j], (1, 0)))
            if j:
                aday.append((D[i, j - 1], (0, 1)))
            if i and j:
                s = benzerlik(gs[i - 1], hs[j - 1])
                aday.append((D[i - 1, j - 1] + (s if s >= 0.34 else -0.01), (1, 1)))
                for u in (2, 3):
                    if j >= u:
                        c = "".join(hs[j - u:j]).replace("-", "")
                        s = benzerlik(gs[i - 1].replace("-", ""), c)
                        if s >= 0.75:
                            aday.append((D[i - 1, j - u] + s * 1.01, (1, u)))
                    if i >= u:
                        c = "".join(gs[i - u:i]).replace("-", "")
                        s = benzerlik(c, hs[j - 1].replace("-", ""))
                        if s >= 0.75:
                            aday.append((D[i - u, j - 1] + s * 1.01, (u, 1)))
            for d, h in aday:
                if d > en:
                    en, yol = d, h
            if yol:
                D[i, j], Y[i, j] = en, yol
    y, i, j = [], n, m
    while i or j:
        a, b = Y[i, j]
        y.append((list(range(i - a, i)), list(range(j - b, j))))
        i, j = i - a, j - b
    return y[::-1]


def kelime_mi(t):
    return any(c.isalnum() for c in t) and not YAPI.fullmatch(t)


def hizala(G, H):
    """Döner: durum[i], karsi[i] (H' indeksleri), ek[i] (i'den önce eklenen H indeksleri), tiles."""
    kod = {}
    gi = [kod.setdefault(t, len(kod)) for t in G.tok]
    hi = [kod.setdefault(t, len(kod)) for t in H.tok]
    tiles, gd, hd = tile_bul(gi, hi, 4)
    ozel = [a in ("u", "a") for a in G.alan]
    if any(ozel):
        ek_t, gd, hd = tile_bul(gi, hi, 1, ozel, gd, hd)
        tiles += ek_t
    dizim = yeniden_dizim(len(hi), tiles)
    h2 = [hi[j] for j in dizim]
    durum, karsi = ["silme"] * len(gi), [[] for _ in gi]
    ek = collections.defaultdict(list)
    ops = Levenshtein.opcodes(gi, h2)
    kume = [None, None]

    def kapat(a, b, c, d):
        for gg, hh in kume_es(G.tok[a:b], [H.tok[dizim[x]] for x in range(c, d)]):
            if not gg:
                ek[a + _konum(a, b, c, d, hh[0])].append(dizim[c + hh[0]])
            elif not hh:
                for g in gg:
                    durum[a + g] = "silme"
            elif len(gg) == 1 and len(hh) == 1:
                g, h = G.tok[a + gg[0]], H.tok[dizim[c + hh[0]]]
                karsi[a + gg[0]] = [dizim[c + hh[0]]]
                durum[a + gg[0]] = tur_bul(g, h)
            elif len(gg) == 1:
                karsi[a + gg[0]] = [dizim[c + x] for x in hh]
                durum[a + gg[0]] = "bolunme"
            else:
                karsi[a + gg[0]] = [dizim[c + hh[0]]]
                for g in gg:
                    durum[a + g] = "birlesme"

    def _konum(a, b, c, d, h):
        # eklenen token: oransal yer (küme içi)
        return int(round((b - a) * (h / max(d - c, 1))))
    for op in ops:
        if op.tag == "equal":
            if kume[0] is not None:
                kapat(kume[0], op.src_start, kume[1], op.dest_start)
                kume = [None, None]
            for k in range(op.src_end - op.src_start):
                durum[op.src_start + k] = "dogru"
                karsi[op.src_start + k] = [dizim[op.dest_start + k]]
        elif kume[0] is None:
            kume = [op.src_start, op.dest_start]
    if kume[0] is not None:
        kapat(kume[0], len(gi), kume[1], len(h2))
    return durum, karsi, ek, tiles


def tur_bul(g, h):
    if g == h:
        return "dogru"
    if fold(g) == fold(h):
        return "aksan"
    d = Levenshtein.distance(g, h)
    if d <= 2 and d / max(len(g), len(h)) < 0.5:
        return "harf"
    return "uzak"


# --- Testler: satır sonu, sütun (Vision kutularından, modelden bağımsız) ---
def kutu_oku(yol):
    if not yol or not Path(yol).exists():
        return []
    t = open(yol, encoding="utf-8").read()
    return json.loads(t[t.index("]=") + 2:].rstrip().rstrip(";"))


def satirlar_kur(kutu):
    d = collections.OrderedDict()
    for k in kutu:
        d.setdefault(k[5], []).append(k)
    y = []
    for s in d.values():
        y.append({"k": [x[0] for x in s], "x0": min(x[1] for x in s), "x1": max(x[1] + x[3] for x in s), "y": min(x[2] for x in s)})
    return y


def cift_sutun(satirlar):
    u = [s for s in satirlar if len(s["k"]) >= 3]
    if len(u) < 12:
        return False
    a, b = min(s["x0"] for s in u), max(s["x1"] for s in u)
    o = (a + b) / 2
    sol = [s for s in u if s["x1"] < o + 0.02]
    sag = [s for s in u if s["x0"] > o - 0.02]
    if len(sol) < 5 or len(sag) < 5 or (len(sol) + len(sag)) < 0.65 * len(u):
        return False
    y0, y1 = max(min(s["y"] for s in sol), min(s["y"] for s in sag)), min(max(s["y"] for s in sol), max(s["y"] for s in sag))
    return y1 - y0 > 0.2


def tire_testleri(G, satirlar):
    """Görselde satır sonunda ayrılmış kelimeler. Vision satırı '-' ile bitip sonraki satırın ilk kelimesiyle birleşince doğru metindeki bir tokene denk gelmeli."""
    testler = []
    kelimeler = collections.defaultdict(list)
    for i, t in enumerate(G.tok):
        if kelime_mi(t) and len(t) >= 4 and G.alan[i] != "f":
            kelimeler[fold(t[:2]).lower()].append(i)
    goruldu = set()
    for n, s in enumerate(satirlar):
        son = s["k"][-1]
        if len(son) < 3 or son[-1] not in "-‐–­¬":
            continue
        a = fold(re.sub(r"\W+$", "", son)).lower()
        a = re.sub(r"^\W+", "", a)
        if len(a) < 2:
            continue
        aday = [x["k"][0] for x in satirlar[n + 1:n + 4]] + [x["k"][0] for x in satirlar if x is not s and abs(x["x0"] - s["x0"]) > 0.2]
        for b in aday:
            b = fold(re.sub(r"^\W+|\W+$", "", b)).lower()
            if not b or not b[0].isalpha():
                continue
            hedefler = [i for i in kelimeler.get(a[:2], []) if i not in goruldu and benzerlik(fold(G.tok[i]).lower().replace("-", ""), a + b) >= 0.88]
            if hedefler:
                goruldu.add(hedefler[0])
                testler.append(hedefler[0])
                break
    return testler


def tablo_es(g, h):
    """Satır ve sütun hizalaması sonrası tam eşleşen dolu hücre sayısı (kısmi puan yok)."""
    A, B = g.izgara, h.izgara
    if not A or not B:
        return 0

    def dp(n, m, skor):
        T = np.zeros((n + 1, m + 1))
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                T[i, j] = max(T[i - 1, j], T[i, j - 1], T[i - 1, j - 1] + skor(i - 1, j - 1))
        y, i, j = [], n, m
        while i and j:
            if T[i, j] == T[i - 1, j - 1] + skor(i - 1, j - 1) and skor(i - 1, j - 1) > 0:
                y.append((i - 1, j - 1))
                i, j = i - 1, j - 1
            elif T[i, j] == T[i - 1, j]:
                i -= 1
            else:
                j -= 1
        return y[::-1]
    sa = [collections.Counter(c for c in x if c) for x in A]
    sb = [collections.Counter(c for c in x if c) for x in B]
    sat = dp(len(A), len(B), lambda i, j: sum((sa[i] & sb[j]).values()))
    if not sat:
        return 0
    sut = dp(len(A[0]), len(B[0]), lambda c, d: sum(1 for i, j in sat if A[i][c] and A[i][c] == B[j][d]))
    return sum(1 for i, j in sat for c, d in sut if A[i][c] and A[i][c] == B[j][d])


class Dugum:
    def __init__(self, ic=None, cocuk=()):
        self.ic, self.children = ic, list(cocuk)


class TedsAyar(Config):
    def rename(self, a, b):
        if (a.ic is None) != (b.ic is None):
            return 1.0
        return Levenshtein.normalized_distance(a.ic, b.ic) if a.ic is not None else 0.0

    def children(self, d):
        return d.children


def teds(g, h):
    """Yardımcı metrik (PubTabNet TEDS'in ızgara hâli): yalnız literatürle karşılaştırma için."""
    a = Dugum(None, [Dugum(None, [Dugum(c) for c in x]) for x in g.izgara])
    b = Dugum(None, [Dugum(None, [Dugum(c) for c in x]) for x in h.izgara])
    na = 1 + sum(1 + len(x) for x in g.izgara)
    nb = 1 + sum(1 + len(x) for x in h.izgara)
    return 1 - APTED(a, b, TedsAyar()).compute_edit_distance() / max(na, nb)


def sira_olcu(G, tiles):
    """Doğru sırada kalan gövde kelimesi oranı (ağırlıklı en uzun artan alt dizi). Üst/alt bilgi ve tablo dahil değil."""
    govde = [t for t in tiles if t[2] >= 4]
    agir = []
    for i, j, L in sorted(govde, key=lambda t: t[1]):
        w = sum(1 for k in range(i, i + L) if G.alan[k] in ("g", "f"))
        if w:
            agir.append((i, w))
    toplam = sum(w for _, w in agir)
    if not agir:
        return None, 0
    en = [w for _, w in agir]
    for a in range(len(agir)):
        for b in range(a):
            if agir[b][0] < agir[a][0] and en[b] + agir[a][1] > en[a]:
                en[a] = en[b] + agir[a][1]
    return max(en), toplam


def carpim_nokta(s):
    """a·b ile a.b aynı çarpımdır; 2·5 ile 2.5 aynı değildir."""
    return re.sub(r"(?<!\d)·|·(?!\d)", ".", s)


def felaket_bul(G, H, durum, bitis):
    if not H.tok:
        return "bos"
    if bitis in ("length", "max_tokens"):
        return "kesildi"
    # Tekrar döngüsü: 8'li dizi 4'ten fazla, doğru metinden çok geçiyor ve fazlalık sayfayı şişiriyor
    if len(H.tok) - len(G.tok) >= max(40, 0.2 * len(G.tok)):
        say = collections.Counter(tuple(H.tok[i:i + 8]) for i in range(len(H.tok) - 7))
        say_g = collections.Counter(tuple(G.tok[i:i + 8]) for i in range(len(G.tok) - 7))
        for g, n in say.items():
            if n > 4 and n > say_g[g] and sum(kelime_mi(t) for t in g) >= 2:
                return "tekrar"
    k = [i for i, t in enumerate(G.tok) if kelime_mi(t)]
    if len(k) >= 20 and sum(durum[i] == "dogru" for i in k) / len(k) < 0.05:
        return "ilgisiz"
    return ""


def kritik_mi(G, i):
    t = G.tok[i]
    if G.alan[i] == "f":
        return False
    if any(c.isdigit() for c in t) or t in KRITIK_ISARET:
        return True
    if len(t) >= 2 and t[0].isupper() and any(c.islower() for c in t) and i not in G.paragraf_bas and G.tok[i - 1] not in (".", "!", "?", ":", ";", '"', "'", "(", "-"):
        return True
    return False


def kucuk_tasima(G, H, durum, karsi, ek):
    """Kalan silinen/uzak kelime ile kalan eklenen birebir aynıysa kelime doğrudur, yalnız yeri farklıdır (fiş, form, tablo okuma yönü).
    Kelime cezası yok; sıra ekseninde sayılır. Harf farkı olan kelime buraya giremez."""
    havuz = collections.defaultdict(list)
    for k, js in ek.items():
        for j in js:
            havuz[H.tok[j]].append(("ek", k, j))
    for i, d in enumerate(durum):
        if d == "uzak" and len(karsi[i]) == 1:
            havuz[H.tok[karsi[i][0]]].append(("uz", i, karsi[i][0]))
    n = 0
    for i, d in enumerate(durum):
        # X, işaretli kutudur: başka etiketin yanına geçmesi okuma hatasıdır
        if d not in ("silme", "uzak") or G.alan[i] == "f" or G.tok[i] == "X" or not havuz.get(G.tok[i]):
            continue
        tur, k, j = havuz[G.tok[i]].pop()
        if tur == "ek":
            ek[k].remove(j)
        else:
            karsi[k], durum[k] = [], "silme"
        if d == "uzak":
            # eski eşi eklenen token olur
            eski = karsi[i][0]
            ek[i].append(eski)
            havuz[H.tok[eski]].append(("ek", i, eski))
        karsi[i], durum[i] = [j], "dogru"
        n += 1
    return n


UST_ALT_PUANLA = True  # False: doğru metindeki üst/alt bilgi ana puana girmez (OmniDocBench gibi), ayrı tanı ekseni olarak raporlanır


def sayfa_degerlendir(gt_md, hyp_md, kutu=None, bitis=None, kategori=""):
    atla = NOKTA_DISI.get(kategori, frozenset())
    G, H = coz(gt_md, atla), coz(hyp_md, atla)
    r = {"kategori": kategori}
    durum, karsi, ek, tiles = hizala(G, H)
    # Formül: yalnız tam eşleşme (çizim aynıysa token farkı önemsiz). Tek tokenlik satır içi ($x$) kelime gibi sayılır.
    f_ok, f_cdm, f_blok, f_blok_ok, f_say = 0, [], 0, 0, 0
    for f in G.formul:
        g = "".join(G.tok[f["a"]:f["b"]])
        h = ""
        for i in range(f["a"], f["b"]):
            if i > f["a"]:
                h += "".join(H.tok[j] for j in ek.get(i, []))
            h += "".join(H.tok[j] for j in karsi[i])
        g, h = carpim_nokta(g), carpim_nokta(h)
        ok = g == h and bool(g)
        if ok:
            for i in range(f["a"], f["b"]):
                durum[i] = "dogru"
                if i > f["a"]:
                    ek.pop(i, None)
        if f["blok"] or f["b"] - f["a"] >= 3:
            f_say += 1
            f_ok += ok
            f_blok += f["blok"]
            f_blok_ok += ok and f["blok"]
            f_cdm.append(1 - Levenshtein.normalized_distance(g, h) if g or h else 1.0)
    r.update(formul_g=f_say, formul_c=f_ok, formul_blok_g=f_blok, formul_blok_c=f_blok_ok,
             formul=f_ok / f_say if f_say else np.nan, formul_cdm=float(np.mean(f_cdm)) if f_cdm else np.nan)
    tasinan = kucuk_tasima(G, H, durum, karsi, ek)
    r["kucuk_tasima"] = tasinan
    # İşaretli kutu sonraki etikete aittir: etiket farklıysa yanlış kutu işaretlenmiştir
    for i, t in enumerate(G.tok[:-1]):
        if t == "X" and G.tok[i + 1][0].isalpha() and durum[i] == "dogru" and karsi[i]:
            j = karsi[i][0] + 1
            if j >= len(H.tok) or benzerlik(G.tok[i + 1], H.tok[j]) < 0.7:
                durum[i] = "harf"

    ua = [i for i, a in enumerate(G.alan) if a in ("u", "a")]
    ua_kel = [i for i in ua if kelime_mi(G.tok[i])]
    r.update(ust_alt_g=len(ua_kel), ust_alt_c=sum(durum[i] == "dogru" for i in ua_kel))
    disari = set() if UST_ALT_PUANLA else set(ua)
    g_kel = [i for i, t in enumerate(G.tok) if kelime_mi(t) and G.alan[i] != "f" and i not in disari]
    n_harf = collections.Counter(durum[i] for i in g_kel)

    # Hyp'te kalan ekler: görsel içi yazı ve okunaksız bölgesi puanlanmaz
    muaf_aralik = []
    bloklar = sorted(G.paragraf_bas) + [len(G.tok)]
    for p in G.fig:
        k = bisect.bisect_right(bloklar, p)
        a = bloklar[k - 2] if k >= 2 else 0
        b = bloklar[k] if k < len(bloklar) else len(G.tok)
        # altyazı şartı: komşu paragraf kısaysa pencere ona genişler
        a2 = a if p - a <= 40 else p
        b2 = b if b - p <= 40 else p
        muaf_aralik.append((a2, b2))
    for p in G.okn:
        muaf_aralik.append((p, p))
    if not UST_ALT_PUANLA:
        # üst/alt bilgi bölgesine yazılan ekler de puanlanmaz
        for i in ua:
            muaf_aralik.append((i, i + 1))
    vision = {fold(k[0]).lower().strip(".,;:()\"'") for k in (kutu or [])}
    gold_k = {fold(t).lower() for t in G.tok}
    v_ek = vision - gold_k
    say_ek = collections.Counter()
    hata_ek = []  # (konum, token)
    for konum, jler in ek.items():
        muaf_poz = any(a <= konum <= b for a, b in muaf_aralik)
        for j in jler:
            t = H.tok[j]
            tur = "kelime" if kelime_mi(t) else "isaret"
            if muaf_poz or (tur == "kelime" and fold(t).lower() in v_ek):
                say_ek["muaf_" + tur] += 1
                continue
            say_ek[tur] += 1
            hata_ek.append((konum, t))
    C = n_harf["dogru"]
    S = sum(n_harf[x] for x in ("aksan", "harf", "uzak", "bolunme", "birlesme"))
    D = n_harf["silme"]
    I = say_ek["kelime"]
    r.update(kelime_g=len(g_kel), kelime_c=C, kelime_harf=n_harf["harf"], kelime_aksan=n_harf["aksan"], kelime_uzak=n_harf["uzak"],
             kelime_silme=D, kelime_bolunme=n_harf["bolunme"], kelime_birlesme=n_harf["birlesme"], kelime_ekleme=I, muaf_kelime=say_ek["muaf_kelime"])
    r["kelime"] = C / max(C + S + D + I, 1)
    h_kel = sum(1 for t in H.tok if kelime_mi(t)) - say_ek["muaf_kelime"]
    r["sallama"] = (n_harf["uzak"] + I) / max(h_kel, 1) if H.tok else 1.0

    # Kritik: sayı, karşılaştırma işareti, özel ad
    kr = [i for i in range(len(G.tok)) if kritik_mi(G, i) and i not in disari]
    kr_ok = sum(durum[i] == "dogru" for i in kr)
    kr_ek = sum(1 for js in ek.values() for j in js if any(c.isdigit() for c in H.tok[j]) or H.tok[j] in KRITIK_ISARET)
    r.update(kritik_g=len(kr), kritik_c=kr_ok, kritik_ek=kr_ek, kritik=kr_ok / max(len(kr) + kr_ek, 1) if kr or kr_ek else np.nan)
    tr = [i for i in g_kel if set(G.tok[i]) & TURKCE]
    r.update(turkce_g=len(tr), turkce_c=sum(durum[i] == "dogru" for i in tr))
    isr = [i for i, t in enumerate(G.tok) if not kelime_mi(t) and G.alan[i] != "f" and i not in disari]
    r.update(isaret_g=len(isr), isaret_c=sum(durum[i] == "dogru" for i in isr))

    # Tablo: tam doğru hücre ve tam doğru tablo
    gt_tab = [t for t, _, _ in G.tablo if t.izgara]
    hy_tab = [t for t, _, _ in H.tablo if t.izgara]
    r.update(tablo_g=len(gt_tab), tablo_h=len(hy_tab))
    if gt_tab:
        es = np.zeros((len(gt_tab), max(len(hy_tab), 1)))
        for a, g in enumerate(gt_tab):
            for b, h in enumerate(hy_tab):
                es[a, b] = tablo_es(g, h)
        h_sat, h_sut = linear_sum_assignment(-es)
        ok_h = int(sum(es[a, b] for a, b in zip(h_sat, h_sut)))
        ng = sum(t.hucre for t in gt_tab)
        kullanilan = [hy_tab[b] for a, b in zip(h_sat, h_sut) if hy_tab and es[a, b] > 0]
        nh = sum(t.hucre for t in kullanilan)
        tam = 0
        for a, b in zip(h_sat, h_sut):
            if hy_tab and gt_tab[a].izgara == hy_tab[b].izgara:
                tam += 1
        r.update(hucre_g=ng, hucre_c=ok_h, hucre_h=nh, tablo_tam=tam, tablo=ok_h / max(ng, nh, 1), tablo_tam_oran=tam / len(gt_tab))
        t_vals = []
        for a, g in enumerate(gt_tab):
            k = list(h_sat).index(a) if a in h_sat else None
            if k is not None and hy_tab and es[a, h_sut[k]] > 0:
                t_vals.append(teds(g, hy_tab[h_sut[k]]))
            else:
                t_vals.append(0.0)
        r["teds"] = float(np.mean(t_vals))
    else:
        r.update(hucre_g=0, hucre_c=0, hucre_h=0, tablo_tam=0, tablo=np.nan, tablo_tam_oran=np.nan, teds=np.nan)
    r["tablo_uydurma"] = float(bool(hy_tab)) if not gt_tab and kategori != "fis_fatura_form" else np.nan

    # Satır sonu tiresi
    sat = satirlar_kur(kutu or [])
    testler = tire_testleri(G, sat) if sat else []
    t_ok = 0
    for i in testler:
        hs = [H.tok[j] for j in karsi[i]]
        if durum[i] in TIRE_KALDI or not hs:
            continue
        if len(hs) == 1 and ("-" in hs[0]) == ("-" in G.tok[i]):
            t_ok += 1
    r.update(tire_g=len(testler), tire_c=t_ok, tire=t_ok / len(testler) if testler else np.nan)

    # Okuma sırası ve sütun
    d, top = sira_olcu(G, tiles)
    g_gov = sum(1 for a in G.alan if a in ("g", "f"))
    if g_gov >= 20:
        r["sira"] = (d or 0) / max(top + tasinan, 0.5 * g_gov)
        r["sira_tam"] = float((d or 0) == top and top >= 0.5 * g_gov)
    else:
        r["sira"], r["sira_tam"] = np.nan, np.nan
    r["cift_sutun"] = float(cift_sutun(sat))

    # Felaket: sayfa sıfır alır
    f = felaket_bul(G, H, durum, bitis)
    r["felaket"] = f
    hata_var = any(durum[i] != "dogru" for i in range(len(G.tok)) if i not in disari) or say_ek["kelime"] or say_ek["isaret"]
    tablo_tam_hepsi = not gt_tab or r["tablo_tam"] == len(gt_tab)
    r["hatasiz"] = float(not hata_var and tablo_tam_hepsi and (np.isnan(r["sira_tam"]) or r["sira_tam"] == 1.0))
    r["duzen"] = np.nanmean([r["sira"], r["tire"]]) if not (np.isnan(r["sira"]) and np.isnan(r["tire"])) else np.nan
    # Yardımcı (literatür): normalize düzenleme mesafesi
    r["ned"] = Levenshtein.normalized_distance(" ".join(G.tok), " ".join(H.tok))
    if f:
        for k in ("kelime", "formul", "tablo", "tablo_tam_oran", "tire", "sira", "sira_tam", "kritik", "hatasiz", "duzen"):
            if not np.isnan(r.get(k, np.nan)):
                r[k] = 0.0
        r["sallama"] = 1.0
    gecti(r)
    r["_hatalar"] = hata_listesi(G, H, durum, karsi, hata_ek, sinir=None)
    return r


def gecti(r):
    """Ana puan: her eksen sayfada ya tam geçer (1) ya kalır (0). Tek harf hatası o sayfanın kelime eksenini düşürür; felaket her ekseni düşürür."""
    f = bool(r["felaket"])
    g = {"g_kelime": r["kelime_c"] == r["kelime_g"] and r["kelime_ekleme"] == 0,
         "g_sallamama": r["kelime_uzak"] == 0 and r["kelime_ekleme"] == 0,
         "g_kritik": r["kritik_c"] == r["kritik_g"] and r["kritik_ek"] == 0 if (r["kritik_g"] or r["kritik_ek"]) else None,
         "g_formul": r["formul_c"] == r["formul_g"] if r["formul_g"] else None,
         "g_tablo": r["tablo_tam"] == r["tablo_g"] if r["tablo_g"] else None}
    dz = [r["tire_c"] == r["tire_g"]] if r["tire_g"] else []
    if not np.isnan(r["sira_tam"]) and r["kategori"] not in SIRA_DISI:
        dz.append(r["sira_tam"] == 1)
    g["g_duzen"] = all(dz) if dz else None
    for k, v in g.items():
        r[k] = np.nan if v is None else float(v and not f)


def hata_listesi(G, H, durum, karsi, ekler, sinir=400):
    y = []
    for i, d in enumerate(durum):
        if d != "dogru":
            y.append([d, G.tok[i], " ".join(H.tok[j] for j in karsi[i]), G.alan[i], i])
    y += [["ekleme", "", t, "", k] for k, t in ekler]
    return y[:sinir] if sinir else y


# --- Toplama ---
TEMEL_AD = {"muse": "Muse", "gemma": "Gemma", "qwen38": "Qwen", "deepseek": "DeepSeek"}  # dogru metnin temel metnini veren modeller
EKSEN = ("kelime", "sallamama", "kritik", "formul", "tablo", "duzen")
NOKTA_DISI = {"fis_fatura_form": frozenset(".·:")}  # düşük çözünürlüklü fiş ve formda tek başına nokta okunamaz; sayı içindeki nokta sayılır
SIRA_DISI = {"slayt", "el_yazisi", "fis_fatura_form"}  # düzenin tek doğrusu yok: sıra sıralamaya girmez, rapora girer


def eksenler(s, agirlik=None):
    """s: sayfa alanları sözlüğü (numpy), agirlik: sayfa ağırlığı (bootstrap). Kategori makro ortalaması."""
    w = np.ones(len(s["kat"])) if agirlik is None else agirlik

    def ort(x, m=None):
        a = np.where(np.isnan(x), 0, 1) * (w if m is None else w * m)
        return np.nan if a.sum() == 0 else np.nansum(x * a) / a.sum()

    def makro(x):
        d = [ort(x, s["kat"] == k) for k in s["kat_ad"]]
        d = [v for v in d if not np.isnan(v)]
        return float(np.mean(d)) if d else np.nan
    return {"kelime": makro(s["g_kelime"]), "sallamama": makro(s["g_sallamama"]), "kritik": makro(s["g_kritik"]),
            "formul": ort(s["g_formul"]), "tablo": ort(s["g_tablo"]), "duzen": ort(s["g_duzen"])}


def token_eksen(s):
    """Tanı için token düzeyinde oranlar (eski ana puan): sıralamaya girmez."""
    w = np.ones(len(s["kat"]))

    def ort(x, m=None):
        a = np.where(np.isnan(x), 0, 1) * (w if m is None else w * m)
        return np.nan if a.sum() == 0 else np.nansum(x * a) / a.sum()

    def makro(x):
        d = [v for v in (ort(x, s["kat"] == k) for k in s["kat_ad"]) if not np.isnan(v)]
        return float(np.mean(d)) if d else np.nan
    return {"kelime": makro(s["kelime"]), "sallamama": makro(1 - s["sallama"]), "kritik": makro(s["kritik"]),
            "formul": ort(s["formul"]), "tablo": ort(s["tablo"]), "duzen": ort(s["duzen_skor"])}


def skor(e, agirlik=None):
    v = np.array([e[k] for k in EKSEN], dtype=float)
    w = np.ones(len(EKSEN)) if agirlik is None else agirlik
    a = ~np.isnan(v)
    return 100 * float((v[a] * w[a]).sum() / w[a].sum())


def dizi(satirlar, kat_ad):
    s = {k: np.array([float(x.get(k, np.nan)) for x in satirlar]) for k in ("kelime", "sallama", "kritik", "formul", "tablo", "sira", "tire", "duzen", "hatasiz",
                                                                          "g_kelime", "g_sallamama", "g_kritik", "g_formul", "g_tablo", "g_duzen")}
    s["kat"] = np.array([x["kategori"] for x in satirlar])
    s["belge"] = np.array([x["belge"] for x in satirlar])
    s["kat_ad"] = kat_ad
    sira = np.array([np.nan if x["kategori"] in SIRA_DISI else x.get("sira", np.nan) for x in satirlar], dtype=float)
    s["duzen_skor"] = np.array([np.nan if np.isnan(a) and np.isnan(b) else np.nanmean([a, b]) for a, b in zip(sira, s["tire"])])
    return s


def bootstrap(s, n=2000, tohum=0):
    """Belge düzeyi: aynı belgenin sayfaları birlikte örneklenir."""
    rng = np.random.default_rng(tohum)
    b, ters = np.unique(s["belge"], return_inverse=True)
    y = []
    for _ in range(n):
        say = np.bincount(rng.integers(0, len(b), len(b)), minlength=len(b)).astype(float)
        y.append(skor(eksenler(s, say[ters])))
    return float(np.percentile(y, 2.5)), float(np.percentile(y, 97.5))


def alt_kume(s, m):
    d = {k: (v[m] if isinstance(v, np.ndarray) else v) for k, v in s.items()}
    d["kat_ad"] = [k for k in s["kat_ad"] if (s["kat"][m] == k).any()]
    return d


def duyarlilik(tablolar, n=2000, tohum=0):
    """Rastgele eksen ağırlıklarında kim birinci, bir eksen atılınca sıra nasıl değişiyor."""
    rng = np.random.default_rng(tohum)
    ad = list(tablolar)
    birinci = collections.Counter()
    for w in rng.dirichlet(np.ones(len(EKSEN)), n):
        d = [skor(tablolar[m], w) for m in ad]
        birinci[ad[int(np.argmax(d))]] += 1
    atla = {}
    for k in EKSEN:
        w = np.array([0.0 if x == k else 1.0 for x in EKSEN])
        atla[k] = [m for _, m in sorted(((-skor(tablolar[m], w), m) for m in ad))]
    return {"birinci_orani": {m: birinci[m] / n for m in ad}, "eksen_atilinca_sira": atla}


# --- Ana akış ---
def _pool_baslat(dosya, ust_alt=True):
    global UST_ALT_PUANLA
    UST_ALT_PUANLA = ust_alt
    KANON.update(json.load(open(dosya, encoding="utf-8")))


def _is(a):
    i, kat, belge, gt, hyp, kutu_y, bitis, temel = a
    r = sayfa_degerlendir(gt, hyp, kutu_oku(kutu_y), bitis, kat)
    r.update(id=i, belge=belge, temel=temel, cikti_yok=hyp == "")
    return r


def sayfalar(gt_kok, secim, cikarilan):
    cik = {json.loads(s)["id"] for s in open(cikarilan, encoding="utf-8")}
    y = []
    for s in open(secim, encoding="utf-8"):
        e = json.loads(s)
        if e["id"] in cik:
            continue
        p = Path(gt_kok) / e["kategori"] / f"{e['id']}.md"
        if p.exists():
            y.append((e["id"], e["kategori"], e.get("belge", e["id"]), p.read_text(encoding="utf-8")))
    return y


def cikti_oku(klasor, kat, i):
    for p in (Path(klasor) / kat / f"{i}.md", Path(klasor) / f"{i}.md", Path(klasor) / kat / i / f"{i}.md"):
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore")
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modeller", nargs="*", help="ad=klasor")
    ap.add_argument("--cikti", required=True)
    ap.add_argument("--gt", default=f"{V0}/veri/dogru_metin")
    ap.add_argument("--secim", default=f"{V0}/veri/sayfalar.jsonl")
    ap.add_argument("--cikarilan", default=f"{V0}/cikarilan.jsonl")
    ap.add_argument("--kutu", default=f"{V0}/veri/kutu")
    ap.add_argument("--kart", default=f"{V0}/hakem/kart", help="temel metni seçilen modeli bulmak için")
    ap.add_argument("--altin", help="elle doğrulanmış sayfa kimlikleri (satır başına bir)")
    ap.add_argument("--gt-kendisi", action="store_true", help="doğru metni model gibi değerlendirir (her şey 100 olmalı)")
    ap.add_argument("--ust-alt-haric", action="store_true", help="doğru metindeki üst/alt bilgi ana puana girmez, ayrı raporlanır")
    ap.add_argument("--n", type=int, default=max((os.cpu_count() or 4) - 2, 1))
    a = ap.parse_args()
    cikti = Path(a.cikti)
    cikti.mkdir(parents=True, exist_ok=True)
    sf = sayfalar(a.gt, a.secim, a.cikarilan)
    kat_ad = sorted({x[1] for x in sf})
    modeller = dict(m.split("=", 1) for m in a.modeller)
    if a.gt_kendisi:
        modeller["DOGRU_METIN"] = a.gt

    temel = {}
    for i, *_ in sf:
        p = Path(a.kart) / f"{i}.json"
        if p.exists():
            temel[i] = json.load(open(p, encoding="utf-8")).get("temel", "")

    texler = set()
    for i, k, b, g in sf:
        texler.update(formul_listesi(g))
        for kl in modeller.values():
            texler.update(formul_listesi(cikti_oku(kl, k, i)))
    onbellek = cikti / "katex_onbellek.json"
    yeni = kanon_doldur(sorted(texler), onbellek)
    if not onbellek.exists():
        json.dump(KANON, open(onbellek, "w", encoding="utf-8"), ensure_ascii=False)
    gt_hata = sorted({s for i, k, b, g in sf for t in formul_listesi(g) for s in tex_on_isle(t)[0] if KANON.get(s, "").startswith(BOZUK)})
    print(f"{len(texler)} formül, {len(yeni)} yeni render; doğru metinde render edilemeyen: {len(gt_hata)}", flush=True)
    (cikti / "gt_render_hatasi.txt").write_text("\n".join(gt_hata), encoding="utf-8")

    ozet, kart, kat_ozet = {}, {}, {}
    tum = {}
    with cf.ProcessPoolExecutor(a.n, initializer=_pool_baslat, initargs=(str(onbellek), not a.ust_alt_haric)) as ex:
        for ad, kl in modeller.items():
            bitis = {}
            kp = Path(kl) / "kayit.jsonl"
            if kp.exists():
                for s in open(kp, encoding="utf-8"):
                    try:
                        e = json.loads(s)
                    except ValueError:
                        continue
                    bitis[e.get("id")] = e.get("bitis")
            isler = [(i, k, b, g, cikti_oku(kl, k, i), f"{a.kutu}/{i}.js", bitis.get(i), temel.get(i, "")) for i, k, b, g in sf]
            satirlar = list(ex.map(_is, isler, chunksize=8))
            tum[ad] = satirlar
            with open(cikti / f"{ad}_hata.jsonl", "w", encoding="utf-8") as f:
                for r in satirlar:
                    f.write(json.dumps({"id": r["id"], "kategori": r["kategori"], "hatalar": r.pop("_hatalar")}, ensure_ascii=False) + "\n")
            with open(cikti / f"{ad}_sayfa.jsonl", "w", encoding="utf-8") as f:
                for r in satirlar:
                    f.write(json.dumps(r, ensure_ascii=False, default=float) + "\n")
            s = dizi(satirlar, kat_ad)
            e = eksenler(s)
            ga = bootstrap(s)
            kart[ad] = e
            top = lambda k: sum(r.get(k, 0) for r in satirlar)
            ora = lambda a_, b_: top(a_) / max(top(b_), 1)
            cs = [r for r in satirlar if r["cift_sutun"] == 1 and r["kategori"] not in SIRA_DISI]
            o = {"oku_skor": skor(e), "ga95": ga, **e, "token": token_eksen(s), "token_skor": skor(token_eksen(s)),
                 "hatasiz_sayfa": float(np.nanmean(s["hatasiz"])),
                 "felaket_orani": float(np.mean([bool(r["felaket"]) for r in satirlar])), "felaket": dict(collections.Counter(r["felaket"] for r in satirlar if r["felaket"])),
                 "kelime_mikro": ora("kelime_c", "kelime_g"),
                 "harf_hatasi": top("kelime_harf"), "aksan_hatasi": top("kelime_aksan"), "uzak_ikame": top("kelime_uzak"), "silinen": top("kelime_silme"),
                 "bolunen": top("kelime_bolunme"), "birlesen": top("kelime_birlesme"), "eklenen": top("kelime_ekleme"), "muaf_gorsel_yazi": top("muaf_kelime"),
                 "turkce_kelime": ora("turkce_c", "turkce_g"), "ust_alt_kelime": ora("ust_alt_c", "ust_alt_g"), "isaret": ora("isaret_c", "isaret_g"),
                 "formul_tam": ora("formul_c", "formul_g"), "formul_n": top("formul_g"), "formul_blok_tam": ora("formul_blok_c", "formul_blok_g"),
                 "hucre_tam": ora("hucre_c", "hucre_g"), "tablo_tam": ora("tablo_tam", "tablo_g"), "tablo_n": top("tablo_g"),
                 "tire": ora("tire_c", "tire_g"), "tire_n": top("tire_g"),
                 "sira": float(np.nanmean(s["sira"])), "cift_sutun_n": len(cs), "cift_sutun_sira": float(np.nanmean([r["sira"] for r in cs])) if cs else np.nan,
                 "cift_sutun_temiz": float(np.nanmean([r["sira_tam"] for r in cs])) if cs else np.nan,
                 "yardimci_ned": float(np.mean([r["ned"] for r in satirlar])), "yardimci_teds": float(np.nanmean([r["teds"] for r in satirlar])),
                 "yardimci_cdm": float(np.nanmean([r["formul_cdm"] for r in satirlar]))}
            ozet[ad] = o
            kat_ozet[ad] = {k: {"kelime": float(np.nanmean([r["kelime"] for r in satirlar if r["kategori"] == k])),
                                "hatasiz": float(np.nanmean([r["hatasiz"] for r in satirlar if r["kategori"] == k])),
                                "sallama": float(np.nanmean([r["sallama"] for r in satirlar if r["kategori"] == k]))} for k in kat_ad}
            # İz ayrımı: bu modelin temel seçilmediği sayfalar, sentetik orijinal etiketli sayfalar, altın alt küme
            m_tem = np.array([r["temel"] != TEMEL_AD.get(ad) for r in satirlar])
            o["iz_temel_degil"] = skor(eksenler(alt_kume(s, m_tem)))
            o["iz_sentetik"] = skor(eksenler(alt_kume(s, s["kat"] == "fis_fatura_form")))
            if a.altin:
                al = set(open(a.altin, encoding="utf-8").read().split())
                o["iz_altin"] = skor(eksenler(alt_kume(s, np.array([r["id"] in al for r in satirlar]))))
            print(ad, round(o["oku_skor"], 2), flush=True)
    if len([m for m in kart if m != "DOGRU_METIN"]) > 1:
        ozet["_duyarlilik"] = duyarlilik({m: v for m, v in kart.items() if m != "DOGRU_METIN"})
    # Doğru metin denetimi: tüm modellerin birbiriyle aynı, doğru metinle farklı okuduğu yerler
    json.dump({"ozet": ozet, "kategori": kat_ozet}, open(cikti / "ozet.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
    rapor(ozet, kat_ozet, kat_ad, cikti)
    denetim(tum, cikti)


def denetim(tum, cikti):
    ad = [m for m in tum if m != "DOGRU_METIN"]
    if len(ad) < 2:
        return
    y = []
    hatalar = {m: {json.loads(s)["id"]: json.loads(s)["hatalar"] for s in open(cikti / f"{m}_hata.jsonl", encoding="utf-8")} for m in ad}
    for i in hatalar[ad[0]]:
        kes = None
        for m in ad:
            c = {(d[4], d[1], d[2]) for d in hatalar[m].get(i, [])}
            kes = c if kes is None else kes & c
        for k, g, h in sorted(kes or []):
            y.append({"id": i, "konum": k, "dogru_metin": YAPI.sub("~", g), "tum_modeller": YAPI.sub("~", h)})
    with open(cikti / "denetim.jsonl", "w", encoding="utf-8") as f:
        for x in y:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"Doğru metin denetimi: {len(y)} yerde tüm modeller aynı okuyup doğru metinden ayrılıyor ({cikti / 'denetim.jsonl'})")


def rapor(ozet, kat, kat_ad, cikti):
    ad = sorted((m for m in ozet if not m.startswith("_")), key=lambda m: -ozet[m]["oku_skor"])
    y = ["# OKU-Bench sonuçları", "", "Eksenler sayfa düzeyindedir: sayfa o eksende hiç hata yapmadıysa geçer. OKU-Skor altı eksenin ortalamasıdır.", "",
         "| Model | OKU-Skor | %95 GA | Kelime | Sallamama | Kritik | Formül | Tablo | Düzen | Hatasız sayfa | Felaket |", "|" + "---|" * 11]
    p = lambda v: "-" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{100 * v:.1f}"
    for m in ad:
        o = ozet[m]
        y.append(f"| {m} | {o['oku_skor']:.1f} | {o['ga95'][0]:.1f}-{o['ga95'][1]:.1f} | {p(o['kelime'])} | {p(o['sallamama'])} | {p(o['kritik'])} | {p(o['formul'])} | {p(o['tablo'])} | {p(o['duzen'])} | {p(o['hatasiz_sayfa'])} | {p(o['felaket_orani'])} |")
    y += ["", "Üst/alt bilgi kelimelerinin doğru okunma oranı (tanı): " + ", ".join(f"{m} {p(ozet[m]['ust_alt_kelime'])}" for m in ad)]
    y += ["", "## Token düzeyinde doğruluk (tanı, sıralamaya girmez)", "", "| Model | Ortalama | Kelime | Sallamama | Kritik | Formül | Tablo | Düzen |", "|" + "---|" * 8]
    for m in ad:
        t = ozet[m]["token"]
        y.append(f"| {m} | {ozet[m]['token_skor']:.1f} | " + " | ".join(p(t[k]) for k in EKSEN) + " |")
    y += ["", "## Ham sayılar", "", "| Model | Harf hatası | Aksan | Uzak ikame | Silinen | Bölünen | Birleşen | Eklenen | Muaf (görsel yazı) | Formül tam | Tablo tam | Hücre tam | Tire | Çift sütun temiz (n) | Sıra |", "|" + "---|" * 15]
    for m in ad:
        o = ozet[m]
        y.append(f"| {m} | {o['harf_hatasi']} | {o['aksan_hatasi']} | {o['uzak_ikame']} | {o['silinen']} | {o['bolunen']} | {o['birlesen']} | {o['eklenen']} | {o['muaf_gorsel_yazi']} | {p(o['formul_tam'])} ({o['formul_n']}) | {p(o['tablo_tam'])} ({o['tablo_n']}) | {p(o['hucre_tam'])} | {p(o['tire'])} ({o['tire_n']}) | {p(o['cift_sutun_temiz'])} ({o['cift_sutun_n']}) | {p(o['sira'])} |")
    y += ["", "## Kategori: tam doğru kelime / hatasız sayfa", "", "| Model | " + " | ".join(kat_ad) + " |", "|" + "---|" * (len(kat_ad) + 1)]
    for m in ad:
        y.append(f"| {m} | " + " | ".join(f"{p(kat[m][k]['kelime'])} / {p(kat[m][k]['hatasiz'])}" for k in kat_ad) + " |")
    y += ["", "## İz ayrımı ve yardımcılar", "", "| Model | Temel seçilmediği sayfalar | Sentetik etiketli sayfalar | NED | TEDS | CDM |", "|" + "---|" * 6]
    for m in ad:
        o = ozet[m]
        y.append(f"| {m} | {o['iz_temel_degil']:.1f} | {o['iz_sentetik']:.1f} | {o['yardimci_ned']:.3f} | {o['yardimci_teds']:.3f} | {o['yardimci_cdm']:.3f} |")
    if "iz_altin" in ozet[ad[0]]:
        y += ["", "Elle doğrulanmış alt küme: " + ", ".join(f"{m} {ozet[m]['iz_altin']:.1f}" for m in ad)]
    if "_duyarlilik" in ozet:
        d = ozet["_duyarlilik"]
        y += ["", "## Duyarlılık", "", "Rastgele eksen ağırlıklarında birinci olma oranı: " + ", ".join(f"{m} %{100 * v:.0f}" for m, v in d["birinci_orani"].items()), ""]
        for k, v in d["eksen_atilinca_sira"].items():
            y.append(f"- {k} atılınca: " + " > ".join(v))
    (cikti / "rapor.md").write_text("\n".join(y) + "\n", encoding="utf-8")
    print("\n".join(y))


if __name__ == "__main__":
    main()

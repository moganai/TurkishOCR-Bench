"""TurkishOCR-Bench sonuç sitesi: oku_puanla.py çıktısından (ozet.json, <model>_sayfa.jsonl) ve testlerden tek dosyalık HTML üretir.
Bütün sayılar gömülüdür; sayfa çevrimdışı açılır.

Kullanım: python site_uret.py --sonuc <sonuc_klasoru> --testler <testler_klasoru> --cikti <dosya.html>
"""
import argparse
import collections
import json
import time
from pathlib import Path

AD = {"Muse": "Muse Spark 1.3", "Gemma": "Gemma-4-31B", "Qwen3.8": "Qwen3.8-flash-next", "DeepSeek": "DeepSeek-v4.1-flash",
      "mimo": "MiMo-v2.6-pro", "qwen3.5-9b": "Qwen3.5-9B", "dots-ocr": "dots.ocr", "moganocr-tr": "MoganOCR-TR (2B)", "ongun-ocr": "OngunOCR",
      "qwen3-vl-30b": "Qwen3-VL-30B", "deepseek-ocr-2": "DeepSeek-OCR-2", "qwen3.5-2b": "Qwen3.5-2B", "nemotron-3.5": "Nemotron 3.5 Super VL", "minimax-m3.1": "MiniMax M3.1 Flash", "paddleocr-vl-1.6": "PaddleOCR-VL-1.6", "glm-ocr": "GLM-OCR", "indra-ocr": "Indra OCR", "gpt-6.1-sol": "GPT-6.1 Sol", "mistral-large-4": "Mistral Large 4"}
KAT = {"akademik": "Akademik", "el_yazisi": "El yazısı", "fis_fatura_form": "Fiş / fatura / form", "formul": "Formül", "kitap": "Kitap",
       "resmi_eski": "Resmî eski", "resmi_yeni": "Resmî yeni", "slayt": "Slayt", "tablo": "Tablo", "taranmis": "Taranmış"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sonuc", required=True)
    ap.add_argument("--testler", required=True)
    ap.add_argument("--cikti", required=True)
    ap.add_argument("--yerel", action="store_true", help="doctype + utf-8 başlığı ekle (yerel sunucu için)")
    ap.add_argument("--sablon", default=str(Path(__file__).with_name("site_sablon.html")))
    a = ap.parse_args()
    S, T = Path(a.sonuc), Path(a.testler)
    ozet = json.load(open(S / "ozet.json", encoding="utf-8"))
    meta = [json.loads(s) for s in open(T / "sayfalar.jsonl", encoding="utf-8")]
    test_say = json.load(open(T / "test_sayilari.json", encoding="utf-8"))
    sayfalar = {m["sayfa"]: {"k": m["kategori"], "b": m["belge"], "t": m["temel"], "h": {}} for m in meta}
    for m in ozet:
        p = S / f"{m}_sayfa.jsonl"
        if not p.exists():
            continue
        for s in open(p, encoding="utf-8"):
            x = json.loads(s)
            if x["sayfa"] in sayfalar:
                sayfalar[x["sayfa"]]["h"][m] = [x["hukum"][0], x["kritik"], x["orta"], x["hafif"], x["kelime"],
                                                [[o[0][0], o[1], str(o[2])[:70], str(o[3])[:70]] for o in x.get("ornek", [])[:8]]]
    modeller = {}
    for m, o in ozet.items():
        e = o.get("ek_olcu", {})
        modeller[m] = {
            "ad": AD.get(m, m), "temiz": o["temiz"], "hukum": {k: o["hukum"][k] for k in ("temiz", "duzeltilebilir", "guvenilmez")},
            "kat_temiz": o["hukum"]["kategori_temiz"], "ceza": o["hukum"].get("ceza"), "birim": o["oku_skor"],
            "tob": o["tob"], "kull": o["kullanilabilirlik"], "kat_kull": o["hukum"]["kategori_kullanilabilirlik"],
            "aile": o["aile"], "aile_kat": o["aile_kategori"], "ayrik": o.get("ayrik"), "ayirt": o.get("ayirt_edici"),
            "ek": {k: e.get(k) for k in ("kapi", "kapsam", "fazlalik", "chrf_p", "chrf_r", "chrf", "der_eksik", "der_fazla", "nokta", "kok_dogruluk", "ek_dogruluk")},
            "morf": e.get("morf", {}), "kapi_neden": {k[6:]: v for k, v in o["teshis"].items() if k.startswith("temel_") and k != "temel_uydurma"},
            "iz": {k: o.get("iz_" + k) for k in ("temel_degil", "incelenmis", "sentetik_haric")}, "teshis": o["teshis"]}
    veri = {"uretim": time.strftime("%d.%m.%Y %H:%M"), "kat_ad": KAT, "modeller": modeller, "sayfalar": sayfalar,
            "test_say": test_say, "sayfa_say": len(meta), "belge_say": len({m["belge"] for m in meta}),
            "kat_say": dict(collections.Counter(m["kategori"] for m in meta))}
    html = Path(a.sablon).read_text(encoding="utf-8").replace("/*__VERI__*/null", json.dumps(veri, ensure_ascii=False, separators=(",", ":")).replace("\ufffd", "\\ufffd"))
    if a.yerel:
        html = '<!doctype html>\n<html lang="tr">\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n' + html
    Path(a.cikti).write_text(html, encoding="utf-8")
    print(a.cikti, f"{len(html) / 1e6:.1f} MB", len(modeller), "model", len(sayfalar), "sayfa")


if __name__ == "__main__":
    main()

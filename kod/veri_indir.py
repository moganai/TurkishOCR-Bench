"""Sayfa görüntülerini ve doğru metinleri Hugging Face'ten veri/ klasörüne indirir.

Depoda yalnız veri/sayfalar.jsonl ve veri/kutu/ bulunur; veri/goruntu/ ve veri/dogru_metin/ bu betikle gelir.
Puanlama için doğru metin yeterlidir; görüntüler yalnız bir modeli çalıştırmak için gerekir.

Kullanım:
  python veri_indir.py                 # doğru metin + görüntüler (~250 MB)
  python veri_indir.py --yalniz-metin  # yalnız doğru metin (~2 MB)

Veri kümesi özelse önce `hf auth login` ile oturum açın ya da HF_TOKEN ortam değişkenini verin.
"""
import argparse
from pathlib import Path

from huggingface_hub import snapshot_download

DEPO = "moganai/TurkishOCR-Bench"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hedef", default=str(Path(__file__).resolve().parent.parent / "veri"))
    ap.add_argument("--yalniz-metin", action="store_true", help="görüntüleri indirme")
    ap.add_argument("--surum", default=None, help="veri kümesinin commit'i ya da etiketi (varsayılan: en güncel)")
    a = ap.parse_args()
    desen = ["dogru_metin/**"] + ([] if a.yalniz_metin else ["goruntu/**"])
    yol = snapshot_download(DEPO, repo_type="dataset", revision=a.surum, allow_patterns=desen, local_dir=a.hedef)
    n_metin = sum(1 for _ in Path(yol, "dogru_metin").rglob("*.md"))
    n_gor = sum(1 for p in Path(yol, "goruntu").rglob("*") if p.is_file()) if not a.yalniz_metin else 0
    print(f"{yol}: {n_metin} doğru metin" + (f", {n_gor} görüntü" if n_gor else ""))


if __name__ == "__main__":
    main()

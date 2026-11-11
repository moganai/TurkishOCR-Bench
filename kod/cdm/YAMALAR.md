# CDM (UniMERNet) — TurkishOCR-Bench kopyası

Kaynak: https://github.com/opendatalab/UniMERNet, `cdm/` klasörü, commit `5a2c80d96b1d2dba447ff18d873e5fb73ba03c35`. Lisans: Apache-2.0 (`LICENSE`).
Yöntem: Wang ve ark., *Image Over Text: Transforming Formula Recognition Evaluation with Character Detection Matching* (CVPR 2025).

`modules/latex2bbox_color.py` dosyasında yalnız aşağıdaki değişiklikler yapıldı. CDM'in eşleştirme ve puan hesabına dokunulmadı.

1. **Derleyici:** `pdflatex` yerine `tectonic` kullanılır: `tectonic --keep-logs --outdir …`, zaman sınırı 120 sn. macOS'ta TeX Live gerekmez; `brew install tectonic imagemagick ghostscript` yeterlidir.
2. **`\mathcolor`:** Üç şablona grupsuz bir `\mathcolor` tanımı eklendi. Tectonic'in TeX demeti, LaTeX çekirdeğinin 2022'deki `\mathcolor` komutunu içermez.

   ```latex
   \providecommand{\mathcolor}{}\renewcommand{\mathcolor}[3][]{\color[#1]{#2}#3}
   ```

   Tanım grupsuzdur, çünkü CDM her simgeyi ayrı renklendirir ve `\left(` gibi ayraçlar gruba alınamaz.
3. **`\operatorname`:** Renklendirilmiş LaTeX'te `\operatorname*` ve `\operatorname` → `\mathrm`. Renk sıfırlaması `\nolimits`'ten önce araya girip derlemeyi bozuyordu. Değişiklik doğru metne ve model çıktısına aynı biçimde uygulanır ve yalnız operatör adlarının (max, exp …) yerleşimini etkiler.

Gereken araçlar: Python 3.10 (`numpy<2`, `scikit-image<=0.20`, `opencv-python-headless`, `matplotlib`, `tqdm`), Node.js, ImageMagick (`magick`), Ghostscript, tectonic.

Paketle gelen 19 modelin bütün CDM sonuçları `testler/cdm_onbellek.json` dosyasındadır. Bu sonuçları yeniden üretmek için TeX gerekmez. CDM yalnız yeni bir modelin önbellekte olmayan formül çiftleri için çalışır (`tob_v3.py --cdm-calistir`).

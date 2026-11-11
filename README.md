# TurkishOCR-Bench

Türkçe belge OCR'ı için sayfa düzeyinde bir benchmark. Bir modelin sayfayı **ne kadar doğru okuduğunu** ve çıktının **elle düzeltmeye ne kadar az ihtiyaç duyduğunu** ölçer.

- **488 sayfa · 368 belge · 10 kategori · 18 model.**
- **Türkçe'ye özgü hatalar ayrıca sınanır:** Türkçe karakter (ı/i, ş/s, İ/I), şapkalı harf, ondalık virgül, olumsuzluk eki.
- **Gösterim farkı ceza almaz, okuma hatası alır.** Markdown/HTML/LaTeX yazımı, `$O_2$` / `O₂`, kalın, tırnak türü ve boşluk aynı sayılır.
- **Ana skor: TOB-Skor = (Metin_TR + Tablo + Formül) / 3.** Tablo TEDS, formül CDM ile, OmniDocBench'teki gibi ölçülür. Metin bileşeni Türkçe ağırlıklıdır.

Puanlama kuralları **v1.0** olarak dondurulmuştur (2026-11-11). Bütün kurallar [`PUANLAMA.md`](PUANLAMA.md)'dedir.

## Sonuçlar

%95 güven aralığı: kategori içinde katmanlı belge bootstrap, 1.000 tekrar.

| # | Model | **TOB-Skor** | %95 GA | Metin_TR | Tablo (TEDS) | Formül (CDM) | Temiz sayfa | Güvenilmez sayfa |
|---|---|---|---|---|---|---|---|---|
| 1 | GPT-6.1 Sol | **96,2** | 95,5–96,9 | 92,5 | 96,6 | 99,6 | 71,9 | 18,3 |
| 2 | Gemma-4-31B | **92,2** | 90,9–93,3 | 87,1 | 92,2 | 97,3 | 51,6 | 30,2 |
| 3 | Qwen3.8-flash-next | **92,0** | 90,7–93,2 | 83,0 | 94,1 | 98,9 | 42,6 | 32,7 |
| 4 | **MoganOCR-TR (2B)** | **89,9** | 87,1–92,2 | 89,4 | 82,5 | 97,8 | 65,8 | 26,8 |
| 5 | DeepSeek-v4.1-flash | **89,2** | 86,4–91,3 | 82,9 | 87,6 | 97,1 | 52,6 | 32,7 |
| 6 | Mistral Large 4 | **86,4** | 84,2–88,0 | 71,6 | 91,4 | 96,2 | 19,3 | 62,6 |
| 7 | MiMo-v2.6-pro | **84,7** | 82,6–86,7 | 69,3 | 86,2 | 98,7 | 24,5 | 57,9 |
| 8 | Qwen3.5-9B | **83,9** | 81,1–86,4 | 69,5 | 85,1 | 97,1 | 19,7 | 54,6 |
| 9 | dots.ocr | **82,2** | 76,8–86,8 | 75,3 | 80,9 | 90,2 | 42,8 | 42,2 |
| 10 | OngunOCR | **81,2** | 78,5–83,9 | 78,3 | 69,3 | 96,1 | 44,5 | 39,3 |
| 11 | Nemotron 3.5 Super VL | **72,2** | 68,3–75,4 | 38,7 | 85,4 | 92,4 | 3,7 | 81,9 |
| 12 | PaddleOCR-VL-1.6 | **71,3** | 68,5–73,9 | 44,8 | 73,6 | 95,6 | 3,9 | 74,4 |
| 13 | MiniMax M3.1 Flash | **65,4** | 61,4–68,7 | 37,5 | 79,5 | 79,1 | 6,6 | 85,0 |
| 14 | DeepSeek-OCR-2 | **64,5** | 60,7–68,1 | 55,2 | 53,7 | 84,8 | 15,0 | 71,4 |
| 15 | GLM-OCR | **59,9** | 56,7–63,8 | 29,3 | 56,1 | 94,2 | 1,3 | 73,9 |
| 16 | Qwen3-VL-30B | **53,8** | 47,4–60,5 | 52,7 | 49,0 | 59,7 | 11,8 | 61,4 |
| 17 | Qwen3.5-2B | **51,0** | 45,4–56,1 | 36,7 | 50,7 | 65,6 | 1,6 | 85,6 |
| 18 | Indra OCR | **49,4** | 45,2–53,8 | 55,6 | 53,8 | 38,9 | 14,3 | 64,3 |

- **Temiz sayfa:** kritik hatası yok ve 100 kelimede en fazla 1 orta hata. **Güvenilmez sayfa:** en az 1 kritik hata. İkisi de ana skora girmez.
- **Komşu sıralar çoğu zaman ayrışmaz.** Güven aralıkları örtüşen modeller için "daha iyi" denmemelidir; örneğin Gemma ile Qwen3.8, MoganOCR-TR ile DeepSeek-v4.1-flash.
- **Bileşenleri ayrı okuyun.** Formül bileşeni çoğu modelde tavana yakındır; modelleri en çok Metin_TR ayırır.

Metin bileşeninin test aileleri (%):

| Model | Doğruluk_metin | Kullanılabilirlik_metin | metin | turkce | sayi | tire | kapsam |
|---|---|---|---|---|---|---|---|
| GPT-6.1 Sol | 97,0 | 88,2 | 94,8 | 96,9 | 99,0 | 97,2 | 99,7 |
| Gemma-4-31B | 95,0 | 79,9 | 90,2 | 96,8 | 98,3 | 94,5 | 99,6 |
| Qwen3.8-flash-next | 92,1 | 74,8 | 87,1 | 92,4 | 97,9 | 91,2 | 99,0 |
| **MoganOCR-TR (2B)** | 94,2 | 84,9 | 92,5 | 97,6 | 97,8 | 88,7 | 99,3 |
| DeepSeek-v4.1-flash | 91,3 | 75,3 | 86,7 | 93,4 | 95,1 | 89,8 | 97,4 |
| Mistral Large 4 | 88,8 | 57,7 | 78,1 | 89,4 | 97,0 | 90,6 | 97,1 |
| MiMo-v2.6-pro | 84,5 | 56,9 | 75,4 | 86,4 | 92,0 | 84,3 | 94,5 |
| Qwen3.5-9B | 81,6 | 59,2 | 76,6 | 87,3 | 95,0 | 67,4 | 97,6 |
| dots.ocr | 85,7 | 66,3 | 82,0 | 92,8 | 89,7 | 78,2 | 93,3 |
| OngunOCR | 89,0 | 68,8 | 85,7 | 93,8 | 95,1 | 81,3 | 98,4 |
| Nemotron 3.5 Super VL | 67,9 | 22,1 | 48,5 | 77,5 | 94,5 | 51,2 | 95,3 |
| PaddleOCR-VL-1.6 | 70,9 | 28,3 | 57,0 | 76,1 | 83,3 | 67,0 | 90,1 |
| MiniMax M3.1 Flash | 68,3 | 20,6 | 46,4 | 79,2 | 85,0 | 62,5 | 85,1 |
| DeepSeek-OCR-2 | 71,9 | 42,3 | 64,6 | 87,2 | 84,8 | 51,0 | 87,6 |
| GLM-OCR | 67,3 | 12,7 | 45,3 | 69,2 | 88,2 | 66,6 | 93,7 |
| Qwen3-VL-30B | 63,9 | 43,5 | 59,2 | 71,2 | 75,4 | 50,0 | 79,4 |
| Qwen3.5-2B | 59,9 | 22,5 | 46,9 | 71,8 | 75,9 | 45,1 | 76,8 |
| Indra OCR | 75,7 | 40,8 | 68,0 | 76,6 | 89,3 | 69,0 | 89,6 |

Sayfa ve test düzeyindeki bütün sonuçlar `sonuclar/` klasöründedir; `sonuclar/site/index.html` sonuçları tarayıcıda gezilebilir biçimde gösterir.

## Kategoriler

| Kategori | Sayfa | Kategori | Sayfa |
|---|---|---|---|
| akademik | 60 | kitap | 50 |
| tablo | 60 | fis_fatura_form | 50 |
| formul | 60 | el_yazisi | 50 |
| taranmis | 59 | resmi_yeni (Resmî Gazete) | 35 |
| slayt | 35 | resmi_eski (Resmî Gazete, eski) | 29 |

## Depo düzeni

Sayfa görüntüleri ve doğru metinler Hugging Face'tedir: [moganai/TurkishOCR-Bench](https://huggingface.co/datasets/moganai/TurkishOCR-Bench). Kod, testler, model çıktıları ve sonuçlar bu depodadır.

| Klasör | İçerik |
|---|---|
| `veri/goruntu/<kategori>/<id>` | Sayfa görüntüleri (488). Depoda yoktur; Hugging Face'ten indirilir |
| `veri/dogru_metin/<kategori>/<id>.md` | Doğru metin (488). Depoda yoktur; Hugging Face'ten indirilir |
| `veri/kutu/<id>.js` | Sayfadaki kelime kutuları: uydurma tespiti ve satır sonu tire testleri için |
| `veri/sayfalar.jsonl` | Sayfa listesi: id, kategori, belge, başlık, kaynak, lisans, url |
| `testler/` | Doğru metinden üretilmiş birim testler (`testler.jsonl`, 115.116 test), KaTeX ve CDM önbellekleri |
| `kod/` | Test üretici, puanlayıcı, ana skor, CDM (`cdm/`), regresyon testleri, sonuç sitesi üreticisi, modellere verilen istem (`istem.txt`) |
| `model_ciktilari/<model>/<kategori>/<id>.md` | 18 modelin çıktıları; `kayit.jsonl` bitiş nedenini (stop/length) tutar |
| `sonuclar/` | `rapor_v3.md` ve `tob_v3.json` (ana skor), `tob_v3_sayfa.jsonl`, `tob_v3_formul.jsonl`, `ozet.json`, `rapor.md` (ek ölçüler), model başına sayfa ve test düzeyi sonuçlar |

## Puanlama (özet)

1. **Ön işlem.** Doğru metin ve çıktı aynı dönüştürücüden geçer; aynı içeriğin farklı yazımları aynıdır. Üst/alt bilgi ve görsel içi yazı nötrdür. El yazısında büyük/küçük harf ayırt edilmez.
2. **TOB-Skor = (Metin_TR + Tablo + Formül) / 3.** Her bileşen yalnız o öğeyi içeren sayfalarda hesaplanır: metin 488, tablo 118, formül 47 sayfa. Kategoriler √n ağırlığıyla ortalanır (n: kategoride o öğeyi içeren sayfa sayısı).
3. **Metin_TR = √(Doğruluk_metin × Kullanılabilirlik_metin).**
   - **Doğruluk_metin:** metin, turkce, sayi ve tire test ailelerinin geçme oranı.
   - **Kullanılabilirlik_metin:** sayfa cezası = 100 × (5·kritik + 2,5·Türkçe karakter + 1·diğer orta + 0,1·hafif) / (kelime + 30); sayfa puanı = 2^(−ceza/5). Ağırlıklar WMT MQM'den (Freitag ve ark., 2021).
4. **Tablo:** doğru tablo model tablolarıyla eşlenir, eşleşen çiftin TEDS'i alınır; eşi olmayan tablo 0 alır.
5. **Formül:** yalnız blok formüller (193 formül). Puanlayıcının formül testi geçtiyse 1; geçmediyse CDM F1; model LaTeX yazmadıysa ya da CDM derleyemediyse normalize edit benzerliği.
6. **Kapı:** boş, kesik, döngüye girmiş ya da yabancı alfabeli sayfa üç bileşende de 0 alır.

## Çalıştırma

```bash
cd kod
pip install -r gereksinimler.txt        # formüller için Node.js da gerekir

# sayfa görüntülerini ve doğru metinleri Hugging Face'ten veri/ klasörüne indir (~250 MB)
python veri_indir.py                    # yalnız puanlama için: python veri_indir.py --yalniz-metin

# kuralların değişmediğini doğrula (35 test)
python test_gosterim.py

# 1) birim testler ve sayfa hataları: model_ciktilari/ altındaki bütün modeller, çıktı sonuclar/
python oku_puanla.py

# 2) ana skor: Metin_TR + TEDS + CDM
python tob_v3.py

# sonuç sitesi
python site_uret.py --sonuc ../sonuclar --testler ../testler --cikti ../sonuclar/site/index.html --yerel
```

Bu komutlar depodaki sonuçları birebir yeniden üretir. Paketle gelen 18 modelin CDM sonuçları `testler/cdm_onbellek.json`'dadır; yeniden üretmek için TeX gerekmez.

Testleri doğru metinden yeniden üretmek isteğe bağlıdır (`testler/` hazır gelir):

```bash
python oku_testler.py --cikti ../testler
```

### Yeni model eklemek

1. Modeli `kod/istem.txt` istemiyle 488 sayfada çalıştırın. Kendi sabit istemi olan OCR modelleri kendi hatlarıyla çalıştırılabilir.
2. Çıktıları `model_ciktilari/<ad>/<kategori>/<id>.md` olarak koyun. Çıktısı token sınırında kesilen sayfaları `kayit.jsonl` içinde `{"id": "<id>", "bitis": "length"}` satırıyla bildirin.
3. Yalnız yeni modeli ayrı bir klasöre puanlayın:

```bash
python oku_puanla.py --cikti ../sonuclar_yeni <ad>=../model_ciktilari/<ad>
python tob_v3.py --sonuc ../sonuclar_yeni --cdm-calistir --cdm-python <cdm ortamının python'u>
```

`--cdm-calistir`, önbellekte olmayan formül çiftleri için CDM'i çalıştırır; kurulumu `kod/cdm/YAMALAR.md`'dedir. Skor her model için bağımsızdır: yeni model eklemek diğerlerinin skorunu değiştirmez.

## Doğru metin

- PDF metin katmanı ve kelime kutularıyla çift kaynaklı satır kontrolü yapıldı.
- Üç ayrı kişi kelime kelime kontrol etti.
- Doğru metin sayfadaki yazım ve baskı hatalarını korur.

Ayrıntı ve bilinen sınırlar `PUANLAMA.md` bölüm 8'dedir.

## Çalıştırma notları

- Genel modeller `kod/istem.txt` istemiyle; dots.ocr, PaddleOCR-VL, GLM-OCR, Indra OCR ve OngunOCR kendi sabit hatlarıyla çalıştırıldı.
- MoganOCR-TR, görüntü üst sınırı 4.194.304 piksel (Hugging Face'teki işlemci ayarı) ile çalıştırıldı.
- MiniMax 10, GLM-OCR 2, Indra OCR 1 sayfada çıktı vermedi. Bu sayfalar o model için kapıya takılmış sayıldı.

## Lisans

Her sayfanın kaynak lisansı `veri/sayfalar.jsonl`'deki `lisans` alanındadır: by-nc 144, cc-by-4.0 91, FSEK m. 31 (resmî mevzuat) 90, internet üzerinden açık kaynak (lisans belirtilmemiş) 50, by 33, cc-by-nc-4.0 25, by-sa 17, cc-by-nc-sa-4.0 17, public domain 15, by-nc-sa 4, cc-by-sa-4.0 2.

Veri kümesinin tek bir lisansı yoktur; her sayfa kendi kaynağının lisansına tabidir. 190 sayfa ticari kullanıma izin vermez (NC), 40 sayfa türevlerin aynı lisansla paylaşılmasını ister (SA).

`kod/cdm/` UniMERNet'in CDM uygulamasıdır (Apache-2.0); yapılan değişiklikler `kod/cdm/YAMALAR.md`'dedir.

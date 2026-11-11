# TurkishOCR-Bench v3.1: TOB-Skor

TOB-Skor = (Metin_TR + Tablo + Formül) / 3. Metin_TR = √(Doğruluk_metin × Kullanılabilirlik_metin); Tablo = TEDS; Formül = blok formüllerde puanlayıcı testi, değilse CDM. Kategoriler √n ağırlıklı ortalanır. Ayrıntı: PUANLAMA.md.

| # | Model | **TOB-Skor** | Metin_TR | Doğruluk_metin | Kullanılabilirlik_metin | Tablo (TEDS) | Formül (CDM) | v2 TOB |
|---|---|---|---|---|---|---|---|---|
| 1 | gpt-6.1-sol | **96.2** | 92.5 | 97.0 | 88.2 | 96.6 | 99.6 | 91.5 |
| 2 | Gemma | **92.2** | 87.1 | 95.0 | 79.9 | 92.2 | 97.3 | 86.7 |
| 3 | Qwen3.8 | **92.0** | 83.0 | 92.1 | 74.8 | 94.1 | 98.9 | 82.3 |
| 4 | moganocr-tr | **89.9** | 89.4 | 94.2 | 84.9 | 82.5 | 97.8 | 86.4 |
| 5 | DeepSeek | **89.2** | 82.9 | 91.3 | 75.3 | 87.6 | 97.1 | 82.9 |
| 6 | mistral-large-4 | **86.4** | 71.6 | 88.8 | 57.7 | 91.4 | 96.2 | 71.8 |
| 7 | mimo | **84.7** | 69.3 | 84.5 | 56.9 | 86.2 | 98.7 | 69.8 |
| 8 | qwen3.5-9b | **83.9** | 69.5 | 81.6 | 59.2 | 85.1 | 97.1 | 68.9 |
| 9 | dots-ocr | **82.2** | 75.3 | 85.7 | 66.3 | 80.9 | 90.2 | 72.7 |
| 10 | ongun-ocr | **81.2** | 78.3 | 89.0 | 68.8 | 69.3 | 96.1 | 75.8 |
| 11 | nemotron-3.5 | **72.2** | 38.7 | 67.9 | 22.1 | 85.4 | 92.4 | 39.7 |
| 12 | paddleocr-vl-1.6 | **71.3** | 44.8 | 70.9 | 28.3 | 73.6 | 95.6 | 45.8 |
| 13 | minimax-m3.1 | **65.4** | 37.5 | 68.3 | 20.6 | 79.5 | 79.1 | 37.2 |
| 14 | deepseek-ocr-2 | **64.5** | 55.2 | 71.9 | 42.3 | 53.7 | 84.8 | 53.4 |
| 15 | glm-ocr | **59.9** | 29.3 | 67.3 | 12.7 | 56.1 | 94.2 | 29.3 |
| 16 | qwen3-vl-30b | **53.8** | 52.7 | 63.9 | 43.5 | 49.0 | 59.7 | 50.5 |
| 17 | qwen3.5-2b | **51.0** | 36.7 | 59.9 | 22.5 | 50.7 | 65.6 | 34.7 |
| 18 | indra-ocr | **49.4** | 55.6 | 75.7 | 40.8 | 53.8 | 38.9 | 48.1 |

Formül puanının kaynağı (blok formül × model): {'cdm': 935, 'test': 2245, 'kismi': 140, 'kapi': 154}

# TurkishOCR-Bench v3.1: puanlama kuralları

Bu belge skorların nasıl hesaplandığını eksiksiz anlatır. Kurallar **v3.1** olarak dondurulmuştur (2026-11-11). Bir kuralı değiştirmek sürüm yükseltmeyi ve `kod/test_gosterim.py` regresyon testlerinin bilinçli olarak güncellenmesini gerektirir.

Kod `kod/` klasöründedir:
- `oku_testler.py` doğru metinden testleri üretir.
- `oku_puanla.py` model çıktılarını birim testlerle puanlar ve sayfa hatalarını çıkarır.
- `tob_v3.py` ana skoru (TOB v3) hesaplar: Metin_TR, tablo TEDS, formül CDM.
- `cdm/` formül CDM ölçüsüdür (UniMERNet, Apache-2.0; yamalar `cdm/YAMALAR.md`'de).
- `oku_ortak.py` ortak kuralları ve normalleştirmeyi içerir.
- `eval.py` Markdown/HTML/LaTeX dönüştürücüsüdür.
- `test_gosterim.py` bu belgedeki eşdeğerlikleri sınar.

## 1. Ana skor

> **TOB-Skor = (Metin_TR + Tablo + Formül) / 3**

| Bileşen | Sorduğu soru | Ölçü |
|---|---|---|
| **Metin_TR** | Sayfanın metni, Türkçe'ye özgü hatalar da düşünüldüğünde, ne kadar doğru ve elle düzeltmeden ne kadar kullanılabilir? | √(Doğruluk_metin × Kullanılabilirlik_metin) |
| **Tablo** | Tabloların yapısı ve hücreleri ne kadar doğru? | TEDS (OmniDocBench gibi) |
| **Formül** | Blok formüller ne kadar doğru? | Bizim normalleştirmemiz + CDM (OmniDocBench gibi) |

- Üç bileşen eşit ağırlıklıdır. Tablo ve formül OmniDocBench'in yöntemiyle ölçülür. Benchmarkı ayıran Türkçe duyarlılığı metin bileşenindedir.
- Her bileşen yalnız o öğeyi içeren sayfalardan hesaplanır: metin 488 sayfadan, tablo tablolu sayfalardan, formül blok formüllü 47 sayfadan. Sayfa puanları önce kategori içinde ortalanır, sonra kategoriler **√n ağırlığıyla** birleştirilir (n: kategoride o öğeyi içeren sayfa sayısı). Böylece iki sayfalık bir hücre altmış sayfalık hücreyle aynı ağırlığı almaz, ama yok da sayılmaz.
- Kapıya takılan sayfa (boş, kesik, döngü, yabancı alfabe) üç bileşende de 0 alır.
- Skor her model için bağımsız hesaplanır; yeni model eklemek diğerlerinin skorunu değiştirmez.

### 1.1 Metin_TR

> **Metin_TR = √(Doğruluk_metin × Kullanılabilirlik_metin)**

- **Doğruluk_metin:** metin, turkce, sayi ve tire test ailelerinin geçme oranı (bölüm 3–4); her aile kategoriler boyunca √n ağırlıklı, aileler eşit ağırlıklıdır. Tablo ve formül testleri kendi bileşenlerinde ölçüldüğü için buraya girmez.
- **Kullanılabilirlik_metin:** bölüm 6'daki MQM sayfa puanı, iki farkla:
  - tablo (`tablo_yapisi`, `tablo_hucre_yeri`) ve formül (`formul`, `formul_kucuk_fark`, `formul_buyuk_kucuk`) hata türleri cezadan çıkarılır;
  - paydada formül tokenı yoktur: kelime + 30.
- Geometrik ortalama kullanılır, böylece biri ötekini telafi edemez. Bilginin çoğunu doğru okuyup sayfalarında kritik hata yapan model yüksek Metin_TR alamaz.
- Tablo hücrelerindeki kelimeler metindir: hücredeki Türkçe karakter ya da sayı hatası Metin_TR'yi de düşürür.

### 1.2 Tablo (TEDS)

- Doğru metin ve çıktıdaki tablolar (Markdown, HTML, LaTeX) bölüm 2'deki dönüştürücüyle hücre ızgarasına çevrilir. Hücre içeriği normalleştirilmiştir.
- Her doğru tablo, model tablolarıyla tam doğru hücre sayısına göre Macar yöntemiyle eşlenir.
- Eşleşen çift için TEDS hesaplanır: tablo → satır → hücre ağacında ağaç düzenleme uzaklığı, hücre yeniden adlandırma maliyeti normalize Levenshtein. Sonra 1 − uzaklık / en büyük düğüm sayısı alınır.
- Eşi olmayan doğru tablo 0 alır. Sayfa puanı, sayfadaki tabloların ortalamasıdır.
- **Tablosu isteğe bağlı sayfalar:** beş sayfada (`sl_12726650_32`, `el_221943087880384370`, `rg_201`, `rg_73`, `rg_74`) içerik hem tablo hem düz metin olarak savunulabilir biçimde yazılabilir (renkli kutular, anahtar–değer satırları, kısa liste, içindekiler). Bu sayfalar `sayfalar.jsonl` içinde `tablo_istege_bagli` ile işaretlidir ve Tablo bileşenine girmez; hücre içerikleri Metin_TR'deki metin, Türkçe, sayı ve tire testleriyle her iki yazımda da aynı şekilde puanlanır. 
- **Üst/alt bilgideki tablo:** doğru metinde `<header>` ya da `<footer>` içinde duran tablo (ajanda sayfasının altındaki basılı takvim gibi) sayfa içeriği değildir; üst/alt bilginin geri kalanı gibi nötrdür, tablo testi üretilmez ve TEDS'e girmez. Tablo bileşeni böylece 118 sayfadan hesaplanır.
- Fark: OmniDocBench TEDS'i HTML etiket ağacında hesaplar. Burada ağaç, birleştirilmiş hücreleri açılmış ızgaradır. Bu yüzden `rowspan`/`colspan` yazım farkı ceza almaz, hücre yeri ve içeriği alır.

### 1.3 Formül (CDM)

OmniDocBench gibi yalnız **blok formüller** puanlanır: 193 formül, 47 sayfa. Satır içi formüller bölüm 2'deki kurallarla metne çevrilir ve Metin_TR'de ölçülür. Her blok formülün puanı sırayla şöyle belirlenir:

1. Puanlayıcının formül testi geçtiyse **1**. Test, bölüm 2'deki normalleştirmeden sonra KaTeX kanonunda karşılaştırır: `\tag` ↔ `(n)`, `{,}` ↔ `,`, `×` ↔ `\times`, görünüm komutları, satır bölme yeri, Unicode ↔ LaTeX.
2. Geçmediyse formül, model çıktısındaki LaTeX formülleriyle Macar yöntemiyle eşlenir. Eşleme, görünüm komutlarından arındırılmış edit benzerliğine göredir. Eşi varsa iki formül de temizlenir (`\tag`, `\label`, `\displaystyle` çıkar; `{,}` → `,`) ve puanı **CDM F1** olur. CDM, iki formülü çizip karakterleri görüntü üzerinde konumlarıyla eşleştirir (Wang ve ark., 2025).
3. Model formülü LaTeX yazmadıysa (Unicode düz metin) ya da CDM formülü derleyemediyse puanlayıcının **kısmi puanı** kullanılır: normalize edit benzerliği.

Sayfa puanı, sayfadaki blok formüllerin ortalamasıdır.

18 modelde puanın kaynağı (3.474 blok formül × model): puanlayıcı testi 2.245, CDM 935, kısmi puan 140, kapı 154. CDM sonuçları `testler/cdm_onbellek.json`'da saklanır. CDM'in bu pakette tectonic ile çalışması için yapılan üç küçük değişiklik `kod/cdm/YAMALAR.md`'dedir; eşleştirme ve puan hesabına dokunulmadı.

### 1.4 OmniDocBench ile uyum

OmniDocBench tarzı genel skor: metin 1−NED, tablo TEDS, formül edit benzerliği, eşit ağırlık. v3.0 sonuçlarında, OngunOCR hariç 18 modelde bu skorla Kendall τ:

| Skor | τ |
|---|---|
| v2 TOB-Skor, √(Doğruluk × Kullanılabilirlik) | 0,59 |
| **v3 TOB-Skor** | **0,87** |

Kalan fark bilerek bırakıldı. Tablo ve formülü doğru okuyup Türkçe metinde kritik hata yapan modeller Metin_TR'de geride kalır.

## 2. Ön işlem: gösterim farkı ceza almaz

Doğru metin ve model çıktısı aynı dönüştürücüden geçer. Aynı içeriğin farklı yazımları aynı kabul edilir; doğru metin dosyalarına dokunulmaz.

**Biçim:**
- Kalın, italik, başlık düzeyi, tırnak türü ve boşluk düzeni silinir.
- Markdown, HTML ve LaTeX tablo yazımları hücre ızgarasına çevrilir.
- Satır içi HTML biçim etiketleri (`<u> <b> <strong> <i> <em> <span> <small> <mark> <ins> <font>`) iz bırakmadan silinir. Örneğin `CH₂<u>CH₂</u>CH₃` = `CH₂CH₂CH₃`; NMR atamalarındaki altı çizili yazım kelimeyi bölmez.
- Üst ve alt bilgi (`<header>`, `<footer>`) nötrdür: test üretilmez.
- Görsel içindeki yazı (şekil lejantı, grafik etiketi) nötrdür. Doğru metin yalnız `<figure/>` içerir.

**Formül ve simge:**
- Komut içermeyen satır içi formüller metne çevrilir. Aşağıdakiler aynıdır:
  - `$O_2$` = `O₂` = `O<sub>2</sub>`
  - `$x^2$` = `x²`; `$10^{5}$` = `10⁵`
  - `$\alpha$` = `α`; `25$^\circ$C` = `25°C`
- Yalnız yazı biçimini değiştiren komutlar (`\mathrm`, `\mathbf`, `\text`, `\operatorname` …) dengeli parantezle açılır: `$\mathrm{C_{19}H_{32}ClN_3O_2}$` = `C₁₉H₃₂ClN₃O₂`.
- Aksan komutları harfe çevrilir: `\ddot{o}` = ö, `\dot{I}` = İ, `\hat{a}` = â.
- Virgülle ayrılmış Unicode alt/üst simgeler tek simgedir: `Hᵢ,ₕ` = `H_{i,h}`; `²⁸, ³⁸` = `$^{28,38}$` = `<sup>28, 38</sup>`. Simge içindeki boşluk yok sayılır.
- Alt simge düz yazıya iner: `NO_X` = `NOₓ`.
- Üst simge düz yazıya **inmez**: `28,38` (düz) ≠ `²⁸,³⁸`, `105` ≠ `10⁵`.
- Matematik içinde harfler arasındaki boşluk çizilmez: `$\Delta W$` = `ΔW`.
- Çarpma işareti: `×` = `x` = `\times`.
- Denklem numarası `\tag{n}` = metindeki `(n)`. Nokta dizisiyle sağa yaslanmış numara (`... ... ... 1`) ve kapanan ayraçtan sonra gelen `(n)` de numaradır.
- Formülün sonundaki cümle noktalaması (`,` `.` `;`) formülün parçası değildir.
- Formül ayraçları `$ $`, `$$ $$`, `\( \)` ve `\[ \]` eşit işlenir; formül içindeki `*` çarpım işaretidir, italik işareti değil.

**Semboller ve düzen:**
- Satır başındaki madde işaretleri (■ ● ▪ ► ◦ ✹ …) silinir. Onay kutuları (☐ ☑ ✓ ✔) bilgi taşıdığı için silinmez.
- Ok çeşitleri (➜ ➔ ⟶ ⇒ …) `→`'ya indirilir. Satır içindeki ara noktalar (` · `, ` • `) silinir.
- `˒` ve LaTeX `{,}` virgüldür.

**Kategoriye özgü:**
- **El yazısı:** büyük/küçük harf ayırt edilmez (formüller ve Yunan harfleri hariç). Türkçe'de büyük `I`'nın küçüğü `ı` olduğu için İ/I noktası farkı korunur.

**Neyin hata olduğu görsele göre belirlenir:**
- Ondalık ayırıcı görseldeki gibi olmalı: `4,5` ≠ `4.5`.
- Şapkalı harfler (â î û) ve İ/I ayrımı korunmalı.
- Görseldeki yazım ve baskı hataları korunmalı. Modeller "harfi harfine aktar" istemiyle çalıştırıldı; düzeltmek okuma hatasıdır.

## 3. Birim testler

Her sayfanın doğru metninden otomatik testler üretilir (toplam 115.116). Her test tek bir olguyu sınar ve ya geçer ya kalır.

**Doğruluk aileleri:**

| Aile | Sınadığı | Test |
|---|---|---|
| metin | ~12 tokenlık parça çıktıda harfi harfine var mı (aksan, büyük/küçük harf, noktalama dahil). Parçalar görsele bakmadan tahmin edilmesi zor bir tokenin (sayı, kod, özel ad, eski imla, nadir kelime) çevresinden alınır. Parçanın kelimeleri çıktıda doğru sayıda varsa kelime sırası farkı; karakterleri aynıysa boşluk farkı geçer | 14.639 |
| turkce | ç ğ ı ö ş ü, İ/I ve â î û içeren kelime doğru yazılmış mı. Payda modelin okuduğu kelimelerdir. Fazladan eklenen aksan (bilgi → bılgi) kalan test sayılır. Alt türler (şapka / büyük İ-I / diğer) eşit ağırlıklıdır | 59.822 |
| sayi | Rakam içeren her dizi işaretleriyle birebir mi (`4,5` ≠ `4.5`, `%10`, `-3`). Gövdedeki dipnot ve kaynak işaretleri (metin²⁵, metin²⁸,³⁸) ayrı türdür | 16.562 |
| tablo | Hücrenin sağ ve alt komşusu ile üst ve sol başlığı doğru mu. Hücreler bulanık karşılaştırılır (aksansız, küçük harf, noktalamasız, %85). Boş hücreler komşuluğa sayılmaz. Değerleri hücrede alt alta yazmak ile `rowspan` ile ayrı satırlara bölmek aynıdır | 5.711 |
| formul | Gerçek matematik formülü (`\frac`, `\sqrt`, `\sum` … içeren) KaTeX kanonunda birebir mi. Farklı `$` sınırı, yalnız görünüm komutları ya da farklı satır bölme yeri geçer. Bütün terimleri kelime olan sözel formül (`\text{Ortalama hız} = \frac{\text{Toplam alınan yol}}{\text{Zaman}}`) düz metin ya da yarı formül yazıldığında da geçer (`Ortalama hız = Toplam alınan yol / Zaman`). Birebir bulunamayan formül, en benzer formüle normalize edit benzerliği kadar kısmi puan alır (OmniDocBench CDM karşılığı) | 258 |
| tire | Satır sonunda bölünmüş kelime tek parça yazılmış mı | 1.501 |

**Sayfa hatası aileleri** (Doğruluk ortalamasına girmez, bulunan hata kullanılabilirliği düşürür):

| Aile | Sınadığı | Test |
|---|---|---|
| sıra | Ardışık iki paragrafın sırası korunmuş mu. Yalnız paragrafların tek ve belirgin bir sırayla okunduğu kategorilerde ölçülür: akademik, kitap, Resmî Gazete (yeni, eski), taranmış, formül. El yazısı, slayt, fiş/form ve tablo sayfalarında sütun/kutu sırasının tek doğrusu olmadığından ölçülmez | 2.181 |
| kapsam | Gövde baştan sona ~12 tokenlık parçalara bölünür; parça (aksansız, küçük harf, kelimelerinin en az %80'i) çıktıda var mı. Atlanan metni yakalar | 13.954 |
| temel (kapı) | Sayfa başına tek test: boş çıktı, kesilme (`length`), tekrar döngüsü ya da yabancı alfabe (en az 3 harf) var mı. Varsa sayfanın bütün testleri kalır ve sayfa puanı 0 olur | 488 |

## 4. Doğruluk

1. Her ailede, her kategori içinde geçen test oranı hesaplanır.
2. Kategorilerin eşit ağırlıklı ortalaması ailenin puanıdır.
3. Altı ailenin (metin, turkce, sayi, tablo, formul, tire) eşit ağırlıklı ortalaması Doğruluk'tur. Ek ölçü olarak raporlanır (`ozet.json` → `oku_skor`).
4. Ana skordaki **Doğruluk_metin** aynı hesabın metin, turkce, sayi ve tire aileleriyle, kategoriler √n ağırlıklı ortalanarak yapılmış hâlidir (bölüm 1.1).

## 5. Hatalar ve şiddet

Kalan testler hatalara çevrilir ve şiddete ayrılır. Aynı hata iki aileden iki kez sayılmaz.

| Şiddet | Hata |
|---|---|
| **Kritik** | Yanlış ya da eksik sayı. Yanlış formül (benzerlik %90'ın altında). Tabloda veri hücresinin komşusunun değişmesi. Başka bir kelimeye dönmüş kelime. Olumsuzluk eki farkı (geldi ↔ gelmedi; Zeyrek ile, yalnız bütün çözümlemeler uyuşursa). 3 ve üzeri kelime eksik ya da fazla. Atlanmış gövde parçası. `[okunaksız]` yerine uydurma. Uydurma metin (doğru metinde ve görselde olmayan 4+ kelimelik dizi; harf aralıklı başlıklar birleştirilerek denetlenir). Felaket (kapı) |
| **Orta: Türkçe karakter** | ı/i, ş/s, ğ/g, ç/c, ö/o, ü/u, İ/I, â/a, î/i, û/u hataları; okunan kelimede eksik ya da fazla aksan |
| **Orta: diğer** | 1–2 harf hatası (görseldeki yazım hatasını düzeltmek dahil). Türkçe dışı aksan. Büyük/küçük harf. 1–2 kelime eksik ya da fazla. Ters paragraf sırası (sıra ölçülen kategorilerde). Tablo başlık yapısı. Birleştirilmemiş satır sonu tiresi. Eksik dipnot işareti. Formülde küçük fark (benzerlik %90 ve üstü) ya da yalnız büyük/küçük harf farkı |
| **Hafif** | Yalnız noktalama ya da kesme işareti farkı. Tamamen büyük harfli kelimede yalnız büyük/küçük farkı |
| **Ceza yok** | Yalnız boşluk farkı (harfler aynı, kelime bitişik ya da bölünmüş). El yazısında büyük/küçük harf. Sütun ve satır düzeni |

## 6. Kullanılabilirlik

Bu bölüm sayfa puanını tanımlar. Ana skordaki **Kullanılabilirlik_metin** bunun tablo ve formül hata türleri çıkarılmış, paydası kelime + 30 olan hâlidir (bölüm 1.1). Aşağıdaki tam hâli v2 skorunda ve ek ölçülerde kullanılır.

Önce her sayfanın ağırlıklı hata yükü hesaplanır:

> **ceza = 100 × (5·kritik + 2,5·Türkçe karakter + 1·diğer orta + 0,1·hafif) / (kelime + formül tokenı + 30)**

- **Ağırlıklar:** WMT MQM şemasından alınmıştır (Freitag ve ark., 2021): major 5, minor 1, minor/noktalama 0,1.
- **Türkçe karakter hatası 2,5:** Türkçe'de aksan ve nokta kelimenin anlamını değiştirir (sınır/sinir, şık/sık, ılık/ilik). Veride Türkçe karakter hatalarının yaklaşık %41'inde yanlış biçim de geçerli bir Türkçe kelimedir; bu orandan beklenen ağırlık ≈ 0,59×1 + 0,41×5 ≈ 3,0 çıkar, yani 2,5 temkinli bir değerdir.
- **Payda:** sayfadaki içerik miktarıdır, gövde ve tablo kelimeleri artı formül tokenları. Formül hataları cezaya girdiği için formül içeriği de paydaya girer.
- **+30:** kısa sayfa düzleştirmesidir. 70 kelimelik bir formda tek hata sayfayı sıfırlamaz; uzun sayfalarda etkisi ihmal edilebilir.

Sayfa puanı:

> **sayfa puanı = 2^(−ceza / 5)**

- Hatasız sayfa 1 alır. Kapıya takılan sayfa 0 alır.
- Ceza her 5 puanda bir yarıya iner. Puan hiçbir zaman eksiye düşmez.
- Üstel azalma, kalite algısındaki IQX ilişkisini izler: ilk ağır hata güveni en çok düşürür.

| Örnek sayfa | Puan |
|---|---|
| 300 kelime, hatasız | 1,00 |
| 300 kelime, 1 Türkçe karakter hatası | 0,90 |
| 300 kelime, 1 yanlış sayı | 0,81 |
| 70 kelime, 1 yanlış sayı | 0,50 |
| 70 kelime, 1 Türkçe karakter hatası | 0,71 |
| Boş, kesik ya da döngüye girmiş çıktı | 0 |

**Kullanılabilirlik** = sayfa puanlarının her kategori içinde ortalaması, kategorilerin eşit ağırlıklı ortalaması. Ana skordaki Kullanılabilirlik_metin'de kategoriler √n ağırlıklıdır.

## 7. Ek ölçüler (ana skora girmez)

- **v2 TOB-Skor:** √(Doğruluk × Kullanılabilirlik), altı aileli Doğruluk ve tam Kullanılabilirlik ile (`ozet.json` → `tob_v2`). v2.0 sürümünün ana skoruydu.

- **Sayfa hükmü (katı ölçü):** bir sayfa
  - **güvenilmez**dir, en az 1 kritik hatası varsa;
  - **temiz**dir, kritik hatası yoksa ve 100 kelimede en fazla 1 orta hatası varsa;
  - geri kalan durumlarda **düzeltilebilir**dir.

  "Temiz sayfa oranı" kategori makro hesaplanır.
- **Kapı oranı, kapsam oranı, ters sıra sayısı.**
- **Türkçe analizi:**
  - DER: eksik ve fazla aksan oranı; İ/I nokta hatası ayrı.
  - Zeyrek ile kök ve ek doğruluğu.
  - chrF kesinlik ve duyarlılık.
  - Kelime torbası fazlalığı.
- **Duyarlılık (v2 skorunda, v2.0 sonuçlarıyla ölçüldü):** sıralamanın, mevcut sıralamayla Kendall τ değeri:

  | Değiştirilen ayar | Kendall τ |
  |---|---|
  | Yarılanma 3 | 0,987 |
  | Yarılanma 10 | 0,935 |
  | Türkçe ağırlığı 1 | 0,948 |

  Sıralama parametre seçimine bağlı değildir.

## 8. Doğru metin ve bilinen sınırlar

- **Doğru metin:**
  1. 4 güçlü modelin taslağı (Muse 239, Gemma 122, DeepSeek 72, Qwen3.8 55 sayfa) hazırlandı.
  2. LLM hakemi taslakları birleştirdi.
  3. PDF metin katmanı ve Vision kutularıyla çift kaynaklı satır kontrolü yapıldı.
  4. Üç ayrı kişi kelime kelime kontrol etti.
  5. Ayrıca, doğru metnin taslak modeliyle aynı okuduğu ama iki bağımsız güçlü modelin birlikte farklı okuduğu 86 yer görselden yeniden incelendi; 39'u düzeltildi.
- **Taslak etkisi:** taslak modellerinin kendi taslak sayfalarında küçük bir avantajı kalabilir. README'deki tablo her taslak modelinin skorunu kendi taslağı olmayan sayfalarda da verir.
- **Seçim:** sayfalar, değerlendirilen modellerin en çok zorlandığı sayfalardan kategori kotalı seçildi. Skorlar genel bir sayfa dağılımını değil, zor sayfaları temsil eder.
- **İstem:** genel modeller `kod/istem.txt` istemiyle, kendi sabit istemi olan OCR modelleri (dots.ocr, PaddleOCR-VL, GLM-OCR, Indra OCR) kendi hatlarıyla çalıştırıldı.

## 9. Sürüm geçmişi

**v3.1 (2026-11-11), dondurulmuş.** v3.0'dan farkları:
- **Kategori ortalaması:** ana skorda kategoriler √n ağırlıklıdır (bölüm 1); belge bu kuralı artık doğru anlatır.
- **Formül ön işlemi:** nokta dizili ve ayraçtan sonra gelen denklem numarası, süslü parantezsiz `\tag*4` ve formül sonundaki noktalama formülden ayrılır. Formül içindeki `*` italik sanılıp silinmez. `\( \)` ve `\[ \]` ayraçlı formüller el yazısında küçük harfe çevrilmez.
- **Doğru metin:** dört formül satırı düzeltildi (üçünde `\tag{n})` sonundaki fazladan parantez, birinde `\tag*4`).
- **Model:** MoganOCR-TR eklendi; önceki mogan-ocr sürümü çıkarıldı (18 model).
- **Etki:** ana skorda en büyük değişim 0,3 puandır; sıralama değişmedi. Test sayısı 115.106'dan 115.116'ya çıktı.
- `test_gosterim.py` 35/35 geçer.

**v3.0 (2026-11-07).** v2.0'dan farkları:
- **Ana skor:** TOB-Skor = (Metin_TR + Tablo + Formül) / 3. Tablo TEDS ve formül CDM ile, OmniDocBench gibi. Metin_TR v2'nin Türkçe ağırlıklı doğruluk ve kullanılabilirlik ölçüsünün tablo ve formül çıkarılmış hâlidir (bölüm 1).
- **Çift sayım kaldırıldı:** tablo ve formül hataları artık yalnız kendi bileşenlerinde sayılır.
- **Formül kapsamı:** ana skorda yalnız blok formüller (193). Satır içi formüller metinde ölçülür.
- **Model:** OngunOCR eklendi (19 model).
- Birim testler, gösterim eşdeğerlikleri ve doğru metin v2.0 ile aynıdır; `test_gosterim.py` 35/35 geçer.

**v2.0 (2026-11-07).** v1'den farkları:
- **Ana skor:** TOB-Skor, MQM tabanlı sürekli kullanılabilirlikle.
- **Gösterim eşdeğerlikleri:** formül, simge, biçim etiketi ve sembol (bölüm 2).
- **Tablo:** boş hücre ve `rowspan` toleransı.
- **Sıra:** kategoriye bağlı ölçülüyor; sıra ve kapsam yalnız sayfa hatası.
- **Kaldırılan aile:** sadakat ailesi kaldırıldı; yazım düzeltmesi sıradan okuma hatasıdır.
- **El yazısı:** büyük/küçük harf serbest.
- **Kapsam:** kısa sayfa düzleştirmesi (+30); payda formül tokenlarını içerir.
- **Uydurma:** harf aralıklı başlıklar uydurma sayılmaz.
- **Veri:** `rg_53` çıkarıldı; benchmark 488 sayfadır.

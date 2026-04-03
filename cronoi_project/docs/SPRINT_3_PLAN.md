Haftalık Plan Kavramı
WeeklyPlan (Haftalık Plan)
├── Hafta: 2026-W13 (28 Mart - 1 Nisan)
├── Statü: taslak → onaylandı → tamamlandı
├── Toplam sipariş: 47
├── Tahmini palet: 84
├── Tahmini araç: 6 TIR + 1 panelvan
│
└── Sevkiyatlar (bu haftaya bağlı)
    ├── SEV-001: İzmir · TIR · Salı  · 12 sipariş · 24 palet
    ├── SEV-002: Bursa · TIR · Çarşamba · 8 sipariş
    └── SEV-003: İstanbul · 2× TIR · Perşembe


Adım Adım Doğru Akış
1. SİPARİŞ GİRİŞİ (Sürekli)
   ─────────────────────────
   Üretimden gelen siparişler → sisteme girilir (Excel / manuel)
   Statü: confirmed
   Siparişlerde mutlaka en erken teslim ve en geç teslim olur, proje numarası ve proje açıklaması olur. 
   
   
2. HAFTALIK PLAN OTURUMU (Pazartesi sabahı, ~30 dk)
   ─────────────────────────────────────────────────
   a) "Bu hafta gönderilecekler" seçilir
      Filtre: istenen_yükleme_tarihi bu hafta + öncelik
      Sipariş statüsü: confirmed → scheduled
   
   b) Sistem otomatik gruplar önerir
      "İzmir'e 3 sipariş → 1 TIR yeterli"
      "İstanbul'a 8 sipariş → 2 TIR gerekli"
   
   c) Araç ataması yapılır
      Her gruba: hangi araç, hangi gün, hangi sürücü
   
   d) HAFTALIK PLAN ONAYLANIR
      → Özet: "6 TIR, 2 Panelvan, 84 palet, 47 sipariş"
      → Nakliyeci bilgilendirmesi gider (email/mesaj)
      Sevkiyat statüsü: planned
   
   
3. YÜKLEME HAZIRLIĞI (Yükleme günü sabahı)
   ─────────────────────────────────────────
   a) Sistem depo ekibine yükleme listesi verir
      "Bugün 3 TIR yüklenecek — işte liste"
   b) Depo ürünleri toplar (pick list)
   c) Palet hazırlama (ürünleri paletlere koy)
   Sevkiyat statüsü: ready_to_load
   
   
4. FİZİKSEL YÜKLEME (Depo ekibi)
   ─────────────────────────────
   a) QR kod ile TIR açılır
   b) Hangi palet nereye → 3D plan ekranda
   c) Her palet yüklenince "tamamlandı" işaretlenir
   d) Fotoğraf çekilir
   e) TIR kapısı kapanır → yükleme tamamlandı
   Sipariş statüsü: loaded
   Sevkiyat statüsü: loaded → in_transit
   
   
5. TESLİMAT
   ─────────
   Alıcı teslim aldı → confirmed → delivered
   Tüm siparişler: delivered



Gerçek Hayat Akışı
ÜRETİM                    LOJİSTİK PLANLACI              DEPO / NAKLIYE
────────                  ─────────────────              ──────────────
Siparişler oluşur    →    Haftalık plan yapar    →       TIR yükler
(sürekli gelir)           (Pazartesi sabahı)             (Salı-Perşembe)
                          Nakliyeci ayarlar
                          Yükleme tarihi verir


Optimizasyon Noktaları : 
Optimizasyon 2 önemli noktada bulunur. Birincisi sevkiyatı planlanan ürünler için palet kütüphanesinden en az palet kullanarak kısıtlara uyacak şekilde hangi ürünlerin hangi paletlere koyulacağı belirlenir. Paletlerdeki boşluklar değerlendirilir. 

2. optimizasyon ise belirlenen paletler için optimum araç planlaması yapılır. Zaten kütüphanemizde bununla ilgili çalışmalar yer alıyor. 

gerisi haftalık özettedir. 
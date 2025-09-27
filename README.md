# Kemah Doğal Ürünler Pazarı

Flask tabanlı e-ticaret uygulaması.

## Özellikler

- 🛒 Ürün kataloğu ve sepet sistemi
- 👥 Kullanıcı kayıt ve giriş sistemi
- 🛡️ Admin paneli
- 📱 Responsive tasarım
- 📊 Ziyaretçi takibi
- 📝 Blog sistemi

## Demo Hesaplar

- **Admin**: admin / admin123
- **Kullanıcı**: test / test123

## Kurulum

### Yerel Geliştirme

```bash
# Bağımlılıkları yükle
pip install -r requirements.txt

# Uygulamayı başlat
python app.py
```

### Hosting Deploy

1. Bu dosyaları hosting sağlayıcınıza yükleyin
2. `requirements.txt` dosyasındaki paketler otomatik yüklenecek
3. `wsgi.py` dosyası WSGI entry point olarak kullanılacak

## Hosting Sağlayıcıları

### Heroku
```bash
heroku create kemah-dogal-urunler
git push heroku main
```

### PythonAnywhere
1. Files sekmesinde dosyaları yükleyin
2. Web sekmesinde WSGI dosyasını `wsgi.py` olarak ayarlayın

### DigitalOcean App Platform
1. GitHub repository bağlayın
2. Build command: `pip install -r requirements.txt`
3. Run command: `gunicorn wsgi:application`

## Dosya Yapısı

```
kemah1/
├── app.py              # Ana uygulama
├── wsgi.py             # WSGI entry point
├── config.py           # Konfigürasyon
├── requirements.txt    # Python bağımlılıkları
├── Procfile           # Heroku için
├── runtime.txt        # Python versiyonu
├── static/            # Statik dosyalar
├── templates/         # HTML şablonları
└── kemah.db          # SQLite veritabanı
```

## Teknik Detaylar

- **Framework**: Flask 2.3.3
- **Veritabanı**: SQLite
- **Frontend**: HTML, CSS, JavaScript
- **Authentication**: Flask-Login
- **Password Hashing**: Flask-Bcrypt

## Lisans

Bu proje Kemah Doğal Ürünler Pazarı için geliştirilmiştir.
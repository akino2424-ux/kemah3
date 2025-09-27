#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WSGI Entry Point for Kemah Doğal Ürünler Pazarı
Bu dosya hosting sağlayıcıları için WSGI uygulamasını tanımlar.
Production ortamında gunicorn ile çalışır.
"""

import os
import sys
import logging

# Proje dizinini Python path'ine ekle
project_dir = os.path.dirname(os.path.abspath(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# Logging ayarları
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s'
)

# Flask uygulamasını import et
from app import app as application

# Gerekli klasörleri oluştur
try:
    upload_folder = os.path.join(project_dir, 'static', 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    logging.info(f"Upload klasörü hazır: {upload_folder}")
except Exception as e:
    logging.error(f"Upload klasörü oluşturulamadı: {e}")

# Veritabanını başlat
try:
    from app import init_db
    init_db()
    logging.info("Veritabanı başarıyla başlatıldı!")
except Exception as e:
    logging.error(f"Veritabanı başlatma hatası: {e}")

# Production için güvenlik ayarları
if os.environ.get('FLASK_ENV') == 'production':
    application.config['DEBUG'] = False
    application.config['TESTING'] = False

if __name__ == "__main__":
    # Development için
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    application.run(debug=debug, host='0.0.0.0', port=port)

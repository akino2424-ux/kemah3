from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime
import os
import sqlite3
import time
import logging
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps

app = Flask(__name__, static_folder='static', static_url_path='/static')

# LocalTunnel için özel static dosya route'u
@app.route('/static/<path:filename>')
def static_files(filename):
    """LocalTunnel için özel static dosya servisi"""
    from flask import send_from_directory, make_response, request
    import os
    
    file_path = os.path.join(app.static_folder, filename)
    
    if not os.path.exists(file_path):
        return "File not found", 404
    
    # Dosyayı oku
    with open(file_path, 'rb') as f:
        content = f.read()
    
    response = make_response(content)
    
    # LocalTunnel için özel headers
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Cross-Origin-Embedder-Policy'] = 'unsafe-none'
    response.headers['Cross-Origin-Opener-Policy'] = 'unsafe-none'
    response.headers['Cross-Origin-Resource-Policy'] = 'cross-origin'
    response.headers['Cache-Control'] = 'public, max-age=3600'
    response.headers['Vary'] = 'Accept-Encoding'
    
    # Content-Type ayarları
    if filename.endswith('.css'):
        response.headers['Content-Type'] = 'text/css; charset=utf-8'
    elif filename.endswith('.js'):
        response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    elif filename.endswith('.png'):
        response.headers['Content-Type'] = 'image/png'
    elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
        response.headers['Content-Type'] = 'image/jpeg'
    elif filename.endswith('.gif'):
        response.headers['Content-Type'] = 'image/gif'
    elif filename.endswith('.svg'):
        response.headers['Content-Type'] = 'image/svg+xml'
    
    return response

# Static dosyalar için CORS ve cache ayarları
@app.after_request
def after_request(response):
    # CORS ayarları
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    
    # Güvenlik başlıkları
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Static dosyalar için cache ayarları
    if request.endpoint == 'static':
        response.headers['Cache-Control'] = 'public, max-age=3600'
        response.headers['Vary'] = 'Accept-Encoding'
        # LocalTunnel için özel ayarlar
        response.headers['Cross-Origin-Embedder-Policy'] = 'unsafe-none'
        response.headers['Cross-Origin-Opener-Policy'] = 'unsafe-none'
        response.headers['Cross-Origin-Resource-Policy'] = 'cross-origin'
    
    return response

# Hosting için konfigürasyon
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'kemah-dogal-urunler-2025-gizli-anahtar')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Logging ayarları
if not app.debug:
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

# Uygulama uzantılarını başlat
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Bu sayfaya erişmek için giriş yapmalısınız.'

# Upload klasörünü oluştur
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Veritabanı bağlantısı - Hosting uyumlu
def get_db_connection():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kemah.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # SQLite pragma ayarları
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

# Ziyaretçi takip fonksiyonu
def track_visitor(request):
    ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', '127.0.0.1'))
    user_agent = request.headers.get('User-Agent', 'Unknown')
    page_visited = request.path
    
    conn = get_db_connection()
    
    # Aynı IP'den daha önce ziyaret var mı kontrol et
    existing_visitor = conn.execute('SELECT * FROM visitors WHERE ip_address = ?', (ip_address,)).fetchone()
    
    if existing_visitor:
        # Ziyaret sayısını artır ve son ziyaret tarihini güncelle
        conn.execute('''
            UPDATE visitors 
            SET visit_count = visit_count + 1, 
                last_visit = CURRENT_TIMESTAMP,
                page_visited = ?
            WHERE ip_address = ?
        ''', (page_visited, ip_address))
    else:
        # Yeni ziyaretçi ekle
        conn.execute('''
            INSERT INTO visitors (ip_address, user_agent, page_visited)
            VALUES (?, ?, ?)
        ''', (ip_address, user_agent, page_visited))
    
    conn.commit()
    conn.close()

def is_maintenance_mode():
    """Site bakım modunda mı kontrol et"""
    conn = get_db_connection()
    status = conn.execute('SELECT * FROM site_status ORDER BY id DESC LIMIT 1').fetchone()
    conn.close()
    
    if status:
        return bool(status['is_maintenance_mode'])
    return False

def get_maintenance_message():
    """Bakım modu mesajını al"""
    conn = get_db_connection()
    status = conn.execute('SELECT * FROM site_status ORDER BY id DESC LIMIT 1').fetchone()
    conn.close()
    
    if status:
        return status['maintenance_message']
    return 'Site bakımda. Lütfen daha sonra tekrar deneyin.'

def set_maintenance_mode(is_maintenance, message=None):
    """Bakım modunu ayarla"""
    conn = get_db_connection()
    
    if message is None:
        message = 'Site bakımda. Lütfen daha sonra tekrar deneyin.'
    
    if is_maintenance:
        conn.execute('''
            UPDATE site_status 
            SET is_maintenance_mode = 1, 
                maintenance_message = ?,
                maintenance_started_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
        ''', (message,))
    else:
        conn.execute('''
            UPDATE site_status 
            SET is_maintenance_mode = 0, 
                maintenance_ended_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
        ''')
    
    conn.commit()
    conn.close()

def maintenance_required(f):
    """Bakım modu kontrolü decorator'ı"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Admin giriş sayfası ve admin paneli bakım modunda da çalışsın
        if request.endpoint in ['login', 'admin_dashboard', 'admin_settings', 'admin_maintenance']:
            return f(*args, **kwargs)
        
        # Bakım modu aktifse bakım sayfasını göster
        if is_maintenance_mode():
            return render_template('maintenance.html', 
                                 maintenance_message=get_maintenance_message())
        
        return f(*args, **kwargs)
    return decorated_function

# Basit User sınıfı
class User(UserMixin):
    def __init__(self, id, username, email, password, first_name, last_name, phone=None, address=None, is_admin=False):
        self.id = id
        self.username = username
        self.email = email
        self.password = password
        self.first_name = first_name
        self.last_name = last_name
        self.phone = phone
        self.address = address
        self.is_admin = is_admin

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    user_data = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    
    if user_data:
        return User(
            id=user_data['id'],
            username=user_data['username'],
            email=user_data['email'],
            password=user_data['password'],
            first_name=user_data['first_name'],
            last_name=user_data['last_name'],
            phone=user_data['phone'],
            address=user_data['address'],
            is_admin=bool(user_data['is_admin'])
        )
    return None

# Context Processor - Her template'de kullanılabilir değişkenler
@app.context_processor
def inject_user():
    return dict(current_user=current_user)

# Site ayarları fonksiyonu
def get_site_settings():
    try:
        conn = get_db_connection()
        settings = conn.execute('SELECT * FROM site_settings').fetchall()
        conn.close()
        
        # Ayarları dictionary'ye çevir
        site_settings = {setting['setting_key']: setting['setting_value'] for setting in settings}
        return site_settings
    except:
        return {}

# Site ayarları context processor
@app.context_processor
def inject_site_settings():
    return dict(site_settings=get_site_settings())

# E-posta gönderme fonksiyonu (Gerçek SMTP)
def send_email(to_email, subject, message, sender_name, sender_email):
    try:
        # Site ayarlarından admin e-postasını al
        conn = get_db_connection()
        admin_email = conn.execute('SELECT setting_value FROM site_settings WHERE setting_key = ?', ('site_email',)).fetchone()
        conn.close()
        
        if not admin_email:
            return False, "Admin e-posta adresi bulunamadı"
        
        admin_email = admin_email['setting_value']
        
        # E-posta ayarları (Site ayarlarından al)
        conn = get_db_connection()
        smtp_settings = conn.execute('''
            SELECT setting_key, setting_value FROM site_settings 
            WHERE setting_key IN ('smtp_email', 'smtp_password', 'smtp_server', 'smtp_port')
        ''').fetchall()
        conn.close()
        
        # SMTP ayarlarını dictionary'ye çevir
        smtp_config = {setting['setting_key']: setting['setting_value'] for setting in smtp_settings}
        
        smtp_email = smtp_config.get('smtp_email', '')
        smtp_password = smtp_config.get('smtp_password', '')
        smtp_server = smtp_config.get('smtp_server', 'smtp.gmail.com')
        smtp_port = int(smtp_config.get('smtp_port', '587'))
        
        # SMTP ayarları kontrolü
        if not smtp_email or not smtp_password:
            return False, "E-posta gönderebilmek için SMTP ayarlarını yapılandırın (Admin Ayarları)"
        
        # E-posta içeriği
        email_subject = f"İletişim Formu: {subject or 'Konu belirtilmemiş'}"
        
        # E-posta gövdesi
        body = f"""Yeni bir iletişim formu mesajı alındı:

Gönderen: {sender_name}
E-posta: {sender_email}
Konu: {subject or 'Konu belirtilmemiş'}

Mesaj:
{message}

---
Bu mesaj {datetime.now().strftime('%d.%m.%Y %H:%M')} tarihinde gönderilmiştir.
IP Adresi: {request.remote_addr if request else 'Bilinmiyor'}
"""
        
        # E-posta oluştur
        msg = MIMEMultipart()
        msg['From'] = smtp_email
        msg['To'] = admin_email
        msg['Subject'] = email_subject
        msg['Reply-To'] = sender_email
        
        # E-posta gövdesini ekle
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # SMTP sunucusuna bağlan ve e-posta gönder
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()  # TLS şifreleme
        server.login(smtp_email, smtp_password)
        
        # E-postayı gönder
        text = msg.as_string()
        server.sendmail(smtp_email, admin_email, text)
        server.quit()
        
        # Log'a yaz
        print("=" * 50)
        print("E-POSTA BAŞARIYLA GÖNDERİLDİ")
        print("=" * 50)
        print(f"Admin E-posta: {admin_email}")
        print(f"Konu: {email_subject}")
        print(f"Gönderen: {sender_name} ({sender_email})")
        print(f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        print("=" * 50)
        
        return True, "Mesajınız başarıyla gönderildi! En kısa sürede size dönüş yapacağız."
        
    except smtplib.SMTPAuthenticationError:
        print("SMTP kimlik doğrulama hatası! E-posta ve şifre kontrol edin.")
        return False, "E-posta gönderilemedi: Kimlik doğrulama hatası"
    except smtplib.SMTPException as e:
        print(f"SMTP hatası: {str(e)}")
        return False, f"E-posta gönderilemedi: {str(e)}"
    except Exception as e:
        print(f"E-posta gönderme hatası: {str(e)}")
        return False, f"E-posta gönderilemedi: {str(e)}"

# Şifre sıfırlama e-posta gönderme fonksiyonu
def send_password_reset_email(user_email, reset_token, user_name):
    try:
        # SMTP ayarlarını al
        conn = get_db_connection()
        smtp_settings = conn.execute('''
            SELECT setting_key, setting_value FROM site_settings 
            WHERE setting_key IN ('smtp_email', 'smtp_password', 'smtp_server', 'smtp_port', 'site_title')
        ''').fetchall()
        conn.close()
        
        # SMTP ayarlarını dictionary'ye çevir
        smtp_config = {setting['setting_key']: setting['setting_value'] for setting in smtp_settings}
        
        smtp_email = smtp_config.get('smtp_email', '')
        smtp_password = smtp_config.get('smtp_password', '')
        smtp_server = smtp_config.get('smtp_server', 'smtp.gmail.com')
        smtp_port = int(smtp_config.get('smtp_port', '587'))
        site_title = smtp_config.get('site_title', 'Kemah Doğal Ürünler')
        
        # SMTP ayarları kontrolü
        if not smtp_email or not smtp_password:
            return False, "E-posta gönderebilmek için SMTP ayarlarını yapılandırın (Admin Ayarları)"
        
        # Şifre sıfırlama linki
        reset_link = f"http://localhost:5000/reset-password/{reset_token}"
        
        # E-posta içeriği
        subject = f"{site_title} - Şifre Sıfırlama"
        
        # HTML e-posta gövdesi
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; background: #28a745; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{site_title}</h1>
                    <p>Şifre Sıfırlama Talebi</p>
                </div>
                <div class="content">
                    <h2>Merhaba {user_name},</h2>
                    <p>Hesabınız için şifre sıfırlama talebinde bulundunuz. Şifrenizi sıfırlamak için aşağıdaki butona tıklayın:</p>
                    
                    <div style="text-align: center;">
                        <a href="{reset_link}" class="button">Şifremi Sıfırla</a>
                    </div>
                    
                    <p><strong>Önemli:</strong></p>
                    <ul>
                        <li>Bu link 1 saat geçerlidir</li>
                        <li>Link sadece bir kez kullanılabilir</li>
                        <li>Eğer bu talebi siz yapmadıysanız, bu e-postayı görmezden gelebilirsiniz</li>
                    </ul>
                    
                    <p>Eğer buton çalışmıyorsa, aşağıdaki linki kopyalayıp tarayıcınıza yapıştırın:</p>
                    <p style="word-break: break-all; background: #e9ecef; padding: 10px; border-radius: 5px;">{reset_link}</p>
                </div>
                <div class="footer">
                    <p>Bu e-posta otomatik olarak gönderilmiştir. Lütfen yanıtlamayın.</p>
                    <p>&copy; 2024 {site_title}. Tüm hakları saklıdır.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # E-posta oluştur
        msg = MIMEMultipart('alternative')
        msg['From'] = smtp_email
        msg['To'] = user_email
        msg['Subject'] = subject
        
        # HTML ve plain text versiyonları
        html_part = MIMEText(html_body, 'html', 'utf-8')
        msg.attach(html_part)
        
        # SMTP sunucusuna bağlan ve e-posta gönder
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_email, smtp_password)
        
        # E-postayı gönder
        text = msg.as_string()
        server.sendmail(smtp_email, user_email, text)
        server.quit()
        
        print("ŞİFRE SIFIRLAMA E-POSTASI BAŞARIYLA GÖNDERİLDİ")
        print("=" * 50)
        print(f"Alıcı: {user_email}")
        print(f"Konu: {subject}")
        print(f"Token: {reset_token}")
        print(f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        print("=" * 50)
        
        return True, "Şifre sıfırlama e-postası gönderildi!"
        
    except smtplib.SMTPAuthenticationError:
        print("SMTP kimlik doğrulama hatası! E-posta ve şifre kontrol edin.")
        return False, "E-posta gönderilemedi: Kimlik doğrulama hatası"
    except smtplib.SMTPException as e:
        print(f"SMTP hatası: {str(e)}")
        return False, f"E-posta gönderilemedi: {str(e)}"
    except Exception as e:
        print(f"Şifre sıfırlama e-postası gönderme hatası: {str(e)}")
        return False, f"E-posta gönderilemedi: {str(e)}"

# Veritabanını başlat - GÜNCEL ŞEMA
def init_db():
    conn = get_db_connection()
    
    # Tabloları oluştur
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            ip_address TEXT,
            is_admin BOOLEAN DEFAULT 0,
            cookie_consent TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            user_agent TEXT,
            page_visited TEXT,
            visit_count INTEGER DEFAULT 1,
            first_visit TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_visit TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cookie_consent TEXT DEFAULT 'pending',
            is_blocked BOOLEAN DEFAULT 0,
            blocked_reason TEXT,
            blocked_at TIMESTAMP
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS site_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            is_maintenance_mode BOOLEAN DEFAULT 0,
            maintenance_message TEXT DEFAULT 'Site bakımda. Lütfen daha sonra tekrar deneyin.',
            maintenance_started_at TIMESTAMP,
            maintenance_ended_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            description TEXT,
            parent_id INTEGER,
            image TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL,
            description TEXT,
            short_description TEXT,
            price REAL NOT NULL,
            stock_quantity INTEGER DEFAULT 0,
            image TEXT,
            weight TEXT,
            brand TEXT,
            is_active BOOLEAN DEFAULT 1,
            is_featured BOOLEAN DEFAULT 0,
            is_new BOOLEAN DEFAULT 0,
            category_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            user_id INTEGER,
            total_amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            payment_status TEXT DEFAULT 'pending',
            shipping_address TEXT NOT NULL,
            billing_address TEXT,
            phone TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            total REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS blogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            excerpt TEXT,
            image TEXT,
            is_published BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Blog yazıları tablosu (admin paneli için)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS blog_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blog_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            excerpt TEXT,
            author TEXT NOT NULL,
            image TEXT,
            slug TEXT,
            is_published BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Eksik sütunları ekle (eğer yoksa)
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN excerpt TEXT')
    except:
        pass
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN slug TEXT')
    except:
        pass
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN is_published BOOLEAN DEFAULT 1')
    except:
        pass
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN blog_author_name TEXT')
    except:
        pass
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN blog_author_title TEXT')
    except:
        pass
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN blog_author_avatar TEXT')
    except:
        pass
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN blog_tags TEXT')
    except:
        pass
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN blog_features TEXT')
    except:
        pass
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN sidebar_title TEXT')
    except:
        pass
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN sidebar_description TEXT')
    except:
        pass
    
    
    # Blog resimleri tablosu (çoklu resim desteği için)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS blog_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blog_post_id INTEGER NOT NULL,
            image_filename TEXT NOT NULL,
            is_primary BOOLEAN DEFAULT 0,
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (blog_post_id) REFERENCES blog_posts (id) ON DELETE CASCADE
        )
    ''')
    
    # Blog etiketleri tablosu
    conn.execute('''
        CREATE TABLE IF NOT EXISTS blog_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            color TEXT DEFAULT 'bg-primary',
            description TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Blog özellikleri tablosu
    conn.execute('''
        CREATE TABLE IF NOT EXISTS blog_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            icon TEXT DEFAULT 'fas fa-check',
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Varsayılan etiketleri ekle
    default_tags = [
        ('Doğal Ürünler', 'bg-primary', 'Doğal ve organik ürünler hakkında'),
        ('Sağlık', 'bg-success', 'Sağlık ve beslenme konuları'),
        ('Beslenme', 'bg-info', 'Beslenme ve diyet önerileri'),
        ('Organik', 'bg-warning', 'Organik ürünler ve yaşam'),
        ('Yaşam', 'bg-secondary', 'Genel yaşam önerileri'),
        ('Tarifler', 'bg-danger', 'Yemek tarifleri ve reçeteler'),
        ('İpuçları', 'bg-dark', 'Pratik yaşam ipuçları')
    ]
    
    for tag in default_tags:
        existing = conn.execute('SELECT id FROM blog_tags WHERE name = ?', (tag[0],)).fetchone()
        if not existing:
            conn.execute('''
                INSERT INTO blog_tags (name, color, description)
                VALUES (?, ?, ?)
            ''', tag)
    
    # Varsayılan özellikleri ekle
    default_features = [
        ('100% Doğal İçerik', 'Doğal ve organik içerikler', 'fas fa-leaf'),
        ('Uzman Yazarlar', 'Alanında uzman yazarlar', 'fas fa-user-graduate'),
        ('Güncel Bilgiler', 'En güncel bilgi ve araştırmalar', 'fas fa-clock'),
        ('Detaylı Açıklamalar', 'Kapsamlı ve detaylı açıklamalar', 'fas fa-info-circle'),
        ('Bilimsel Kaynaklar', 'Bilimsel araştırmalara dayalı', 'fas fa-microscope'),
        ('Pratik Öneriler', 'Günlük hayatta uygulanabilir', 'fas fa-lightbulb'),
        ('Güvenilir Kaynak', 'Güvenilir ve doğrulanmış bilgiler', 'fas fa-shield-alt')
    ]
    
    for feature in default_features:
        existing = conn.execute('SELECT id FROM blog_features WHERE name = ?', (feature[0],)).fetchone()
        if not existing:
            conn.execute('''
                INSERT INTO blog_features (name, description, icon)
                VALUES (?, ?, ?)
            ''', feature)
    
    # Ürün resimleri tablosu
    conn.execute('''
        CREATE TABLE IF NOT EXISTS product_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            image_filename TEXT NOT NULL,
            is_primary BOOLEAN DEFAULT 0,
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
        )
    ''')
    
    # Admin kullanıcı oluştur - Environment variables'dan
    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_email = os.environ.get('ADMIN_EMAIL', 'admin@kemah.com.tr')
    admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
    
    admin_user = conn.execute('SELECT * FROM users WHERE username = ?', (admin_username,)).fetchone()
    if not admin_user:
        hashed_password = bcrypt.generate_password_hash(admin_password).decode('utf-8')
        conn.execute('''
            INSERT INTO users (username, email, password, first_name, last_name, is_admin)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (admin_username, admin_email, hashed_password, 'Admin', 'User', 1))
    
    # Test kullanıcısı oluştur - KALDIRILDI
    # test_username = os.environ.get('TEST_USERNAME', 'test')
    # test_email = os.environ.get('TEST_EMAIL', 'test@kemah.com.tr')
    # test_password = os.environ.get('TEST_PASSWORD', 'test123')
    
    # test_user = conn.execute('SELECT * FROM users WHERE username = ?', (test_username,)).fetchone()
    # if not test_user:
    #     hashed_password = bcrypt.generate_password_hash(test_password).decode('utf-8')
    #     conn.execute('''
    #         INSERT INTO users (username, email, password, first_name, last_name, is_admin)
    #         VALUES (?, ?, ?, ?, ?, ?)
    #     ''', (test_username, test_email, hashed_password, 'Test', 'User', 0))
    
    # Kategoriler zaten veritabanında mevcut
    
    # Ürünler zaten veritabanında mevcut
    
    # Blog yazıları zaten veritabanında mevcut
    
    # Mevcut tablolara cookie_consent sütunu ekle (eğer yoksa)
    try:
        conn.execute('ALTER TABLE users ADD COLUMN cookie_consent TEXT DEFAULT "pending"')
        print("Users tablosuna cookie_consent sütunu eklendi")
    except:
        print("Users tablosunda cookie_consent sütunu zaten mevcut")
    
    try:
        conn.execute('ALTER TABLE visitors ADD COLUMN cookie_consent TEXT DEFAULT "pending"')
        print("Visitors tablosuna cookie_consent sütunu eklendi")
    except:
        print("Visitors tablosunda cookie_consent sütunu zaten mevcut")
    
    try:
        conn.execute('ALTER TABLE visitors ADD COLUMN is_blocked BOOLEAN DEFAULT 0')
        print("Visitors tablosuna is_blocked sütunu eklendi")
    except:
        print("Visitors tablosunda is_blocked sütunu zaten mevcut")
    
    try:
        conn.execute('ALTER TABLE visitors ADD COLUMN blocked_reason TEXT')
        print("Visitors tablosuna blocked_reason sütunu eklendi")
    except:
        print("Visitors tablosunda blocked_reason sütunu zaten mevcut")
    
    try:
        conn.execute('ALTER TABLE visitors ADD COLUMN blocked_at TIMESTAMP')
        print("Visitors tablosuna blocked_at sütunu eklendi")
    except:
        print("Visitors tablosunda blocked_at sütunu zaten mevcut")
    
    # Orders tablosunda user_id'yi NULL yapabilmek için güncelleme
    try:
        # SQLite'da ALTER COLUMN desteklenmediği için yeni tablo oluşturup verileri taşı
        conn.execute('''
            CREATE TABLE orders_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT UNIQUE NOT NULL,
                user_id INTEGER,
                total_amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                payment_status TEXT DEFAULT 'pending',
                shipping_address TEXT NOT NULL,
                billing_address TEXT,
                phone TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Mevcut verileri yeni tabloya kopyala
        conn.execute('''
            INSERT INTO orders_new (id, order_number, user_id, total_amount, status, 
                                  payment_status, shipping_address, billing_address, 
                                  phone, notes, created_at, updated_at)
            SELECT id, order_number, user_id, total_amount, status, 
                   payment_status, shipping_address, billing_address, 
                   phone, notes, created_at, updated_at
            FROM orders
        ''')
        
        # Eski tabloyu sil ve yeni tabloyu yeniden adlandır
        conn.execute('DROP TABLE orders')
        conn.execute('ALTER TABLE orders_new RENAME TO orders')
        
        print("Orders tablosu misafir kullanıcılar için güncellendi")
    except Exception as e:
        print(f"Orders tablosu güncellenirken hata: {e}")
        # Hata durumunda yeni tabloyu sil
        try:
            conn.execute('DROP TABLE IF EXISTS orders_new')
        except:
            pass
    
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN image TEXT')
        print("Blog_posts tablosuna image sütunu eklendi")
    except:
        print("Blog_posts tablosunda image sütunu zaten mevcut")
    
    # Blog_posts tablosunda blog_id sütunu ekle
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN blog_id TEXT')
        print("Blog_posts tablosuna blog_id sütunu eklendi")
    except:
        print("Blog_posts tablosunda blog_id sütunu zaten mevcut")
    
    # Blog_posts tablosuna excerpt sütunu ekle
    try:
        conn.execute('ALTER TABLE blog_posts ADD COLUMN excerpt TEXT')
        print("Blog_posts tablosuna excerpt sütunu eklendi")
    except:
        print("Blog_posts tablosunda excerpt sütunu zaten mevcut")
    
    # Mevcut blog yazılarına blog_id ekle
    import uuid
    existing_blogs = conn.execute('SELECT id FROM blog_posts WHERE blog_id IS NULL').fetchall()
    for blog in existing_blogs:
        blog_id = f"BLOG_{str(uuid.uuid4())[:8].upper()}"
        conn.execute('UPDATE blog_posts SET blog_id = ? WHERE id = ?', (blog_id, blog['id']))
    if existing_blogs:
        print(f"{len(existing_blogs)} blog yazısına blog_id eklendi")
    
    # Çerez verilerini sıfırla (test için) - KAPALI
    # conn.execute('UPDATE users SET cookie_consent = "pending"')
    # conn.execute('UPDATE visitors SET cookie_consent = "pending"')
    # print("Tüm çerez verileri sıfırlandı - test için")
    
    # Test kullanıcısını sil
    conn.execute('DELETE FROM users WHERE username = "test"')
    print("Test kullanıcısı silindi")
    
    # Site durumu tablosuna varsayılan veri ekle
    existing_status = conn.execute('SELECT * FROM site_status').fetchone()
    if not existing_status:
        conn.execute('''
            INSERT INTO site_status (is_maintenance_mode, maintenance_message, updated_at)
            VALUES (0, 'Site bakımda. Lütfen daha sonra tekrar deneyin.', CURRENT_TIMESTAMP)
        ''')
        print("Site durumu tablosuna varsayılan veri eklendi")
    
    # Site ayarları tablosu oluştur
    conn.execute('''
        CREATE TABLE IF NOT EXISTS site_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_key TEXT UNIQUE NOT NULL,
            setting_value TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # İletişim mesajları tablosu - E-posta gönderme kullanıldığı için kaldırıldı
    # conn.execute('''
    #     CREATE TABLE IF NOT EXISTS contact_messages (
    #         id INTEGER PRIMARY KEY AUTOINCREMENT,
    #         name TEXT NOT NULL,
    #         email TEXT NOT NULL,
    #         subject TEXT,
    #         message TEXT NOT NULL,
    #         ip_address TEXT,
    #         is_read BOOLEAN DEFAULT 0,
    #         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    #     )
    # ''')
    
    # Şifre sıfırlama token tablosu
    conn.execute('''
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')
    
    # Varsayılan site ayarlarını ekle
    default_settings = [
        ('site_email', 'info@kemah.com.tr', 'Site e-posta adresi'),
        ('site_phone', '+90 555 123 45 67', 'Site telefon numarası'),
        ('site_address', 'Kemah, Erzincan, Türkiye', 'Site adresi'),
        ('facebook_url', 'https://facebook.com/kemah', 'Facebook sayfası'),
        ('instagram_url', 'https://instagram.com/kemah', 'Instagram sayfası'),
        ('twitter_url', 'https://twitter.com/kemah', 'Twitter sayfası'),
        ('youtube_url', 'https://youtube.com/kemah', 'YouTube kanalı'),
        ('linkedin_url', 'https://linkedin.com/company/kemah', 'LinkedIn sayfası'),
        ('whatsapp_url', 'https://wa.me/905551234567', 'WhatsApp numarası'),
        ('site_title', 'Kemah - Erzincan', 'Site başlığı'),
        ('site_description', 'Kemah ilçesi resmi web sitesi', 'Site açıklaması'),
        ('smtp_email', '', 'SMTP e-posta adresi'),
        ('smtp_password', '', 'SMTP şifre'),
        ('smtp_server', 'smtp.gmail.com', 'SMTP sunucu'),
        ('smtp_port', '587', 'SMTP port')
    ]
    
    for key, value, description in default_settings:
        conn.execute('''
            INSERT OR IGNORE INTO site_settings (setting_key, setting_value, description)
            VALUES (?, ?, ?)
        ''', (key, value, description))
    
    print("Site ayarları tablosu oluşturuldu ve varsayılan değerler eklendi")
    
    conn.commit()
    conn.close()
    print("Veritabanı başarıyla oluşturuldu!")

# Ana Sayfa
@app.route('/')
@maintenance_required
def index():
    # Ziyaretçi takibi
    track_visitor(request)
    
    conn = get_db_connection()
    
    # Öne çıkan ürünler
    featured_products = conn.execute('''
        SELECT p.*, c.name as category_name,
               CASE 
                   WHEN p.is_new = 1 OR datetime(p.created_at) > datetime('now', '-30 days') THEN 1 
                   ELSE 0 
               END as is_new
        FROM products p 
        JOIN categories c ON p.category_id = c.id 
        WHERE p.is_featured = 1 AND p.is_active = 1 
        LIMIT 8
    ''').fetchall()
    
    # Kategoriler
    categories = conn.execute('''
        SELECT * FROM categories 
        WHERE is_active = 1 AND parent_id IS NULL
    ''').fetchall()
    
    # Yeni ürünler
    recent_products = conn.execute('''
        SELECT p.*, c.name as category_name,
               CASE 
                   WHEN p.is_new = 1 OR datetime(p.created_at) > datetime('now', '-30 days') THEN 1 
                   ELSE 0 
               END as is_new
        FROM products p 
        JOIN categories c ON p.category_id = c.id 
        WHERE p.is_active = 1 
        ORDER BY p.created_at DESC 
        LIMIT 6
    ''').fetchall()
    
    # Rastgele ürünler (reklamlar için)
    random_products = conn.execute('''
        SELECT p.*, c.name as category_name,
               CASE 
                   WHEN p.is_new = 1 OR datetime(p.created_at) > datetime('now', '-30 days') THEN 1 
                   ELSE 0 
               END as is_new
        FROM products p 
        JOIN categories c ON p.category_id = c.id 
        WHERE p.is_active = 1 
        ORDER BY RANDOM() 
        LIMIT 6
    ''').fetchall()
    
    # Blog yazıları (admin panelinden eklenen) - çoklu resim desteği ile
    blog_posts = conn.execute('''
        SELECT bp.id, bp.blog_id, bp.title, bp.content, bp.author, bp.created_at, bp.updated_at,
               CASE WHEN LENGTH(bp.content) > 150 THEN SUBSTR(bp.content, 1, 150) || '...' ELSE bp.content END as excerpt,
               bi.image_filename as primary_image
        FROM blog_posts bp
        LEFT JOIN blog_images bi ON bp.id = bi.blog_post_id AND bi.is_primary = 1
        WHERE bp.is_published IS NULL OR bp.is_published = 1
        ORDER BY bp.created_at DESC
    ''').fetchall()
    
    conn.close()
    
    return render_template('index.html', 
                         featured_products=featured_products,
                         categories=categories,
                         recent_products=recent_products,
                         random_products=random_products,
                         blog_posts=blog_posts,
                         site_settings=get_site_settings())

# Arama Sayfası
@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    results = []
    
    if query:
        conn = get_db_connection()
        
        # Ürünlerde arama
        products = conn.execute('''
            SELECT p.*, c.name as category_name
            FROM products p 
            JOIN categories c ON p.category_id = c.id 
            WHERE (p.name LIKE ? OR p.description LIKE ? OR p.short_description LIKE ?) 
            AND p.is_active = 1
            ORDER BY p.name
        ''', (f'%{query}%', f'%{query}%', f'%{query}%')).fetchall()
        
        # Kategorilerde arama
        categories = conn.execute('''
            SELECT * FROM categories 
            WHERE name LIKE ? OR description LIKE ?
            ORDER BY name
        ''', (f'%{query}%', f'%{query}%')).fetchall()
        
        conn.close()
        
        results = {
            'products': products,
            'categories': categories
        }
    
    return render_template('search.html', query=query, results=results)

# Kullanıcı Kayıt
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        
        # Form verilerini al
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        
        # Validasyon
        if not all([username, email, password, first_name, last_name]):
            flash('Tüm zorunlu alanları doldurun!', 'error')
            return render_template('register.html')
        
        # Terms checkbox kontrolü
        if not request.form.get('terms'):
            flash('Kullanım şartlarını kabul etmelisiniz!', 'error')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Şifreler eşleşmiyor!', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Şifre en az 6 karakter olmalıdır!', 'error')
            return render_template('register.html')
        
        # E-posta formatını kontrol et
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            flash('Geçerli bir e-posta adresi girin!', 'error')
            return render_template('register.html')
        
        conn = get_db_connection()
        
        # Kullanıcı var mı kontrol et
        existing_user = conn.execute('SELECT * FROM users WHERE username = ? OR email = ?', (username, email)).fetchone()
        
        if existing_user:
            flash('Bu kullanıcı adı veya e-posta adresi zaten kullanılıyor!', 'error')
            conn.close()
            return render_template('register.html')
        
        # Yeni kullanıcı oluştur
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'Unknown'))
        conn.execute('''
            INSERT INTO users (username, email, password, first_name, last_name, phone, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (username, email, hashed_password, first_name, last_name, phone, ip_address))
        
        conn.commit()
        conn.close()
        
        flash('Kayıt başarılı! Giriş yapabilirsiniz.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

# Kullanıcı Giriş
@app.route('/giris', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        remember = request.form.get('remember') == 'on'
        
        # Environment variables'dan admin bilgilerini al
        admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
        admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
        admin_email = os.environ.get('ADMIN_EMAIL', 'admin@kemah.com.tr')
        
        # Environment variables'dan test kullanıcı bilgilerini al - KALDIRILDI
        # test_username = os.environ.get('TEST_USERNAME', 'test')
        # test_password = os.environ.get('TEST_PASSWORD', 'test123')
        # test_email = os.environ.get('TEST_EMAIL', 'test@kemah.com.tr')
        
        # Admin girişi
        if username == admin_username and password == admin_password:
            # IP adresini güncelle
            ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', '127.0.0.1'))
            conn = get_db_connection()
            conn.execute('UPDATE users SET ip_address = ? WHERE username = ?', (ip_address, username))
            conn.commit()
            conn.close()
            
            user = User(
                id=1,
                username=admin_username,
                email=admin_email,
                password=admin_password,
                first_name='Admin',
                last_name='User',
                phone=None,
                address=None,
                is_admin=True
            )
            login_user(user, remember=remember)
            flash('Admin olarak giriş yapıldı!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('admin_dashboard'))
        
        # Test kullanıcısı - KALDIRILDI
        # elif username == test_username and password == test_password:
        #     # IP adresini güncelle
        #     ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', '127.0.0.1'))
        #     conn = get_db_connection()
        #     conn.execute('UPDATE users SET ip_address = ? WHERE username = ?', (ip_address, username))
        #     conn.commit()
        #     conn.close()
        #     
        #     user = User(
        #         id=2,
        #         username=test_username,
        #         email=test_email,
        #         password=test_password,
        #         first_name='Test',
        #         last_name='User',
        #         phone=None,
        #         address=None,
        #         is_admin=False
        #     )
        #     login_user(user, remember=remember)
        #     flash('Test kullanıcısı olarak giriş yapıldı!', 'success')
        #     next_page = request.args.get('next')
        #     return redirect(next_page) if next_page else redirect(url_for('index'))
        
        else:
            # Veritabanından kullanıcı kontrolü
            conn = get_db_connection()
            user_data = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            
            if user_data and bcrypt.check_password_hash(user_data['password'], password):
                # IP adresini güncelle
                ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', '127.0.0.1'))
                conn.execute('UPDATE users SET ip_address = ? WHERE id = ?', (ip_address, user_data['id']))
                conn.commit()
                
                user = User(
                    id=user_data['id'],
                    username=user_data['username'],
                    email=user_data['email'],
                    password=user_data['password'],
                    first_name=user_data['first_name'],
                    last_name=user_data['last_name'],
                    phone=user_data['phone'],
                    address=user_data['address'],
                    is_admin=bool(user_data['is_admin'])
                )
                login_user(user, remember=remember)
                flash('Giriş başarılı!', 'success')
                next_page = request.args.get('next')
                conn.close()
                return redirect(next_page) if next_page else redirect(url_for('index'))
            else:
                flash('Kullanıcı adı veya şifre hatalı!', 'error')
            
            conn.close()
    
    return render_template('login.html')

# Kullanıcı Profil Sayfası
@app.route('/profil')
@login_required
def profile():
    return render_template('profile.html', user=current_user)

# Kullanıcı Profil Güncelleme
@app.route('/profil/guncelle', methods=['GET', 'POST'])
@login_required
def update_profile():
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        
        if not all([first_name, last_name, email]):
            flash('Ad, soyad ve e-posta alanları zorunludur!', 'error')
            return redirect(url_for('update_profile'))
        
        # E-posta formatını kontrol et
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            flash('Geçerli bir e-posta adresi girin!', 'error')
            return redirect(url_for('update_profile'))
        
        conn = get_db_connection()
        
        # E-posta başka kullanıcıda var mı kontrol et
        existing_user = conn.execute('SELECT * FROM users WHERE email = ? AND id != ?', (email, current_user.id)).fetchone()
        if existing_user:
            flash('Bu e-posta adresi başka bir kullanıcı tarafından kullanılıyor!', 'error')
            conn.close()
            return redirect(url_for('update_profile'))
        
        # Kullanıcı bilgilerini güncelle
        conn.execute('''
            UPDATE users 
            SET first_name = ?, last_name = ?, email = ?, phone = ?, address = ?
            WHERE id = ?
        ''', (first_name, last_name, email, phone, address, current_user.id))
        
        conn.commit()
        conn.close()
        
        flash('Profil bilgileriniz başarıyla güncellendi!', 'success')
        return redirect(url_for('profile'))
    
    return render_template('update_profile.html', user=current_user)

# Şifre Değiştirme
@app.route('/profil/sifre-degistir', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        if not all([current_password, new_password, confirm_password]):
            flash('Tüm alanları doldurun!', 'error')
            return redirect(url_for('change_password'))
        
        if new_password != confirm_password:
            flash('Yeni şifreler eşleşmiyor!', 'error')
            return redirect(url_for('change_password'))
        
        if len(new_password) < 6:
            flash('Yeni şifre en az 6 karakter olmalıdır!', 'error')
            return redirect(url_for('change_password'))
        
        conn = get_db_connection()
        user_data = conn.execute('SELECT * FROM users WHERE id = ?', (current_user.id,)).fetchone()
        
        if not bcrypt.check_password_hash(user_data['password'], current_password):
            flash('Mevcut şifre hatalı!', 'error')
            conn.close()
            return redirect(url_for('change_password'))
        
        # Yeni şifreyi hash'le ve güncelle
        hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
        conn.execute('UPDATE users SET password = ? WHERE id = ?', (hashed_password, current_user.id))
        
        conn.commit()
        conn.close()
        
        flash('Şifreniz başarıyla değiştirildi!', 'success')
        return redirect(url_for('profile'))
    
    return render_template('change_password.html')

# Şifre sıfırlama talebi
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        
        if not email:
            flash('E-posta adresi gerekli!', 'error')
            return render_template('forgot_password.html')
        
        # E-posta formatını kontrol et
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            flash('Geçerli bir e-posta adresi girin!', 'error')
            return render_template('forgot_password.html')
        
        # Kullanıcıyı bul
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        
        if not user:
            flash('Bu e-posta adresi ile kayıtlı kullanıcı bulunamadı!', 'error')
            conn.close()
            return render_template('forgot_password.html')
        
        # Eski token'ları temizle
        conn.execute('DELETE FROM password_reset_tokens WHERE user_id = ?', (user['id'],))
        
        # Yeni token oluştur
        import secrets
        import datetime
        reset_token = secrets.token_urlsafe(32)
        expires_at = datetime.datetime.now() + datetime.timedelta(hours=1)
        
        # Token'ı veritabanına kaydet
        conn.execute('''
            INSERT INTO password_reset_tokens (user_id, token, expires_at)
            VALUES (?, ?, ?)
        ''', (user['id'], reset_token, expires_at))
        
        conn.commit()
        conn.close()
        
        # E-posta gönder
        success, message = send_password_reset_email(
            user['email'], 
            reset_token, 
            f"{user['first_name']} {user['last_name']}"
        )
        
        if success:
            flash('Şifre sıfırlama linki e-posta adresinize gönderildi!', 'success')
        else:
            flash(f'E-posta gönderilemedi: {message}', 'error')
        
        return render_template('forgot_password.html')
    
    return render_template('forgot_password.html')

# Şifre sıfırlama formu
@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # Token'ı kontrol et
    conn = get_db_connection()
    token_data = conn.execute('''
        SELECT prt.*, u.email, u.first_name, u.last_name
        FROM password_reset_tokens prt
        JOIN users u ON prt.user_id = u.id
        WHERE prt.token = ? AND prt.used = 0 AND prt.expires_at > datetime('now')
    ''', (token,)).fetchone()
    
    if not token_data:
        flash('Geçersiz veya süresi dolmuş şifre sıfırlama linki!', 'error')
        conn.close()
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        # Validasyon
        if not new_password or not confirm_password:
            flash('Tüm alanları doldurun!', 'error')
            return render_template('reset_password.html', token=token, user_name=f"{token_data['first_name']} {token_data['last_name']}")
        
        if len(new_password) < 6:
            flash('Şifre en az 6 karakter olmalıdır!', 'error')
            return render_template('reset_password.html', token=token, user_name=f"{token_data['first_name']} {token_data['last_name']}")
        
        if new_password != confirm_password:
            flash('Şifreler eşleşmiyor!', 'error')
            return render_template('reset_password.html', token=token, user_name=f"{token_data['first_name']} {token_data['last_name']}")
        
        # Şifreyi güncelle
        hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
        conn.execute('UPDATE users SET password = ? WHERE id = ?', (hashed_password, token_data['user_id']))
        
        # Token'ı kullanıldı olarak işaretle
        conn.execute('UPDATE password_reset_tokens SET used = 1 WHERE token = ?', (token,))
        
        conn.commit()
        conn.close()
        
        flash('Şifreniz başarıyla güncellendi! Artık yeni şifrenizle giriş yapabilirsiniz.', 'success')
        return redirect(url_for('login'))
    
    conn.close()
    return render_template('reset_password.html', token=token, user_name=f"{token_data['first_name']} {token_data['last_name']}")

# Çıkış
@app.route('/cikis')
@login_required
def logout():
    logout_user()
    flash('Başarıyla çıkış yaptınız!', 'info')
    return redirect(url_for('index'))

# Ürün Kategorileri
@app.route('/kategori/<slug>')
@maintenance_required
def category(slug):
    conn = get_db_connection()
    category = conn.execute('SELECT * FROM categories WHERE slug = ? AND is_active = 1', (slug,)).fetchone()
    
    if not category:
        flash('Kategori bulunamadı!', 'error')
        conn.close()
        return redirect(url_for('index'))
    
    products = conn.execute('''
        SELECT p.*, c.name as category_name,
               CASE 
                   WHEN p.is_new = 1 OR datetime(p.created_at) > datetime('now', '-30 days') THEN 1 
                   ELSE 0 
               END as is_new
        FROM products p 
        JOIN categories c ON p.category_id = c.id 
        WHERE p.category_id = ? AND p.is_active = 1
    ''', (category['id'],)).fetchall()
    
    # Alt kategorileri getir
    children = conn.execute('''
        SELECT * FROM categories 
        WHERE parent_id = ? AND is_active = 1
        ORDER BY name
    ''', (category['id'],)).fetchall()
    
    conn.close()
    return render_template('category.html', category=category, products=products, children=children)

# Ürün Detayı
@app.route('/urun/<slug>')
@maintenance_required
def product_detail(slug):
    conn = get_db_connection()
    product = conn.execute('''
        SELECT p.*, c.name as category_name 
        FROM products p 
        JOIN categories c ON p.category_id = c.id 
        WHERE p.slug = ? AND p.is_active = 1
    ''', (slug,)).fetchone()
    
    if not product:
        flash('Ürün bulunamadı!', 'error')
        conn.close()
        return redirect(url_for('index'))
    
    related_products = conn.execute('''
        SELECT p.*, c.name as category_name 
        FROM products p 
        JOIN categories c ON p.category_id = c.id 
        WHERE p.category_id = ? AND p.id != ? AND p.is_active = 1
        LIMIT 4
    ''', (product['category_id'], product['id'])).fetchall()
    
    # Ürün resimlerini getir
    product_images = conn.execute('''
        SELECT * FROM product_images 
        WHERE product_id = ? 
        ORDER BY is_primary DESC, display_order ASC
    ''', (product['id'],)).fetchall()
    
    conn.close()
    return render_template('product_detail.html', product=product, related_products=related_products, product_images=product_images)

# Sepet
@app.route('/sepet')
@maintenance_required
def cart():
    if current_user.is_authenticated:
        # Giriş yapmış kullanıcı için veritabanından sepet
        conn = get_db_connection()
        cart_items = conn.execute('''
            SELECT ci.*, p.name, p.price, p.image, c.name as category_name
            FROM cart_items ci
            JOIN products p ON ci.product_id = p.id
            JOIN categories c ON p.category_id = c.id
            WHERE ci.user_id = ?
        ''', (current_user.id,)).fetchall()
        conn.close()
    else:
        # Misafir kullanıcı için session'dan sepet
        cart_items = []
        session_cart = session.get('cart', {})
        
        if session_cart:
            conn = get_db_connection()
            for product_id, quantity in session_cart.items():
                product = conn.execute('''
                    SELECT p.*, c.name as category_name
                    FROM products p
                    JOIN categories c ON p.category_id = c.id
                    WHERE p.id = ?
                ''', (product_id,)).fetchone()
                
                if product:
                    # cart_items formatına uygun hale getir
                    cart_item = {
                        'id': f"session_{product_id}",
                        'product_id': product['id'],
                        'quantity': quantity,
                        'name': product['name'],
                        'price': product['price'],
                        'image': product['image'],
                        'category_name': product['category_name']
                    }
                    cart_items.append(cart_item)
            conn.close()
    
    total = sum(item['quantity'] * item['price'] for item in cart_items)
    
    return render_template('cart.html', cart_items=cart_items, total=total)

# Sepete Ekleme
@app.route('/sepet/ekle', methods=['POST'])
def add_to_cart():
    product_id = request.form.get('product_id')
    quantity = int(request.form.get('quantity', 1))
    
    conn = get_db_connection()
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    
    if not product:
        flash('Ürün bulunamadı!', 'error')
        conn.close()
        return redirect(url_for('index'))
    
    if current_user.is_authenticated:
        # Giriş yapmış kullanıcı için veritabanına ekle
        existing_item = conn.execute('''
            SELECT * FROM cart_items 
            WHERE user_id = ? AND product_id = ?
        ''', (current_user.id, product_id)).fetchone()
        
        if existing_item:
            conn.execute('''
                UPDATE cart_items 
                SET quantity = quantity + ? 
                WHERE user_id = ? AND product_id = ?
            ''', (quantity, current_user.id, product_id))
        else:
            conn.execute('''
                INSERT INTO cart_items (user_id, product_id, quantity)
                VALUES (?, ?, ?)
            ''', (current_user.id, product_id, quantity))
    
        conn.commit()
    else:
        # Misafir kullanıcı için session'a ekle
        if 'cart' not in session:
            session['cart'] = {}
        
        if product_id in session['cart']:
            session['cart'][product_id] += quantity
        else:
            session['cart'][product_id] = quantity
        
        session.modified = True
    
    conn.close()
    
    # AJAX isteği mi kontrol et
    if request.headers.get('Content-Type') == 'application/x-www-form-urlencoded' and request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        # Normal form submission - redirect yap
        flash('Ürün sepete eklendi!', 'success')
        return redirect(url_for('cart'))
    else:
        # AJAX isteği - JSON response döndür
        return jsonify({
            'success': True,
            'message': 'Ürün sepete eklendi!',
            'product_name': product['name']
        })

# Sepetten Çıkarma
@app.route('/sepet/cikar/<item_id>', methods=['POST'])
def remove_from_cart(item_id):
    if current_user.is_authenticated:
        # Giriş yapmış kullanıcı için veritabanından çıkar
        conn = get_db_connection()
        cart_item = conn.execute('''
            SELECT * FROM cart_items 
            WHERE id = ? AND user_id = ?
        ''', (item_id, current_user.id)).fetchone()
        
        if cart_item:
            conn.execute('DELETE FROM cart_items WHERE id = ?', (item_id,))
            conn.commit()
            flash('Ürün sepetten çıkarıldı!', 'info')
        
        conn.close()
    else:
        # Misafir kullanıcı için session'dan çıkar
        if item_id.startswith('session_'):
            product_id = item_id.replace('session_', '')
            if 'cart' in session and product_id in session['cart']:
                del session['cart'][product_id]
                session.modified = True
                flash('Ürün sepetten çıkarıldı!', 'info')
    
    return redirect(url_for('cart'))

# Ödeme Sayfası
@app.route('/odeme', methods=['GET', 'POST'])
def checkout():
    if request.method == 'GET':
        # Sepet bilgilerini al
        if current_user.is_authenticated:
            # Giriş yapmış kullanıcı için veritabanından sepet
            conn = get_db_connection()
            cart_items = conn.execute('''
                SELECT ci.*, p.name, p.price, p.image, c.name as category_name
                FROM cart_items ci
                JOIN products p ON ci.product_id = p.id
                JOIN categories c ON p.category_id = c.id
                WHERE ci.user_id = ?
            ''', (current_user.id,)).fetchall()
            conn.close()
        else:
            # Misafir kullanıcı için session'dan sepet
            cart_items = []
            session_cart = session.get('cart', {})
            
            if session_cart:
                conn = get_db_connection()
                for product_id, quantity in session_cart.items():
                    product = conn.execute('''
                        SELECT p.*, c.name as category_name
                        FROM products p
                        JOIN categories c ON p.category_id = c.id
                        WHERE p.id = ?
                    ''', (product_id,)).fetchone()
                    
                    if product:
                        cart_item = {
                            'id': f"session_{product_id}",
                            'product_id': product['id'],
                            'quantity': quantity,
                            'name': product['name'],
                            'price': product['price'],
                            'image': product['image'],
                            'category_name': product['category_name']
                        }
                        cart_items.append(cart_item)
                conn.close()
        
        if not cart_items:
            flash('Sepetiniz boş!', 'warning')
            return redirect(url_for('cart'))
        
        total = sum(item['quantity'] * item['price'] for item in cart_items)
        
        return render_template('checkout.html', cart_items=cart_items, total=total)
    
    elif request.method == 'POST':
        # Sipariş işleme
        try:
            # Form verilerini al
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            email = request.form.get('email')
            phone = request.form.get('phone')
            address = request.form.get('address')
            city = request.form.get('city')
            postal_code = request.form.get('postal_code')
            payment_method = request.form.get('payment_method')
            notes = request.form.get('notes', '')
            
            # Sepet bilgilerini al
            if current_user.is_authenticated:
                conn = get_db_connection()
                cart_items = conn.execute('''
                    SELECT ci.*, p.name, p.price, p.image
                    FROM cart_items ci
                    JOIN products p ON ci.product_id = p.id
                    WHERE ci.user_id = ?
                ''', (current_user.id,)).fetchall()
                user_id = current_user.id
            else:
                # Misafir kullanıcı için session'dan sepet
                cart_items = []
                session_cart = session.get('cart', {})
                
                if session_cart:
                    conn = get_db_connection()
                    for product_id, quantity in session_cart.items():
                        product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
                        if product:
                            cart_item = {
                                'product_id': product['id'],
                                'quantity': quantity,
                                'name': product['name'],
                                'price': product['price'],
                                'image': product['image']
                            }
                            cart_items.append(cart_item)
                    conn.close()
                user_id = None  # Misafir kullanıcı için user_id None
            
            if not cart_items:
                flash('Sepetiniz boş!', 'error')
                return redirect(url_for('cart'))
            
            # Sipariş numarası oluştur
            import uuid
            order_number = f"ORD-{str(uuid.uuid4())[:8].upper()}"
            
            # Toplam tutarı hesapla
            total_amount = sum(item['quantity'] * item['price'] for item in cart_items)
            
            # Adres bilgisini birleştir
            full_address = f"{address}, {city} {postal_code}"
            
            # Siparişi veritabanına kaydet
            conn = get_db_connection()
            
            # Misafir kullanıcılar için user_id NULL olacak
            cursor = conn.execute('''
                INSERT INTO orders (order_number, user_id, total_amount, status, payment_status, 
                                  shipping_address, phone, notes, first_name, last_name, email, 
                                  city, postal_code, payment_method, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ''', (order_number, user_id, total_amount, full_address, phone, notes, 
                  first_name, last_name, email, city, postal_code, payment_method))
            
            order_id = cursor.lastrowid
            
            # Sipariş öğelerini kaydet
            for item in cart_items:
                conn.execute('''
                    INSERT INTO order_items (order_id, product_id, quantity, price, total)
                    VALUES (?, ?, ?, ?, ?)
                ''', (order_id, item['product_id'], item['quantity'], item['price'], 
                      item['quantity'] * item['price']))
            
            # Giriş yapmış kullanıcı ise sepeti temizle
            if current_user.is_authenticated:
                conn.execute('DELETE FROM cart_items WHERE user_id = ?', (current_user.id,))
            else:
                # Misafir kullanıcı için session'ı temizle
                session.pop('cart', None)
                session.modified = True
            
            conn.commit()
            conn.close()
            
            flash(f'Siparişiniz başarıyla oluşturuldu! Sipariş numaranız: {order_number}', 'success')
            return redirect(url_for('order_success', order_number=order_number))
            
        except Exception as e:
            flash('Sipariş oluşturulurken bir hata oluştu!', 'error')
            print(f"Order error: {e}")
            import traceback
            traceback.print_exc()
            return redirect(url_for('checkout'))

# Müşteri Detayları API
@app.route('/api/customer/<int:customer_id>')
@login_required
def api_customer_details(customer_id):
    try:
        if not current_user.is_admin:
            return jsonify({'error': 'Unauthorized'}), 403
        
        conn = get_db_connection()
        customer = conn.execute('''
            SELECT u.*, 
                   COUNT(DISTINCT o.id) as order_count,
                   COALESCE(SUM(o.total_amount), 0) as total_spent,
                   MAX(o.created_at) as last_order_date
            FROM users u
            LEFT JOIN orders o ON u.id = o.user_id
            WHERE u.id = ?
            GROUP BY u.id
        ''', (customer_id,)).fetchone()
        
        if not customer:
            conn.close()
            return jsonify({'error': 'Customer not found'}), 404
        
        conn.close()
        
        return jsonify({
            'id': customer['id'],
            'username': customer['username'],
            'email': customer['email'],
            'first_name': customer['first_name'],
            'last_name': customer['last_name'],
            'phone': customer['phone'],
            'address': customer['address'],
            'created_at': customer['created_at'],
            'order_count': customer['order_count'],
            'total_spent': customer['total_spent'],
            'last_order_date': customer['last_order_date'],
            'is_admin': bool(customer['is_admin']),
            'ip_address': customer['ip_address'] if customer['ip_address'] else '',
            'cookie_consent': customer['cookie_consent'] if customer['cookie_consent'] else 'pending'
        })
    except Exception as e:
        print(f"API Customer Details Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500

# Sipariş Başarı Sayfası
@app.route('/siparis-basarili/<order_number>')
def order_success(order_number):
    conn = get_db_connection()
    order = conn.execute('''
        SELECT o.*, u.first_name, u.last_name, u.email
        FROM orders o
        LEFT JOIN users u ON o.user_id = u.id
        WHERE o.order_number = ?
    ''', (order_number,)).fetchone()
    
    if not order:
        flash('Sipariş bulunamadı!', 'error')
        return redirect(url_for('index'))
    
    order_items = conn.execute('''
        SELECT oi.*, p.name, p.image
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = ?
    ''', (order['id'],)).fetchall()
    
    conn.close()
    
    return render_template('order_success.html', order=order, order_items=order_items)

# Eski Blog (artık kullanılmıyor - yeni blog sistemi için /blog kullanılıyor)
@app.route('/blog-list')
def blog_list():
    conn = get_db_connection()
    blogs = conn.execute('''
        SELECT bp.id, bp.blog_id, bp.title, bp.content, bp.author, bp.created_at, bp.updated_at,
               CASE WHEN LENGTH(bp.content) > 150 THEN SUBSTR(bp.content, 1, 150) || '...' ELSE bp.content END as excerpt,
               bi.image_filename as primary_image
        FROM blog_posts bp
        LEFT JOIN blog_images bi ON bp.id = bi.blog_post_id AND bi.is_primary = 1
        WHERE (bp.is_published IS NULL OR bp.is_published = 1)
        AND bp.id IN (
            SELECT MAX(id) FROM blog_posts 
            GROUP BY blog_id
        )
        ORDER BY bp.created_at DESC
    ''').fetchall()
    conn.close()
    return render_template('blog_list.html', blogs=blogs)

@app.route('/blog/<int:post_id>')
def blog_detail(post_id):
    conn = get_db_connection()
    
    # Blog yazısını ve resimlerini getir
    blog = conn.execute('''
        SELECT bp.*, 
               (SELECT bi.image_filename FROM blog_images bi 
                WHERE bi.blog_post_id = bp.id AND bi.is_primary = 1 LIMIT 1) as primary_image
        FROM blog_posts bp 
        WHERE bp.id = ?
    ''', (post_id,)).fetchone()
    
    # Blog yazısının tüm resimlerini getir
    images = conn.execute('''
        SELECT image_filename, is_primary, display_order
        FROM blog_images 
        WHERE blog_post_id = ? 
        ORDER BY display_order
    ''', (post_id,)).fetchall()
    
    # Benzer blog yazılarını getir (aynı kategorideki diğer yazılar)
    related_blogs = conn.execute('''
        SELECT bp.*, 
               (SELECT bi.image_filename FROM blog_images bi 
                WHERE bi.blog_post_id = bp.id AND bi.is_primary = 1 LIMIT 1) as primary_image
        FROM blog_posts bp 
        WHERE bp.id != ? AND (bp.is_published IS NULL OR bp.is_published = 1)
        ORDER BY bp.created_at DESC
        LIMIT 4
    ''', (post_id,)).fetchall()
    
    # Tüm aktif etiketleri getir
    all_tags = conn.execute('''
        SELECT name, color FROM blog_tags 
        WHERE is_active = 1 
        ORDER BY name
    ''').fetchall()
    
    # Tüm aktif özellikleri getir
    all_features = conn.execute('''
        SELECT name, icon FROM blog_features 
        WHERE is_active = 1 
        ORDER BY name
    ''').fetchall()
    
    conn.close()
    
    if not blog:
        flash('Blog yazısı bulunamadı!', 'error')
        return redirect(url_for('blog'))
    
    return render_template('blog_detail.html', 
                         blog=blog, 
                         images=images, 
                         related_blogs=related_blogs,
                         all_tags=all_tags,
                         all_features=all_features)

# İletişim
@app.route('/iletisim')
def contact():
    # Site ayarlarından iletişim bilgilerini al
    conn = get_db_connection()
    settings = conn.execute('SELECT * FROM site_settings WHERE setting_key IN (?, ?, ?)', 
                          ('site_address', 'site_phone', 'site_email')).fetchall()
    conn.close()
    
    # Ayarları dictionary'ye çevir
    contact_info = {setting['setting_key']: setting['setting_value'] for setting in settings}
    
    return render_template('contact.html', contact_info=contact_info)

# İletişim formu gönderme
@app.route('/api/contact-form', methods=['POST'])
def api_contact_form():
    try:
        data = request.get_json()
        
        # Form verilerini al
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        subject = data.get('subject', '').strip()
        message = data.get('message', '').strip()
        
        # Validasyon
        if not name or not email or not message:
            return jsonify({'success': False, 'message': 'Ad, e-posta ve mesaj alanları zorunludur'}), 400
        
        # E-posta gönder
        success, result_message = send_email(
            to_email=email,
            subject=subject or 'İletişim Formu',
            message=message,
            sender_name=name,
            sender_email=email
        )
        
        if success:
            return jsonify({'success': True, 'message': 'Mesajınız başarıyla gönderildi!'})
        else:
            return jsonify({'success': False, 'message': result_message}), 500
            
    except Exception as e:
        print(f"İletişim formu hatası: {str(e)}")
        return jsonify({'success': False, 'message': 'Bir hata oluştu'}), 500

# E-posta test fonksiyonu
@app.route('/api/test-email', methods=['POST'])
@login_required
def api_test_email():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        # Test e-postası gönder
        success, result_message = send_email(
            to_email=current_user.email,
            subject='E-posta Test Mesajı',
            message='Bu bir test e-postasıdır. E-posta ayarlarınız doğru çalışıyor!',
            sender_name='Sistem',
            sender_email='noreply@kemah.com.tr'
        )
        
        if success:
            return jsonify({'success': True, 'message': 'Test e-postası başarıyla gönderildi!'})
        else:
            return jsonify({'success': False, 'message': result_message}), 500
            
    except Exception as e:
        print(f"Test e-posta hatası: {str(e)}")
        return jsonify({'success': False, 'message': 'Test e-postası gönderilemedi'}), 500

# Blog yazısı ekleme
@app.route('/api/add-blog-post', methods=['POST'])
@login_required
def api_add_blog_post():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        # Form verilerini al
        title = request.form.get('title', '').strip()
        author = request.form.get('author', '').strip()
        excerpt = request.form.get('excerpt', '').strip()
        content = request.form.get('content', '').strip()
        
        # Blog detay sayfası ayarları
        blog_author_name = request.form.get('blog_author_name', '').strip()
        blog_author_title = request.form.get('blog_author_title', '').strip()
        blog_tags = request.form.get('blog_tags', '').strip()
        blog_features = request.form.get('blog_features', '').strip()
        sidebar_title = request.form.get('sidebar_title', '').strip()
        sidebar_description = request.form.get('sidebar_description', '').strip()
        
        if not title or not author or not content:
            return jsonify({'success': False, 'message': 'Tüm alanları doldurun'}), 400
        
        conn = get_db_connection()
        
        # Aynı başlıkta blog var mı kontrol et (son 5 dakika içinde)
        existing_post = conn.execute('''
            SELECT id FROM blog_posts 
            WHERE title = ? AND author = ? 
            AND created_at > datetime('now', '-5 minutes')
        ''', (title, author)).fetchone()
        
        if existing_post:
            conn.close()
            return jsonify({'success': False, 'message': 'Aynı başlıkta blog yazısı çok kısa süre önce oluşturulmuş. Lütfen bekleyin.'}), 400
        
        # Blog ID oluştur ve unique kontrolü yap
        import uuid
        max_attempts = 10
        for attempt in range(max_attempts):
            blog_id = f"BLOG_{str(uuid.uuid4())[:8].upper()}"
            existing_blog_id = conn.execute('SELECT id FROM blog_posts WHERE blog_id = ?', (blog_id,)).fetchone()
            if not existing_blog_id:
                break
            if attempt == max_attempts - 1:
                conn.close()
                return jsonify({'success': False, 'message': 'Blog ID oluşturulamadı. Lütfen tekrar deneyin.'}), 500
        
        # Blog yazısını oluştur (eski image sütunu için boş bırak)
        cursor = conn.execute('''
            INSERT INTO blog_posts (blog_id, title, content, author, excerpt, image, 
                                   blog_author_name, blog_author_title, blog_tags, 
                                   blog_features, sidebar_title, sidebar_description,
                                   created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (blog_id, title, content, author, excerpt, None,
              blog_author_name, blog_author_title, blog_tags,
              blog_features, sidebar_title, sidebar_description))
        blog_post_id = cursor.lastrowid
        
        # Ana resim yükleme
        uploaded_images = []
        import uuid
        import os
        from werkzeug.utils import secure_filename
        
        upload_folder = os.path.join(app.root_path, 'static', 'uploads', 'blog')
        os.makedirs(upload_folder, exist_ok=True)
        
        # Ana resim işle
        if 'primary_image' in request.files:
            primary_file = request.files['primary_image']
            if primary_file and primary_file.filename:
                file_ext = os.path.splitext(primary_file.filename)[1].lower()
                if file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                    unique_filename = str(uuid.uuid4()) + file_ext
                    file_path = os.path.join(upload_folder, unique_filename)
                    primary_file.save(file_path)
                    
                    conn.execute('''
                        INSERT INTO blog_images (blog_post_id, image_filename, is_primary, display_order)
                        VALUES (?, ?, ?, ?)
                    ''', (blog_post_id, unique_filename, 1, 0))
                    uploaded_images.append(unique_filename)
                else:
                    return jsonify({'success': False, 'message': f'Ana resim geçersiz format: {primary_file.filename}. Sadece JPG, PNG, GIF, WEBP dosyaları kabul edilir.'}), 400
        
        # Diğer resimler işle
        if 'other_images' in request.files:
            files = request.files.getlist('other_images')
            for i, file in enumerate(files):
                if file and file.filename:
                    file_ext = os.path.splitext(file.filename)[1].lower()
                    if file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                        unique_filename = str(uuid.uuid4()) + file_ext
                        file_path = os.path.join(upload_folder, unique_filename)
                        file.save(file_path)
                        
                        conn.execute('''
                            INSERT INTO blog_images (blog_post_id, image_filename, is_primary, display_order)
                            VALUES (?, ?, ?, ?)
                        ''', (blog_post_id, unique_filename, 0, i + 1))
                        uploaded_images.append(unique_filename)
                    else:
                        return jsonify({'success': False, 'message': f'Geçersiz dosya formatı: {file.filename}. Sadece JPG, PNG, GIF, WEBP dosyaları kabul edilir.'}), 400
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Blog yazısı başarıyla eklendi!'})
        
    except Exception as e:
        print(f"Blog yazısı ekleme hatası: {str(e)}")
        return jsonify({'success': False, 'message': 'Blog yazısı eklenemedi'}), 500

# Blog yazısı güncelleme
@app.route('/api/update-blog-post', methods=['POST'])
@login_required
def api_update_blog_post():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        # Form verilerini al
        blog_id = request.form.get('blog_id')  # post_id yerine blog_id kullan
        title = request.form.get('title', '').strip()
        author = request.form.get('author', '').strip()
        excerpt = request.form.get('excerpt', '').strip()
        content = request.form.get('content', '').strip()
        
        # Blog detay sayfası ayarları
        blog_author_name = request.form.get('blog_author_name', '').strip()
        blog_author_title = request.form.get('blog_author_title', '').strip()
        blog_tags = request.form.get('blog_tags', '').strip()
        blog_features = request.form.get('blog_features', '').strip()
        sidebar_title = request.form.get('sidebar_title', '').strip()
        sidebar_description = request.form.get('sidebar_description', '').strip()
        
        if not blog_id or not title or not author or not content:
            return jsonify({'success': False, 'message': 'Tüm alanları doldurun'}), 400
        
        # Ana resim ve diğer resimler yükleme
        uploaded_images = []
        import uuid
        import os
        from werkzeug.utils import secure_filename
        
        upload_folder = os.path.join(app.root_path, 'static', 'uploads', 'blog')
        os.makedirs(upload_folder, exist_ok=True)
        
        # Ana resim işle
        if 'primary_image' in request.files:
            primary_file = request.files['primary_image']
            if primary_file and primary_file.filename:
                file_ext = os.path.splitext(primary_file.filename)[1].lower()
                if file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                    unique_filename = str(uuid.uuid4()) + file_ext
                    file_path = os.path.join(upload_folder, unique_filename)
                    primary_file.save(file_path)
                    uploaded_images.append({'filename': unique_filename, 'is_primary': 1, 'order': 0})
                    print(f"Ana resim eklendi: {file_path}")
                else:
                    return jsonify({'success': False, 'message': f'Ana resim geçersiz format: {primary_file.filename}. Sadece JPG, PNG, GIF, WEBP dosyaları kabul edilir.'}), 400
        
        # Diğer resimler işle
        if 'other_images' in request.files:
            files = request.files.getlist('other_images')
            for i, file in enumerate(files):
                if file and file.filename:
                    file_ext = os.path.splitext(file.filename)[1].lower()
                    if file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                        unique_filename = str(uuid.uuid4()) + file_ext
                        file_path = os.path.join(upload_folder, unique_filename)
                        file.save(file_path)
                        uploaded_images.append({'filename': unique_filename, 'is_primary': 0, 'order': i + 1})
                        print(f"Diğer resim eklendi: {file_path}")
                    else:
                        return jsonify({'success': False, 'message': f'Geçersiz dosya formatı: {file.filename}. Sadece JPG, PNG, GIF, WEBP dosyaları kabul edilir.'}), 400
        
        conn = get_db_connection()
        
        # Aynı blog_id'ye sahip birden fazla blog var mı kontrol et
        duplicate_count = conn.execute('SELECT COUNT(*) FROM blog_posts WHERE blog_id = ?', (blog_id,)).fetchone()[0]
        
        if duplicate_count > 1:
            # Çift blog varsa, sadece birini güncelle (en son oluşturulanı)
            conn.execute('''
                UPDATE blog_posts 
                SET title = ?, content = ?, author = ?, excerpt = ?, 
                    blog_author_name = ?, blog_author_title = ?, blog_tags = ?,
                    blog_features = ?, sidebar_title = ?, sidebar_description = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE blog_id = ? AND id = (
                    SELECT MAX(id) FROM blog_posts WHERE blog_id = ?
                )
            ''', (title, content, author, excerpt, 
                  blog_author_name, blog_author_title, blog_tags,
                      blog_features, sidebar_title, sidebar_description, blog_id, blog_id))
            
            # Güncellenen blog'un ID'sini al
            updated_post = conn.execute('''
                SELECT id FROM blog_posts 
                WHERE blog_id = ? AND id = (
                    SELECT MAX(id) FROM blog_posts WHERE blog_id = ?
                )
            ''', (blog_id, blog_id)).fetchone()
            post_id = updated_post['id'] if updated_post else None
        else:
            # Tek blog varsa normal güncelleme işlemi
            conn.execute('''
                UPDATE blog_posts 
                SET title = ?, content = ?, author = ?, excerpt = ?, 
                    blog_author_name = ?, blog_author_title = ?, blog_tags = ?,
                    blog_features = ?, sidebar_title = ?, sidebar_description = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE blog_id = ?
            ''', (title, content, author, excerpt, 
                  blog_author_name, blog_author_title, blog_tags,
                  blog_features, sidebar_title, sidebar_description, blog_id))
            
            # Güncellenen blog'un ID'sini al
            updated_post = conn.execute('SELECT id FROM blog_posts WHERE blog_id = ?', (blog_id,)).fetchone()
            post_id = updated_post['id'] if updated_post else None
        
        # Yeni resimleri blog_images tablosuna ekle
        if uploaded_images and post_id:
            # Mevcut resim sayısını al
            existing_count = conn.execute('SELECT COUNT(*) FROM blog_images WHERE blog_post_id = ?', (post_id,)).fetchone()[0]
            
            for image_data in uploaded_images:
                conn.execute('''
                    INSERT INTO blog_images (blog_post_id, image_filename, is_primary, display_order)
                    VALUES (?, ?, ?, ?)
                ''', (post_id, image_data['filename'], image_data['is_primary'], existing_count + image_data['order']))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Blog yazısı başarıyla güncellendi!'})
        
    except Exception as e:
        print(f"Blog yazısı güncelleme hatası: {str(e)}")
        return jsonify({'success': False, 'message': 'Blog yazısı güncellenemedi'}), 500

# Blog yazısı silme
@app.route('/api/delete-blog-post', methods=['POST'])
@login_required
def api_delete_blog_post():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        data = request.get_json()
        blog_id = data.get('blog_id')  # post_id yerine blog_id kullan
        
        if not blog_id:
            return jsonify({'success': False, 'message': 'Blog yazısı ID gerekli'}), 400
        
        conn = get_db_connection()
        
        # Aynı blog_id'ye sahip birden fazla blog var mı kontrol et
        duplicate_count = conn.execute('SELECT COUNT(*) FROM blog_posts WHERE blog_id = ?', (blog_id,)).fetchone()[0]
        
        if duplicate_count > 1:
            # Çift blog varsa, sadece birini sil (en son oluşturulanı)
            conn.execute('''
                DELETE FROM blog_posts 
                WHERE blog_id = ? AND id = (
                    SELECT MAX(id) FROM blog_posts WHERE blog_id = ?
                )
            ''', (blog_id, blog_id))
            message = f'Çift blog yazısı tespit edildi. En son oluşturulan blog yazısı silindi. (Kalan: {duplicate_count-1} adet)'
        else:
            # Tek blog varsa normal silme işlemi
        # Resmi de sil
            post = conn.execute('SELECT image FROM blog_posts WHERE blog_id = ?', (blog_id,)).fetchone()
        if post and post['image']:
            import os
            image_path = os.path.join(app.root_path, 'static', 'uploads', 'blog', post['image'])
            if os.path.exists(image_path):
                os.remove(image_path)
                print(f"Blog resmi silindi: {image_path}")
        
            conn.execute('DELETE FROM blog_posts WHERE blog_id = ?', (blog_id,))
            message = 'Blog yazısı başarıyla silindi!'
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        print(f"Blog yazısı silme hatası: {str(e)}")
        return jsonify({'success': False, 'message': f'Blog yazısı silinemedi: {str(e)}'}), 500

# Blog resmi silme endpoint'i
@app.route('/api/delete-blog-image', methods=['POST'])
@login_required
def api_delete_blog_image():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        data = request.get_json()
        image_id = data.get('image_id')
        
        if not image_id:
            return jsonify({'success': False, 'message': 'Resim ID gerekli'}), 400
        
        conn = get_db_connection()
        
        # Resim bilgilerini al
        image = conn.execute('SELECT image_filename FROM blog_images WHERE id = ?', (image_id,)).fetchone()
        if not image:
            return jsonify({'success': False, 'message': 'Resim bulunamadı'}), 404
        
        # Dosyayı sil
        import os
        image_path = os.path.join(app.root_path, 'static', 'uploads', 'blog', image['image_filename'])
        if os.path.exists(image_path):
            os.remove(image_path)
            print(f"Blog resmi silindi: {image_path}")
        
        # Veritabanından sil
        conn.execute('DELETE FROM blog_images WHERE id = ?', (image_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Resim başarıyla silindi!'})
        
    except Exception as e:
        print(f"Blog resmi silme hatası: {str(e)}")
        return jsonify({'success': False, 'message': 'Resim silinemedi'}), 500

# Blog resmi ekleme endpoint'i
@app.route('/api/add-blog-image', methods=['POST'])
@login_required
def api_add_blog_image():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        blog_post_id = request.form.get('blog_post_id')
        if not blog_post_id:
            return jsonify({'success': False, 'message': 'Blog yazısı ID gerekli'}), 400
        
        if 'image' not in request.files:
            return jsonify({'success': False, 'message': 'Resim dosyası gerekli'}), 400
        
        file = request.files['image']
        if not file or not file.filename:
            return jsonify({'success': False, 'message': 'Resim dosyası seçilmedi'}), 400
        
        # Dosya uzantısını kontrol et
        import uuid
        import os
        from werkzeug.utils import secure_filename
        
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            return jsonify({'success': False, 'message': 'Geçersiz dosya formatı. Sadece JPG, PNG, GIF, WEBP dosyaları kabul edilir.'}), 400
        
        # Benzersiz dosya adı oluştur
        unique_filename = str(uuid.uuid4()) + file_ext
        
        # Uploads klasörünü oluştur
        upload_folder = os.path.join(app.root_path, 'static', 'uploads', 'blog')
        os.makedirs(upload_folder, exist_ok=True)
        
        # Dosyayı kaydet
        file_path = os.path.join(upload_folder, unique_filename)
        file.save(file_path)
        
        # Veritabanına kaydet
        conn = get_db_connection()
        
        # Mevcut resim sayısını al
        image_count = conn.execute('SELECT COUNT(*) as count FROM blog_images WHERE blog_post_id = ?', (blog_post_id,)).fetchone()['count']
        
        conn.execute('''
            INSERT INTO blog_images (blog_post_id, image_filename, is_primary, display_order)
            VALUES (?, ?, ?, ?)
        ''', (blog_post_id, unique_filename, 0, image_count))
        
        conn.commit()
        conn.close()
        
        print(f"Blog resmi eklendi: {file_path}")
        return jsonify({'success': True, 'message': 'Resim başarıyla eklendi!'})
        
    except Exception as e:
        print(f"Blog resmi ekleme hatası: {str(e)}")
        return jsonify({'success': False, 'message': 'Resim eklenemedi'}), 500

# Blog yazısı görüntüleme
@app.route('/api/blog-post/<blog_id>')
def api_get_blog_post(blog_id):
    try:
        conn = get_db_connection()
        
        # Blog yazısını al (en son oluşturulanı)
        post = conn.execute('''
            SELECT id, blog_id, title, content, author, created_at, updated_at, excerpt,
                   blog_author_name, blog_author_title, blog_author_avatar,
                   blog_tags, blog_features, sidebar_title, sidebar_description
            FROM blog_posts 
            WHERE blog_id = ? AND id = (
                SELECT MAX(id) FROM blog_posts WHERE blog_id = ?
            )
        ''', (blog_id, blog_id)).fetchone()
        
        if post:
            # Blog resimlerini al
            images = conn.execute('''
                SELECT id, image_filename, is_primary, display_order
                FROM blog_images 
                WHERE blog_post_id = ?
                ORDER BY display_order, created_at
            ''', (post['id'],)).fetchall()
            
            conn.close()
            
            return jsonify({
                'success': True, 
                'post': {
                    'id': post['id'],
                    'blog_id': post['blog_id'],
                    'title': post['title'],
                    'content': post['content'],
                    'author': post['author'],
                    'excerpt': post['excerpt'],
                    'created_at': post['created_at'],
                    'updated_at': post['updated_at'],
                    'blog_author_name': post['blog_author_name'],
                    'blog_author_title': post['blog_author_title'],
                    'blog_author_avatar': post['blog_author_avatar'],
                    'blog_tags': post['blog_tags'],
                    'blog_features': post['blog_features'],
                    'sidebar_title': post['sidebar_title'],
                    'sidebar_description': post['sidebar_description'],
                    'images': [{
                        'id': img['id'],
                        'filename': img['image_filename'],
                        'is_primary': bool(img['is_primary']),
                        'display_order': img['display_order']
                    } for img in images]
                }
            })
        else:
            conn.close()
            return jsonify({'success': False, 'message': 'Blog yazısı bulunamadı'}), 404
            
    except Exception as e:
        print(f"Blog yazısı getirme hatası: {str(e)}")
        return jsonify({'success': False, 'message': 'Blog yazısı yüklenemedi'}), 500

# Admin Panel
@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_authenticated:
        flash('Giriş yapmanız gerekiyor!', 'error')
        return redirect(url_for('login'))
    
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    conn = get_db_connection()
    
    # İstatistikler
    stats = {
        'total_products': conn.execute('SELECT COUNT(*) as count FROM products').fetchone()['count'],
        'total_orders': conn.execute('SELECT COUNT(*) as count FROM orders').fetchone()['count'],
        'total_users': conn.execute('SELECT COUNT(*) as count FROM users').fetchone()['count'],
        'total_categories': conn.execute('SELECT COUNT(*) as count FROM categories').fetchone()['count']
    }
    
    # Son siparişler
    recent_orders = conn.execute('''
        SELECT o.*, u.first_name, u.last_name, u.email 
        FROM orders o 
        LEFT JOIN users u ON o.user_id = u.id 
        ORDER BY o.created_at DESC 
        LIMIT 10
    ''').fetchall()
    
    conn.close()
    
    return render_template('admin/dashboard.html', stats=stats, recent_orders=recent_orders)

# Dashboard API Endpoints
@app.route('/api/dashboard/visitor-stats')
@login_required
def api_visitor_stats():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    
    # Son 7 günün ziyaretçi verilerini al (benzersiz IP'ler)
    visitor_data = conn.execute('''
        SELECT DATE(last_visit) as visit_date, COUNT(DISTINCT ip_address) as visitor_count
        FROM visitors 
        WHERE last_visit >= date('now', '-7 days')
        GROUP BY DATE(last_visit)
        ORDER BY visit_date
    ''').fetchall()
    
    conn.close()
    
    # Eksik günleri doldur
    from datetime import datetime, timedelta
    labels = []
    values = []
    
    for i in range(7):
        date = (datetime.now() - timedelta(days=6-i)).strftime('%Y-%m-%d')
        labels.append(date)
        
        # Bu tarih için veri var mı kontrol et
        found = False
        for row in visitor_data:
            if row['visit_date'] == date:
                values.append(row['visitor_count'])
                found = True
                break
        
        if not found:
            values.append(0)
    
    # Türkçe gün isimleri
    turkish_days = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz']
    labels = turkish_days
    
    return jsonify({
        'labels': labels,
        'values': values
    })

@app.route('/api/dashboard/sales-stats')
@login_required
def api_sales_stats():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    
    # Son 7 günün satış verilerini al
    sales_data = conn.execute('''
        SELECT DATE(created_at) as sale_date, SUM(total_amount) as daily_sales
        FROM orders 
        WHERE created_at >= date('now', '-7 days')
        AND status != 'cancelled'
        GROUP BY DATE(created_at)
        ORDER BY sale_date
    ''').fetchall()
    
    conn.close()
    
    # Eksik günleri doldur
    from datetime import datetime, timedelta
    labels = []
    values = []
    
    for i in range(7):
        date = (datetime.now() - timedelta(days=6-i)).strftime('%Y-%m-%d')
        labels.append(date)
        
        # Bu tarih için veri var mı kontrol et
        found = False
        for row in sales_data:
            if row['sale_date'] == date:
                values.append(float(row['daily_sales']) if row['daily_sales'] else 0)
                found = True
                break
        
        if not found:
            values.append(0)
    
    # Türkçe gün isimleri
    turkish_days = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz']
    labels = turkish_days
    
    return jsonify({
        'labels': labels,
        'values': values
    })

# Admin - Ürün Yönetimi
@app.route('/admin/urunler')
@login_required
def admin_products():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    products = conn.execute('''
        SELECT p.*, c.name as category_name, c.image as category_image 
        FROM products p 
        JOIN categories c ON p.category_id = c.id
    ''').fetchall()
    conn.close()
    
    return render_template('admin/products.html', products=products)

# Ürün Ekleme - YENİ SİSTEM
@app.route('/admin/urunler/ekle', methods=['GET', 'POST'])
@login_required
def admin_add_product():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        print("=== ÜRÜN EKLEME BAŞLADI ===")
        print(f"Form verileri: {dict(request.form)}")
        
        # Form verilerini al
        name = request.form.get('name')
        slug = request.form.get('slug')
        description = request.form.get('description', '')
        short_description = request.form.get('short_description', '')
        price = request.form.get('price', '0')
        stock_quantity = request.form.get('stock_quantity', '0')
        category_id = request.form.get('category_id', '1')
        weight = request.form.get('weight', '')
        brand = request.form.get('brand', '')
        is_featured = 'is_featured' in request.form
        is_new = 'is_new' in request.form
        
        # Çoklu dosya yükleme işlemi
        image_files = request.files.getlist('images')
        uploaded_images = []
        
        for i, file in enumerate(image_files):
            if file and file.filename:
                # Dosya adını güvenli hale getir
                filename = secure_filename(file.filename)
                # Unique dosya adı oluştur
                image_filename = f"{slug}_{int(time.time())}_{i}_{filename}"
                # Dosyayı kaydet
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
                uploaded_images.append({
                    'filename': image_filename,
                    'is_primary': i == 0,  # İlk resim ana resim
                    'display_order': i
                })
        
        # Ana resim olarak ilk yüklenen resmi kullan
        main_image = uploaded_images[0]['filename'] if uploaded_images else None
        
        print(f"İşlenen veriler: name={name}, slug={slug}, price={price}, category_id={category_id}")
        
        try:
            # Veritabanına kaydet
            conn = get_db_connection()
            cursor = conn.execute('''
                INSERT INTO products (name, slug, description, short_description, price, stock_quantity, image, category_id, weight, brand, is_featured, is_new)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, slug, description, short_description, price, stock_quantity, main_image, category_id, weight, brand, is_featured, is_new))
            
            product_id = cursor.lastrowid
            
            # Çoklu resimleri kaydet
            for img in uploaded_images:
                conn.execute('''
                    INSERT INTO product_images (product_id, image_filename, is_primary, display_order)
                    VALUES (?, ?, ?, ?)
                ''', (product_id, img['filename'], img['is_primary'], img['display_order']))
            
            conn.commit()
            conn.close()
            
            print("=== ÜRÜN BAŞARIYLA KAYDEDİLDİ ===")
            flash('Ürün eklendi!', 'success')
            return redirect(url_for('admin_products'))
        except Exception as e:
            print(f"=== HATA: {str(e)} ===")
            flash(f'Hata: {str(e)}', 'error')
            return redirect(url_for('admin_add_product'))
    
    # Formu göster
    conn = get_db_connection()
    categories = conn.execute('SELECT * FROM categories WHERE is_active = 1').fetchall()
    conn.close()
    
    return render_template('admin/add_product.html', categories=categories)

# Admin - Ürün Düzenleme
@app.route('/admin/urunler/duzenle/<int:product_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_product(product_id):
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    
    if request.method == 'POST':
        # Form verilerini al
        name = request.form.get('name', '').strip()
        slug = request.form.get('slug', '').strip()
        description = request.form.get('description', '').strip()
        short_description = request.form.get('short_description', '').strip()
        price = request.form.get('price', '0').strip()
        stock_quantity = request.form.get('stock_quantity', '0').strip()
        is_active = 'is_active' in request.form
        category_id = request.form.get('category_id', '1').strip()
        weight = request.form.get('weight', '').strip()
        brand = request.form.get('brand', '').strip()
        is_featured = 'is_featured' in request.form
        is_new = 'is_new' in request.form
        
        # Çoklu resim yükleme
        image_files = request.files.getlist('images')
        uploaded_images = []
        
        for i, file in enumerate(image_files):
            if file and file.filename:
                filename = secure_filename(file.filename)
                image_filename = f"{slug}_{int(time.time())}_{i}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
                uploaded_images.append({
                    'filename': image_filename,
                    'is_primary': i == 0,
                    'display_order': i
                })
                print(f"Ürün resmi yüklendi: {image_filename}")
        
        # Ana resim olarak ilk yüklenen resmi kullan
        main_image = uploaded_images[0]['filename'] if uploaded_images else None
        
        # Boş alan kontrolü
        if not name:
            flash('Ürün adı boş olamaz!', 'error')
            conn.close()
            return redirect(url_for('admin_edit_product', product_id=product_id))
        
        if not slug:
            flash('URL slug boş olamaz!', 'error')
            conn.close()
            return redirect(url_for('admin_edit_product', product_id=product_id))
        
        # Sayısal değer kontrolü
        try:
            price_float = float(price)
            stock_int = int(stock_quantity)
            category_int = int(category_id)
        except ValueError:
            flash('Fiyat ve stok sayısal değer olmalıdır!', 'error')
            conn.close()
            return redirect(url_for('admin_edit_product', product_id=product_id))
        
        try:
            # Slug kontrolü (kendi ID'si hariç)
            existing = conn.execute('SELECT id FROM products WHERE slug = ? AND id != ?', (slug, product_id)).fetchone()
            if existing:
                flash('Bu URL slug zaten kullanılıyor!', 'error')
                conn.close()
                return redirect(url_for('admin_edit_product', product_id=product_id))
            
            # Ürünü güncelle
            if main_image:
                # Yeni resim yüklendi, image kolonunu güncelle
                conn.execute('''
                    UPDATE products 
                    SET name = ?, slug = ?, description = ?, short_description = ?, 
                        price = ?, stock_quantity = ?, is_active = ?, category_id = ?, 
                        weight = ?, brand = ?, is_featured = ?, is_new = ?, image = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (name, slug, description, short_description, price_float, stock_int, 
                      is_active, category_int, weight, brand, is_featured, is_new, main_image, product_id))
            else:
                # Resim yüklenmedi, image kolonunu güncelleme
                conn.execute('''
                    UPDATE products 
                    SET name = ?, slug = ?, description = ?, short_description = ?, 
                        price = ?, stock_quantity = ?, is_active = ?, category_id = ?, 
                        weight = ?, brand = ?, is_featured = ?, is_new = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (name, slug, description, short_description, price_float, stock_int, 
                      is_active, category_int, weight, brand, is_featured, is_new, product_id))
            
            # Yeni resimleri ekle
            for img in uploaded_images:
                conn.execute('''
                    INSERT INTO product_images (product_id, image_filename, is_primary, display_order)
                    VALUES (?, ?, ?, ?)
                ''', (product_id, img['filename'], img['is_primary'], img['display_order']))
            
            conn.commit()
            conn.close()
            
            flash('Ürün başarıyla güncellendi!', 'success')
            return redirect(url_for('admin_products'))
            
        except Exception as e:
            conn.close()
            flash(f'Hata: {str(e)}', 'error')
            return redirect(url_for('admin_edit_product', product_id=product_id))
    
    # Ürün bilgilerini getir
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    if not product:
        flash('Ürün bulunamadı!', 'error')
        conn.close()
        return redirect(url_for('admin_products'))
    
    categories = conn.execute('SELECT * FROM categories WHERE is_active = 1').fetchall()
    
    # Ürün resimlerini getir
    product_images = conn.execute('''
        SELECT * FROM product_images 
        WHERE product_id = ? 
        ORDER BY is_primary DESC, display_order ASC
    ''', (product_id,)).fetchall()
    
    conn.close()
    
    return render_template('admin/edit_product.html', product=product, categories=categories, product_images=product_images)

# Admin - Ürün Silme
@app.route('/admin/urunler/sil/<int:product_id>', methods=['POST'])
@login_required
def admin_delete_product(product_id):
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    
    # Ürün var mı kontrol et
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    if not product:
        flash('Ürün bulunamadı!', 'error')
        conn.close()
        return redirect(url_for('admin_products'))
    
    # Ürünü sil
    conn.execute('DELETE FROM products WHERE id = ?', (product_id,))
    conn.commit()
    conn.close()
    
    flash('Ürün başarıyla silindi!', 'success')
    return redirect(url_for('admin_products'))

# Admin - Ürün Resmi Silme
@app.route('/admin/urunler/resim-sil/<int:image_id>', methods=['POST'])
@login_required
def admin_delete_product_image(image_id):
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    
    # Resim bilgilerini getir
    image_info = conn.execute('SELECT * FROM product_images WHERE id = ?', (image_id,)).fetchone()
    if not image_info:
        flash('Resim bulunamadı!', 'error')
        conn.close()
        return redirect(url_for('admin_products'))
    
    # Ana resim ise ürünün ana resmini NULL yap
    if image_info['is_primary']:
        conn.execute('UPDATE products SET image = NULL WHERE id = ?', (image_info['product_id'],))
    
    # Resmi veritabanından sil
    conn.execute('DELETE FROM product_images WHERE id = ?', (image_id,))
    
    # Dosyayı da sil
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], image_info['image_filename'])
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"Dosya silinemedi: {e}")
    
    conn.commit()
    conn.close()
    
    flash('Resim başarıyla silindi!', 'success')
    return redirect(url_for('admin_edit_product', product_id=image_info['product_id']))

# Admin - Kategori Yönetimi
@app.route('/admin/kategoriler')
@login_required
def admin_categories():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    categories = conn.execute('SELECT * FROM categories').fetchall()
    conn.close()
    
    return render_template('admin/categories.html', categories=categories)

# Kategori Ekleme - YENİ SİSTEM
@app.route('/admin/kategoriler/ekle', methods=['GET', 'POST'])
@login_required
def admin_add_category():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        print("=== KATEGORİ EKLEME BAŞLADI ===")
        print(f"Form verileri: {dict(request.form)}")
        
        # Form verilerini al
        name = request.form.get('name')
        slug = request.form.get('slug')
        description = request.form.get('description', '')
        parent_id = request.form.get('parent_id', '')
        is_active = 'is_active' in request.form
        
        print(f"İşlenen veriler: name={name}, slug={slug}, parent_id={parent_id}")
        
        # parent_id'yi düzelt
        if parent_id:
            parent_id = int(parent_id)
        else:
            parent_id = None
        
        # Resim yükleme
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                filename = secure_filename(file.filename)
                image_filename = f"{slug}_{int(time.time())}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
                print(f"Resim yüklendi: {image_filename}")
        
        try:
            # Veritabanına kaydet
            conn = get_db_connection()
            conn.execute('''
                INSERT INTO categories (name, slug, description, parent_id, image, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, slug, description, parent_id, image_filename, is_active))
            conn.commit()
            conn.close()
            
            print("=== KATEGORİ BAŞARIYLA KAYDEDİLDİ ===")
            flash('Kategori eklendi!', 'success')
            return redirect(url_for('admin_categories'))
        except Exception as e:
            print(f"=== KATEGORİ HATASI: {str(e)} ===")
            flash(f'Hata: {str(e)}', 'error')
            return redirect(url_for('admin_categories'))
        
    return redirect(url_for('admin_categories'))

# Admin - Kategori Düzenleme
@app.route('/admin/kategoriler/duzenle/<int:category_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_category(category_id):
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
        
    if request.method == 'POST':
        print("=== KATEGORİ DÜZENLEME BAŞLADI ===")
        print(f"Form verileri: {dict(request.form)}")
        
        # Form verilerini al
        name = request.form.get('name')
        slug = request.form.get('slug')
        description = request.form.get('description', '')
        parent_id = request.form.get('parent_id', '')
        is_active = 'is_active' in request.form
        
        print(f"İşlenen veriler: name={name}, slug={slug}, parent_id={parent_id}")
        
        # parent_id'yi düzelt
        if parent_id:
            parent_id = int(parent_id)
        else:
            parent_id = None
        
        # Resim yükleme
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                filename = secure_filename(file.filename)
                image_filename = f"{slug}_{int(time.time())}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
                print(f"Resim yüklendi: {image_filename}")
        
        try:
            # Slug kontrolü (kendi ID'si hariç)
            existing = conn.execute('SELECT id FROM categories WHERE slug = ? AND id != ?', (slug, category_id)).fetchone()
            if existing:
                flash('Bu URL slug zaten kullanılıyor!', 'error')
                conn.close()
                return redirect(url_for('admin_edit_category', category_id=category_id))
            
            # Kategoriyi güncelle
            conn.execute('''
                UPDATE categories 
                SET name = ?, slug = ?, description = ?, parent_id = ?, image = ?, is_active = ?
                WHERE id = ?
            ''', (name, slug, description, parent_id, image_filename, is_active, category_id))
            
            conn.commit()
            conn.close()
            
            print("=== KATEGORİ BAŞARIYLA GÜNCELLENDİ ===")
            flash('Kategori başarıyla güncellendi!', 'success')
            return redirect(url_for('admin_categories'))
            
        except Exception as e:
            print(f"=== KATEGORİ GÜNCELLEME HATASI: {str(e)} ===")
            conn.close()
            flash(f'Hata: {str(e)}', 'error')
            return redirect(url_for('admin_edit_category', category_id=category_id))
    
    # Kategori bilgilerini getir
    category = conn.execute('SELECT * FROM categories WHERE id = ?', (category_id,)).fetchone()
    if not category:
        flash('Kategori bulunamadı!', 'error')
        conn.close()
        return redirect(url_for('admin_categories'))
    
    # Tüm kategorileri getir (parent seçimi için)
    all_categories = conn.execute('SELECT * FROM categories WHERE id != ? AND is_active = 1', (category_id,)).fetchall()
    conn.close()
    
    return render_template('admin/edit_category.html', category=category, all_categories=all_categories)

# Admin - Kategori Silme
@app.route('/admin/kategoriler/sil/<int:category_id>', methods=['POST'])
@login_required
def admin_delete_category(category_id):
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    print(f"=== KATEGORİ SİLME BAŞLADI: {category_id} ===")
    
    conn = get_db_connection()
    
    # Kategori var mı kontrol et
    category = conn.execute('SELECT * FROM categories WHERE id = ?', (category_id,)).fetchone()
    if not category:
        print("Kategori bulunamadı")
        flash('Kategori bulunamadı!', 'error')
        conn.close()
        return redirect(url_for('admin_categories'))
    
    # Bu kategoride ürün var mı kontrol et
    products_count = conn.execute('SELECT COUNT(*) as count FROM products WHERE category_id = ?', (category_id,)).fetchone()['count']
    if products_count > 0:
        print(f"Kategoride {products_count} ürün bulundu, ürünler de silinecek")
        # Ürünleri de sil
        conn.execute('DELETE FROM products WHERE category_id = ?', (category_id,))
    
    # Alt kategoriler var mı kontrol et
    subcategories_count = conn.execute('SELECT COUNT(*) as count FROM categories WHERE parent_id = ?', (category_id,)).fetchone()['count']
    if subcategories_count > 0:
        print(f"Kategoride {subcategories_count} alt kategori bulundu")
        flash('Bu kategorinin alt kategorileri bulunduğu için silinemez!', 'error')
        conn.close()
        return redirect(url_for('admin_categories'))
    
    # Kategoriyi sil
    conn.execute('DELETE FROM categories WHERE id = ?', (category_id,))
    conn.commit()
    conn.close()
    
    if products_count > 0:
        print(f"=== KATEGORİ VE {products_count} ÜRÜN BAŞARIYLA SİLİNDİ ===")
        flash(f'Kategori ve {products_count} ürün başarıyla silindi!', 'success')
    else:
        print("=== KATEGORİ BAŞARIYLA SİLİNDİ ===")
        flash('Kategori başarıyla silindi!', 'success')
    
    return redirect(url_for('admin_categories'))

# Admin - Kategori Zorla Silme
@app.route('/admin/kategoriler/zorla-sil/<int:category_id>', methods=['POST'])
@login_required
def admin_force_delete_category(category_id):
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    print(f"=== KATEGORİ ZORLA SİLME BAŞLADI: {category_id} ===")
    
    conn = get_db_connection()
    
    # Kategori var mı kontrol et
    category = conn.execute('SELECT * FROM categories WHERE id = ?', (category_id,)).fetchone()
    if not category:
        print("Kategori bulunamadı")
        flash('Kategori bulunamadı!', 'error')
        conn.close()
        return redirect(url_for('admin_categories'))
    
    # Bu kategorideki ürünleri sil
    products_count = conn.execute('SELECT COUNT(*) as count FROM products WHERE category_id = ?', (category_id,)).fetchone()['count']
    if products_count > 0:
        print(f"Kategorideki {products_count} ürün siliniyor")
        conn.execute('DELETE FROM products WHERE category_id = ?', (category_id,))
    
    # Alt kategorileri ana kategori yap
    conn.execute('UPDATE categories SET parent_id = NULL WHERE parent_id = ?', (category_id,))
    
    # Kategoriyi sil
    conn.execute('DELETE FROM categories WHERE id = ?', (category_id,))
    conn.commit()
    conn.close()
    
    print(f"=== KATEGORİ VE {products_count} ÜRÜN BAŞARIYLA SİLİNDİ ===")
    flash(f'Kategori ve {products_count} ürün başarıyla silindi!', 'success')
    return redirect(url_for('admin_categories'))

# Admin - Müşteri Yönetimi
# Admin Ayarları
@app.route('/admin/ayarlar')
@login_required
def admin_settings():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    settings = conn.execute('SELECT * FROM site_settings ORDER BY setting_key').fetchall()
    
    # Site durumu bilgisini al
    site_status = conn.execute('SELECT * FROM site_status ORDER BY id DESC LIMIT 1').fetchone()
    
    conn.close()
    
    # Ayarları dictionary'ye çevir
    settings_dict = {setting['setting_key']: setting['setting_value'] for setting in settings}
    
    return render_template('admin/settings.html', settings=settings_dict, site_status=site_status)

# Bakım Modu Kontrolü API
@app.route('/api/maintenance/toggle', methods=['POST'])
@login_required
def api_toggle_maintenance():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    data = request.get_json()
    is_maintenance = data.get('is_maintenance', False)
    message = data.get('message', 'Site bakımda. Lütfen daha sonra tekrar deneyin.')
    
    try:
        set_maintenance_mode(is_maintenance, message)
        
        if is_maintenance:
            return jsonify({
                'success': True, 
                'message': 'Site bakım moduna alındı',
                'status': 'maintenance'
            })
        else:
            return jsonify({
                'success': True, 
                'message': 'Site normal moda alındı',
                'status': 'active'
            })
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Hata oluştu: {str(e)}'
        }), 500

# Blog Sayfası
@app.route('/blog')
@maintenance_required
def blog():
    conn = get_db_connection()
    
    # Blog yazılarını al (son 6 yazı) - çoklu resim desteği ile (çift blog yazılarını gösterme)
    blog_posts = conn.execute('''
        SELECT bp.id, bp.blog_id, bp.title, bp.content, bp.author, bp.created_at, bp.updated_at,
               CASE WHEN LENGTH(bp.content) > 150 THEN SUBSTR(bp.content, 1, 150) || '...' ELSE bp.content END as excerpt,
               bi.image_filename as primary_image
        FROM blog_posts bp
        LEFT JOIN blog_images bi ON bp.id = bi.blog_post_id AND bi.is_primary = 1
        WHERE (bp.is_published IS NULL OR bp.is_published = 1)
        AND bp.id IN (
            SELECT MAX(id) FROM blog_posts 
            GROUP BY blog_id
        )
        ORDER BY bp.created_at DESC
        LIMIT 6
    ''').fetchall()
    
    # Toplam blog sayısı
    total_posts = conn.execute('SELECT COUNT(*) as count FROM blog_posts').fetchone()['count']
    
    conn.close()
    
    return render_template('blog.html', 
                         blog_posts=blog_posts,
                         total_posts=total_posts)

# Blog Yönetimi
@app.route('/admin/blog-yonetimi')
@login_required
def admin_blog_management():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    
    # Blog yazılarını al - çoklu resim desteği ile (çift blog yazılarını gösterme)
    blog_posts = conn.execute('''
        SELECT bp.id, bp.blog_id, bp.title, bp.content, bp.author, bp.created_at, bp.updated_at,
               CASE WHEN LENGTH(bp.content) > 100 THEN SUBSTR(bp.content, 1, 100) || '...' ELSE bp.content END as excerpt,
               bi.image_filename as primary_image,
               (SELECT COUNT(*) FROM blog_images WHERE blog_post_id = bp.id) as image_count
        FROM blog_posts bp
        LEFT JOIN blog_images bi ON bp.id = bi.blog_post_id AND bi.is_primary = 1
        WHERE bp.id IN (
            SELECT MAX(id) FROM blog_posts 
            GROUP BY blog_id
        )
        ORDER BY bp.created_at DESC
    ''').fetchall()
    
    # Blog istatistikleri
    total_posts = conn.execute('SELECT COUNT(*) as count FROM blog_posts').fetchone()['count']
    recent_posts = conn.execute('''
        SELECT COUNT(*) as count FROM blog_posts 
        WHERE created_at >= datetime('now', '-7 days')
    ''').fetchone()['count']
    
    conn.close()
    
    return render_template('admin/blog_management.html', 
                         blog_posts=blog_posts,
                         total_posts=total_posts,
                         recent_posts=recent_posts)

# Blog Etiketleri Yönetimi
@app.route('/admin/blog-etiketleri')
@login_required
def admin_blog_tags():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    
    # Etiketleri al
    tags = conn.execute('''
        SELECT * FROM blog_tags 
        ORDER BY name
    ''').fetchall()
    
    # Renk seçenekleri
    color_options = [
        ('bg-primary', 'Mavi'),
        ('bg-success', 'Yeşil'),
        ('bg-info', 'Açık Mavi'),
        ('bg-warning', 'Sarı'),
        ('bg-danger', 'Kırmızı'),
        ('bg-secondary', 'Gri'),
        ('bg-dark', 'Siyah'),
        ('bg-light', 'Açık Gri')
    ]
    
    conn.close()
    
    return render_template('admin/blog_tags.html', tags=tags, color_options=color_options)

# Blog Özellikleri Yönetimi
@app.route('/admin/blog-ozellikleri')
@login_required
def admin_blog_features():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    
    # Özellikleri al
    features = conn.execute('''
        SELECT * FROM blog_features 
        ORDER BY name
    ''').fetchall()
    
    # Icon seçenekleri
    icon_options = [
        ('fas fa-leaf', 'Yaprak'),
        ('fas fa-user-graduate', 'Uzman'),
        ('fas fa-clock', 'Saat'),
        ('fas fa-info-circle', 'Bilgi'),
        ('fas fa-microscope', 'Mikroskop'),
        ('fas fa-lightbulb', 'Ampul'),
        ('fas fa-shield-alt', 'Kalkan'),
        ('fas fa-check', 'Onay'),
        ('fas fa-star', 'Yıldız'),
        ('fas fa-heart', 'Kalp'),
        ('fas fa-thumbs-up', 'Beğeni'),
        ('fas fa-award', 'Ödül')
    ]
    
    conn.close()
    
    return render_template('admin/blog_features.html', features=features, icon_options=icon_options)

# Etiket ve özellik listesi API'leri
@app.route('/api/blog-tags')
@login_required
def api_get_blog_tags():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        conn = get_db_connection()
        tags = conn.execute('SELECT * FROM blog_tags WHERE is_active = 1 ORDER BY name').fetchall()
        conn.close()
        
        return jsonify({
            'success': True,
            'tags': [{
                'id': tag['id'],
                'name': tag['name'],
                'color': tag['color'],
                'description': tag['description'],
                'is_active': bool(tag['is_active'])
            } for tag in tags]
        })
        
    except Exception as e:
        print(f"Etiketler getirme hatası: {str(e)}")
        return jsonify({'success': False, 'message': f'Etiketler getirilemedi: {str(e)}'}), 500

@app.route('/api/blog-features')
@login_required
def api_get_blog_features():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        conn = get_db_connection()
        features = conn.execute('SELECT * FROM blog_features WHERE is_active = 1 ORDER BY name').fetchall()
        conn.close()
        
        return jsonify({
            'success': True,
            'features': [{
                'id': feature['id'],
                'name': feature['name'],
                'icon': feature['icon'],
                'description': feature['description'],
                'is_active': bool(feature['is_active'])
            } for feature in features]
        })
        
    except Exception as e:
        print(f"Özellikler getirme hatası: {str(e)}")
        return jsonify({'success': False, 'message': f'Özellikler getirilemedi: {str(e)}'}), 500

# Etiket API'leri
@app.route('/api/add-blog-tag', methods=['POST'])
@login_required
def api_add_blog_tag():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        color = data.get('color', 'bg-primary')
        description = data.get('description', '').strip()
        is_active = data.get('is_active', True)
        
        if not name:
            return jsonify({'success': False, 'message': 'Etiket adı gerekli'}), 400
        
        conn = get_db_connection()
        
        # Aynı isimde etiket var mı kontrol et
        existing = conn.execute('SELECT id FROM blog_tags WHERE name = ?', (name,)).fetchone()
        if existing:
            conn.close()
            return jsonify({'success': False, 'message': 'Bu isimde bir etiket zaten mevcut'}), 400
        
        conn.execute('''
            INSERT INTO blog_tags (name, color, description, is_active)
            VALUES (?, ?, ?, ?)
        ''', (name, color, description, is_active))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Etiket başarıyla eklendi!'})
        
    except Exception as e:
        print(f"Etiket ekleme hatası: {str(e)}")
        return jsonify({'success': False, 'message': f'Etiket eklenemedi: {str(e)}'}), 500

@app.route('/api/update-blog-tag', methods=['POST'])
@login_required
def api_update_blog_tag():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        data = request.get_json()
        tag_id = data.get('tag_id')
        name = data.get('name', '').strip()
        color = data.get('color', 'bg-primary')
        description = data.get('description', '').strip()
        is_active = data.get('is_active', True)
        
        if not tag_id or not name:
            return jsonify({'success': False, 'message': 'Etiket ID ve adı gerekli'}), 400
        
        conn = get_db_connection()
        
        # Aynı isimde başka etiket var mı kontrol et
        existing = conn.execute('SELECT id FROM blog_tags WHERE name = ? AND id != ?', (name, tag_id)).fetchone()
        if existing:
            conn.close()
            return jsonify({'success': False, 'message': 'Bu isimde başka bir etiket zaten mevcut'}), 400
        
        conn.execute('''
            UPDATE blog_tags 
            SET name = ?, color = ?, description = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (name, color, description, is_active, tag_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Etiket başarıyla güncellendi!'})
        
    except Exception as e:
        print(f"Etiket güncelleme hatası: {str(e)}")
        return jsonify({'success': False, 'message': f'Etiket güncellenemedi: {str(e)}'}), 500

@app.route('/api/blog-tag/<int:tag_id>')
@login_required
def api_get_blog_tag(tag_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        conn = get_db_connection()
        tag = conn.execute('SELECT * FROM blog_tags WHERE id = ?', (tag_id,)).fetchone()
        conn.close()
        
        if tag:
            return jsonify({
                'success': True,
                'tag': {
                    'id': tag['id'],
                    'name': tag['name'],
                    'color': tag['color'],
                    'description': tag['description'],
                    'is_active': bool(tag['is_active'])
                }
            })
        else:
            return jsonify({'success': False, 'message': 'Etiket bulunamadı'}), 404
            
    except Exception as e:
        print(f"Etiket getirme hatası: {str(e)}")
        return jsonify({'success': False, 'message': f'Etiket getirilemedi: {str(e)}'}), 500

@app.route('/api/delete-blog-tag', methods=['POST'])
@login_required
def api_delete_blog_tag():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        data = request.get_json()
        tag_id = data.get('tag_id')
        
        if not tag_id:
            return jsonify({'success': False, 'message': 'Etiket ID gerekli'}), 400
        
        conn = get_db_connection()
        conn.execute('DELETE FROM blog_tags WHERE id = ?', (tag_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Etiket başarıyla silindi!'})
        
    except Exception as e:
        print(f"Etiket silme hatası: {str(e)}")
        return jsonify({'success': False, 'message': f'Etiket silinemedi: {str(e)}'}), 500

# Özellik API'leri
@app.route('/api/add-blog-feature', methods=['POST'])
@login_required
def api_add_blog_feature():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        icon = data.get('icon', 'fas fa-check')
        description = data.get('description', '').strip()
        is_active = data.get('is_active', True)
        
        if not name:
            return jsonify({'success': False, 'message': 'Özellik adı gerekli'}), 400
        
        conn = get_db_connection()
        
        # Aynı isimde özellik var mı kontrol et
        existing = conn.execute('SELECT id FROM blog_features WHERE name = ?', (name,)).fetchone()
        if existing:
            conn.close()
            return jsonify({'success': False, 'message': 'Bu isimde bir özellik zaten mevcut'}), 400
        
        conn.execute('''
            INSERT INTO blog_features (name, icon, description, is_active)
            VALUES (?, ?, ?, ?)
        ''', (name, icon, description, is_active))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Özellik başarıyla eklendi!'})
        
    except Exception as e:
        print(f"Özellik ekleme hatası: {str(e)}")
        return jsonify({'success': False, 'message': f'Özellik eklenemedi: {str(e)}'}), 500

@app.route('/api/update-blog-feature', methods=['POST'])
@login_required
def api_update_blog_feature():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        data = request.get_json()
        feature_id = data.get('feature_id')
        name = data.get('name', '').strip()
        icon = data.get('icon', 'fas fa-check')
        description = data.get('description', '').strip()
        is_active = data.get('is_active', True)
        
        if not feature_id or not name:
            return jsonify({'success': False, 'message': 'Özellik ID ve adı gerekli'}), 400
        
        conn = get_db_connection()
        
        # Aynı isimde başka özellik var mı kontrol et
        existing = conn.execute('SELECT id FROM blog_features WHERE name = ? AND id != ?', (name, feature_id)).fetchone()
        if existing:
            conn.close()
            return jsonify({'success': False, 'message': 'Bu isimde başka bir özellik zaten mevcut'}), 400
        
        conn.execute('''
            UPDATE blog_features 
            SET name = ?, icon = ?, description = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (name, icon, description, is_active, feature_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Özellik başarıyla güncellendi!'})
        
    except Exception as e:
        print(f"Özellik güncelleme hatası: {str(e)}")
        return jsonify({'success': False, 'message': f'Özellik güncellenemedi: {str(e)}'}), 500

@app.route('/api/blog-feature/<int:feature_id>')
@login_required
def api_get_blog_feature(feature_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        conn = get_db_connection()
        feature = conn.execute('SELECT * FROM blog_features WHERE id = ?', (feature_id,)).fetchone()
        conn.close()
        
        if feature:
            return jsonify({
                'success': True,
                'feature': {
                    'id': feature['id'],
                    'name': feature['name'],
                    'icon': feature['icon'],
                    'description': feature['description'],
                    'is_active': bool(feature['is_active'])
                }
            })
        else:
            return jsonify({'success': False, 'message': 'Özellik bulunamadı'}), 404
            
    except Exception as e:
        print(f"Özellik getirme hatası: {str(e)}")
        return jsonify({'success': False, 'message': f'Özellik getirilemedi: {str(e)}'}), 500

@app.route('/api/delete-blog-feature', methods=['POST'])
@login_required
def api_delete_blog_feature():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        data = request.get_json()
        feature_id = data.get('feature_id')
        
        if not feature_id:
            return jsonify({'success': False, 'message': 'Özellik ID gerekli'}), 400
        
        conn = get_db_connection()
        conn.execute('DELETE FROM blog_features WHERE id = ?', (feature_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Özellik başarıyla silindi!'})
        
    except Exception as e:
        print(f"Özellik silme hatası: {str(e)}")
        return jsonify({'success': False, 'message': f'Özellik silinemedi: {str(e)}'}), 500

# Admin Ayarları Kaydetme
@app.route('/api/save-settings', methods=['POST'])
@login_required
def api_save_settings():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        data = request.get_json()
        conn = get_db_connection()
        
        for key, value in data.items():
            # Önce ayarın var olup olmadığını kontrol et
            existing = conn.execute('SELECT id FROM site_settings WHERE setting_key = ?', (key,)).fetchone()
            
            if existing:
                # Ayar varsa güncelle
                conn.execute('''
                    UPDATE site_settings 
                    SET setting_value = ?, updated_at = CURRENT_TIMESTAMP 
                    WHERE setting_key = ?
                ''', (value, key))
            else:
                # Ayar yoksa ekle
                conn.execute('''
                    INSERT INTO site_settings (setting_key, setting_value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (key, value))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Ayarlar başarıyla kaydedildi'})
        
    except Exception as e:
        print(f"Ayar kaydetme hatası: {str(e)}")
        return jsonify({'success': False, 'message': f'Bir hata oluştu: {str(e)}'}), 500

@app.route('/admin/musteriler')
@login_required
def admin_customers():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    
    # Müşteri listesi (kayıtlı kullanıcılar - admin dahil)
    customers = conn.execute('''
        SELECT u.*, 
               COUNT(o.id) as order_count,
               COALESCE(SUM(o.total_amount), 0) as total_spent,
               MAX(o.created_at) as last_order_date
        FROM users u
        LEFT JOIN orders o ON u.id = o.user_id
        GROUP BY u.id
        ORDER BY u.created_at DESC
    ''').fetchall()
    
    # Ziyaretçi listesi (kayıt olmayan kullanıcılar)
    visitors = conn.execute('''
        SELECT 
            ip_address as username,
            'gmail' as email,
            'Ziyaretçi' as first_name,
            '' as last_name,
            ip_address,
            0 as order_count,
            0 as total_spent,
            NULL as last_order_date,
            first_visit as created_at,
            visit_count,
            last_visit,
            page_visited,
            cookie_consent,
            is_blocked,
            blocked_reason,
            blocked_at
        FROM visitors
        ORDER BY last_visit DESC
    ''').fetchall()
    
    # Tüm kullanıcıları birleştir
    all_customers = list(customers) + list(visitors)
    
    # İstatistikler
    stats = {
        'total_customers': len(customers),
        'total_visitors': len(visitors),
        'total_users': len(all_customers),
        'active_customers': len([c for c in customers if c['order_count'] > 0]),
        'total_revenue': sum(c['total_spent'] for c in customers),
        'new_customers_this_month': len([c for c in customers if c['created_at'] and c['created_at'][:7] == datetime.now().strftime('%Y-%m')])
    }
    
    conn.close()
    
    return render_template('admin/customers.html', customers=all_customers, visitors=visitors, stats=stats)

# Admin - Sipariş Yönetimi
@app.route('/admin/siparisler')
@login_required
def admin_orders():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    orders = conn.execute('''
        SELECT o.*, u.first_name, u.last_name, u.email 
        FROM orders o 
        LEFT JOIN users u ON o.user_id = u.id 
        ORDER BY o.created_at DESC
    ''').fetchall()
    
    # Her sipariş için öğeleri al
    orders_with_items = []
    for order in orders:
        # Sipariş verilerini manuel olarak al
        order_data = {
            'id': order['id'],
            'order_number': order['order_number'],
            'user_id': order['user_id'],
            'total_amount': order['total_amount'],
            'status': order['status'],
            'payment_status': order['payment_status'],
            'shipping_address': order['shipping_address'],
            'billing_address': order['billing_address'],
            'phone': order['phone'],
            'notes': order['notes'],
            'created_at': order['created_at'],
            'updated_at': order['updated_at'],
            'first_name': order['first_name'],
            'last_name': order['last_name'],
            'email': order['email']
        }
        
        # Sipariş öğelerini al
        items = conn.execute('''
            SELECT oi.*, p.name as product_name
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = ?
        ''', (order['id'],)).fetchall()
        order_data['order_items'] = [dict(item) for item in items]
        orders_with_items.append(order_data)
    
    conn.close()
    
    # Debug için log ekle
    print(f"DEBUG: {len(orders_with_items)} sipariş bulundu")
    for order in orders_with_items:
        print(f"  - Sipariş: {order['order_number']}, Durum: {order['status']}, Tutar: {order['total_amount']}")
    
    return render_template('admin/orders.html', orders=orders_with_items)

# Admin - Sipariş Durumu Güncelleme
@app.route('/admin/siparisler/durum-guncelle', methods=['POST'])
@login_required
def admin_update_order_status():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    order_id = request.form.get('order_id')
    new_status = request.form.get('status')
    
    if not order_id or not new_status:
        return jsonify({'error': 'Missing parameters'}), 400
    
    conn = get_db_connection()
    try:
        # Sipariş durumunu güncelle
        conn.execute('''
            UPDATE orders 
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_status, order_id))
        conn.commit()
        
        return jsonify({'success': True, 'message': 'Sipariş durumu güncellendi'})
    except Exception as e:
        print(f"ERROR: Sipariş durumu güncellenirken hata: {e}")
        return jsonify({'error': 'Database error'}), 500
    finally:
        conn.close()

# Admin - Sipariş Detayları
@app.route('/admin/siparisler/detay/<int:order_id>')
@login_required
def admin_order_detail(order_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    
    # Sipariş bilgilerini al
    order = conn.execute('''
        SELECT o.*, u.first_name as user_first_name, u.last_name as user_last_name, u.email as user_email, u.phone as user_phone
        FROM orders o 
        LEFT JOIN users u ON o.user_id = u.id 
        WHERE o.id = ?
    ''', (order_id,)).fetchone()
    
    if not order:
        conn.close()
        return jsonify({'error': 'Sipariş bulunamadı'}), 404
    
    # Sipariş öğelerini al
    items = conn.execute('''
        SELECT oi.*, p.name as product_name, p.price as product_price
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = ?
    ''', (order_id,)).fetchall()
    
    conn.close()
    
    # Veriyi dict'e çevir
    order_data = dict(order)
    order_data['items'] = [dict(item) for item in items]
    
    return jsonify(order_data)

# Admin - Sipariş Yazdırma
@app.route('/admin/siparisler/yazdir/<int:order_id>')
@login_required
def admin_print_order(order_id):
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    
    # Sipariş bilgilerini al
    order = conn.execute('''
        SELECT o.*, u.first_name as user_first_name, u.last_name as user_last_name, u.email as user_email, u.phone as user_phone
        FROM orders o 
        LEFT JOIN users u ON o.user_id = u.id 
        WHERE o.id = ?
    ''', (order_id,)).fetchone()
    
    if not order:
        conn.close()
        flash('Sipariş bulunamadı!', 'error')
        return redirect(url_for('admin_orders'))
    
    # Sipariş öğelerini al
    items = conn.execute('''
        SELECT oi.*, p.name as product_name, p.price as product_price
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = ?
    ''', (order_id,)).fetchall()
    
    conn.close()
    
    # Veriyi dict'e çevir
    order_data = dict(order)
    order_data['items'] = [dict(item) for item in items]
    
    return render_template('admin/print_order.html', order=order_data)

# API Endpoints
@app.route('/api/cart/count')
def api_cart_count():
    if current_user.is_authenticated:
        # Giriş yapmış kullanıcı için veritabanından say
        # Demo için basit sayı döndür
        if current_user.username in ['admin', 'test']:
            return jsonify({'count': 0})
        
        conn = get_db_connection()
        count = conn.execute('SELECT COUNT(*) as count FROM cart_items WHERE user_id = ?', (current_user.id,)).fetchone()['count']
        conn.close()
        return jsonify({'count': count})
    else:
        # Misafir kullanıcı için session'dan say
        session_cart = session.get('cart', {})
        count = sum(session_cart.values()) if session_cart else 0
        return jsonify({'count': count})

@app.route('/api/user/check')
@login_required
def api_user_check():
    has_address = bool(current_user.address)
    return jsonify({'has_address': has_address})

# API - Çerez durumu güncelle
@app.route('/api/cookie-consent', methods=['POST'])
def api_cookie_consent():
    try:
        data = request.get_json()
        consent = data.get('consent')  # 'accepted' veya 'rejected'
        ip_address = request.remote_addr
        
        if consent not in ['accepted', 'rejected']:
            return jsonify({'success': False, 'message': 'Geçersiz çerez durumu'}), 400
        
        conn = get_db_connection()
        
        # Kullanıcı giriş yapmışsa users tablosunu güncelle
        if current_user.is_authenticated:
            conn.execute(
                'UPDATE users SET cookie_consent = ? WHERE id = ?',
                (consent, current_user.id)
            )
        else:
            # Ziyaretçi ise visitors tablosunu güncelle
            conn.execute(
                'UPDATE visitors SET cookie_consent = ? WHERE ip_address = ?',
                (consent, ip_address)
            )
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Çerez durumu güncellendi'})
        
    except Exception as e:
        print(f"Çerez durumu güncelleme hatası: {str(e)}")
        return jsonify({'success': False, 'message': 'Bir hata oluştu'}), 500

# API - IP Engelleme
@app.route('/api/block-ip', methods=['POST'])
@login_required
def api_block_ip():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        data = request.get_json()
        ip_address = data.get('ip_address')
        reason = data.get('reason', 'Spam/İstenmeyen davranış')
        
        if not ip_address:
            return jsonify({'success': False, 'message': 'IP adresi gerekli'}), 400
        
        conn = get_db_connection()
        
        # IP'yi engelle
        conn.execute('''
            UPDATE visitors 
            SET is_blocked = 1, blocked_reason = ?, blocked_at = CURRENT_TIMESTAMP 
            WHERE ip_address = ?
        ''', (reason, ip_address))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'IP {ip_address} engellendi'})
        
    except Exception as e:
        print(f"IP engelleme hatası: {str(e)}")
        return jsonify({'success': False, 'message': 'Bir hata oluştu'}), 500

# API - IP Engelleme Kaldırma
@app.route('/api/unblock-ip', methods=['POST'])
@login_required
def api_unblock_ip():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        data = request.get_json()
        ip_address = data.get('ip_address')
        
        if not ip_address:
            return jsonify({'success': False, 'message': 'IP adresi gerekli'}), 400
        
        conn = get_db_connection()
        
        # IP engellemesini kaldır
        conn.execute('''
            UPDATE visitors 
            SET is_blocked = 0, blocked_reason = NULL, blocked_at = NULL 
            WHERE ip_address = ?
        ''', (ip_address,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'IP {ip_address} engeli kaldırıldı'})
        
    except Exception as e:
        print(f"IP engel kaldırma hatası: {str(e)}")
        return jsonify({'success': False, 'message': 'Bir hata oluştu'}), 500

# Arama sayfası


# Favicon route
@app.route('/favicon.ico')
def favicon():
    return '', 204  # No content

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return render_template('error.html', error_code=404, error_message='Sayfa bulunamadı'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', error_code=500, error_message='Sunucu hatası'), 500

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(error):
    flash('Dosya boyutu çok büyük! Maksimum 16MB yükleyebilirsiniz.', 'error')
    return redirect(request.url)

# Production için güvenlik başlıkları (yukarıdaki after_request ile birleştirildi)

if __name__ == '__main__':
    # Veritabanını başlat
    try:
        init_db()
        app.logger.info("Veritabanı başarıyla başlatıldı")
    except Exception as e:
        app.logger.error(f"Veritabanı başlatma hatası: {e}")
    
    # Hosting ortamında port environment variable'dan alınır
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    # Production'da debug=False
    if os.environ.get('FLASK_ENV') == 'production':
        debug = False
    
    app.run(debug=debug, host='0.0.0.0', port=port)

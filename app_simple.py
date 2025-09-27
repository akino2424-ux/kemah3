from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime
import os
import sqlite3
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kemah-dogal-urunler-2025'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Uygulama uzantılarını başlat
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Bu sayfaya erişmek için giriş yapmalısınız.'

# Upload klasörünü oluştur
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Veritabanı bağlantısı
def get_db_connection():
    conn = sqlite3.connect('kemah.db')
    conn.row_factory = sqlite3.Row
    return conn

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

# Veritabanını başlat
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
            is_admin BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            description TEXT,
            image TEXT,
            parent_id INTEGER,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            description TEXT,
            short_description TEXT,
            price REAL NOT NULL,
            stock_quantity INTEGER DEFAULT 0,
            image TEXT,
            weight TEXT,
            brand TEXT,
            is_active BOOLEAN DEFAULT 1,
            is_featured BOOLEAN DEFAULT 0,
            category_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories (id)
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
            user_id INTEGER NOT NULL,
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
    
    # Admin kullanıcı oluştur
    admin_user = conn.execute('SELECT * FROM users WHERE username = ?', ('admin',)).fetchone()
    if not admin_user:
        hashed_password = bcrypt.generate_password_hash('admin123').decode('utf-8')
        conn.execute('''
            INSERT INTO users (username, email, password, first_name, last_name, is_admin)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ('admin', 'admin@kemah.com.tr', hashed_password, 'Admin', 'User', 1))
    
    # Test kullanıcısı oluştur
    test_user = conn.execute('SELECT * FROM users WHERE username = ?', ('test',)).fetchone()
    if not test_user:
        hashed_password = bcrypt.generate_password_hash('test123').decode('utf-8')
        conn.execute('''
            INSERT INTO users (username, email, password, first_name, last_name, is_admin)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ('test', 'test@kemah.com.tr', hashed_password, 'Test', 'User', 0))
    
    # Kategoriler oluştur
    categories_data = [
        ('ARI ÜRÜNLERİ', 'ari-urunleri', 'Arı ürünleri kategorisi', None),
        ('BAL GRUBU', 'bal-grubu', 'Bal grubu kategorisi', None),
        ('SİRKE GRUBU', 'sirke-grubu', 'Sirke grubu kategorisi', None),
        ('SÜT ÜRÜNLERİ', 'sut-urunleri', 'Süt ürünleri kategorisi', None),
        ('DOĞAL ÜRÜNLER', 'dogal-urunler', 'Doğal ürünler kategorisi', None),
        ('BAKLİYAT', 'bakliyat', 'Bakliyat kategorisi', None)
    ]
    
    for cat_data in categories_data:
        existing = conn.execute('SELECT * FROM categories WHERE slug = ?', (cat_data[1],)).fetchone()
        if not existing:
            conn.execute('''
                INSERT INTO categories (name, slug, description, parent_id)
                VALUES (?, ?, ?, ?)
            ''', cat_data)
    
    # Örnek ürünler oluştur
    products_data = [
        ('KÖY SALAMURA PEYNİRİ', 'koy-salamura-peyniri', 'Doğal köy salamura peyniri', 'Doğal köy salamura peyniri', 225.00, 50, None, '500g', 'Kemah', 1, 1, 4),
        ('ERZİNCAN TULUM PEYNİRİ 900 Gr', 'erzincan-tulum-peyniri-900gr', 'Geleneksel Erzincan tulum peyniri', 'Geleneksel Erzincan tulum peyniri', 380.00, 30, None, '900g', 'Kemah', 1, 1, 4),
        ('GENDİME(YARMA)', 'gendime-yarma', 'Doğal gendime yarma', 'Doğal gendime yarma', 40.00, 100, None, '1kg', 'Kemah', 1, 1, 6),
        ('KAYSI KURUSU', 'kaysi-kurusu', 'Doğal kaysı kurusu', 'Doğal kaysı kurusu', 200.00, 75, None, '500g', 'Kemah', 1, 1, 5),
        ('DUT KURUSU', 'dut-kurusu', 'Doğal dut kurusu', 'Doğal dut kurusu', 250.00, 60, None, '500g', 'Kemah', 1, 1, 5),
        ('TEREYAĞI', 'tereyagi', 'Doğal tereyağı', 'Doğal tereyağı', 425.00, 25, None, '500g', 'Kemah', 1, 1, 4)
    ]
    
    for prod_data in products_data:
        existing = conn.execute('SELECT * FROM products WHERE slug = ?', (prod_data[1],)).fetchone()
        if not existing:
            conn.execute('''
                INSERT INTO products (name, slug, description, short_description, price, stock_quantity, image, weight, brand, is_active, is_featured, category_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', prod_data)
    
    # Örnek blog yazıları
    blogs_data = [
        ('ALIÇ SİRKESİ FAYDALARI', 'alic-sirkesi-faydalari', 'Alıç sirkesi üzerine detaylı bilgiler...', 'Alıç sirkesi faydaları hakkında bilmeniz gerekenler'),
        ('ARCILIK SEKTÖRÜNDE GÜVEN', 'arilik-sektorunde-guven', 'Arı ürünlerini güvenli tüketebilir miyiz...', 'Arıcılık sektöründe güven konusu'),
        ('SİRKENİN SAĞLIK ÜZERİNE ETKİLERİ', 'sirkesin-saglik-uzerine-etkileri', 'Sirkenin sağlık üzere etkileri...', 'Sirkenin sağlık üzerine olumlu etkileri')
    ]
    
    for blog_data in blogs_data:
        existing = conn.execute('SELECT * FROM blogs WHERE slug = ?', (blog_data[1],)).fetchone()
        if not existing:
            conn.execute('''
                INSERT INTO blogs (title, slug, content, excerpt)
                VALUES (?, ?, ?, ?)
            ''', blog_data)
    
    conn.commit()
    conn.close()
    print("Veritabanı başarıyla oluşturuldu ve örnek veriler eklendi!")

# Ana Sayfa
@app.route('/')
def index():
    conn = get_db_connection()
    
    # Öne çıkan ürünler
    featured_products = conn.execute('''
        SELECT p.*, c.name as category_name 
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
        SELECT p.*, c.name as category_name 
        FROM products p 
        JOIN categories c ON p.category_id = c.id 
        WHERE p.is_active = 1 
        ORDER BY p.created_at DESC 
        LIMIT 6
    ''').fetchall()
    
    # Blog yazıları
    blogs = conn.execute('''
        SELECT * FROM blogs 
        WHERE is_published = 1 
        ORDER BY created_at DESC 
        LIMIT 3
    ''').fetchall()
    
    conn.close()
    
    return render_template('index.html', 
                         featured_products=featured_products,
                         categories=categories,
                         recent_products=recent_products,
                         blogs=blogs)

# Kullanıcı Kayıt
@app.route('/kayit', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        phone = request.form.get('phone')
        
        conn = get_db_connection()
        
        # Kullanıcı var mı kontrol et
        existing_user = conn.execute('SELECT * FROM users WHERE username = ? OR email = ?', (username, email)).fetchone()
        
        if existing_user:
            flash('Bu kullanıcı adı veya e-posta adresi zaten kullanılıyor!', 'error')
            conn.close()
            return render_template('register.html')
        
        # Yeni kullanıcı oluştur
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        conn.execute('''
            INSERT INTO users (username, email, password, first_name, last_name, phone)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (username, email, hashed_password, first_name, last_name, phone))
        
        conn.commit()
        conn.close()
        
        flash('Kayıt başarılı! Giriş yapabilirsiniz.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

# Kullanıcı Giriş
@app.route('/giris', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user_data = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user_data and bcrypt.check_password_hash(user_data['password'], password):
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
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('Kullanıcı adı veya şifre hatalı!', 'error')
    
    return render_template('login.html')

# Çıkış
@app.route('/cikis')
@login_required
def logout():
    logout_user()
    flash('Başarıyla çıkış yaptınız!', 'info')
    return redirect(url_for('index'))

# Blog
@app.route('/blog')
def blog_list():
    conn = get_db_connection()
    blogs = conn.execute('''
        SELECT * FROM blogs 
        WHERE is_published = 1 
        ORDER BY created_at DESC
    ''').fetchall()
    conn.close()
    return render_template('blog_list.html', blogs=blogs)

@app.route('/blog/<slug>')
def blog_detail(slug):
    conn = get_db_connection()
    blog = conn.execute('SELECT * FROM blogs WHERE slug = ? AND is_published = 1', (slug,)).fetchone()
    conn.close()
    
    if not blog:
        flash('Blog yazısı bulunamadı!', 'error')
        return redirect(url_for('blog_list'))
    
    return render_template('blog_detail.html', blog=blog)

# İletişim
@app.route('/iletisim')
def contact():
    return render_template('contact.html')

# Admin Panel
@app.route('/admin')
@login_required
def admin_dashboard():
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
        SELECT o.*, u.first_name, u.last_name 
        FROM orders o 
        JOIN users u ON o.user_id = u.id 
        ORDER BY o.created_at DESC 
        LIMIT 10
    ''').fetchall()
    
    conn.close()
    
    return render_template('admin/dashboard.html', stats=stats, recent_orders=recent_orders)

# API Endpoints
@app.route('/api/cart/count')
@login_required
def api_cart_count():
    conn = get_db_connection()
    count = conn.execute('SELECT COUNT(*) as count FROM cart_items WHERE user_id = ?', (current_user.id,)).fetchone()['count']
    conn.close()
    return jsonify({'count': count})

@app.route('/api/user/check')
@login_required
def api_user_check():
    has_address = bool(current_user.address)
    return jsonify({'has_address': has_address})

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

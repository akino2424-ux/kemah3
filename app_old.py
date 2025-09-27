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

# Ana Sayfa
@app.route('/')
def index():
    featured_products = Product.query.filter_by(is_featured=True, is_active=True).limit(8).all()
    categories = Category.query.filter_by(is_active=True, parent_id=None).all()
    recent_products = Product.query.filter_by(is_active=True).order_by(Product.created_at.desc()).limit(6).all()
    blogs = Blog.query.filter_by(is_published=True).order_by(Blog.created_at.desc()).limit(3).all()
    
    return render_template('index.html', 
                         featured_products=featured_products,
                         categories=categories,
                         recent_products=recent_products,
                         blogs=blogs)

# Ürün Kategorileri
@app.route('/kategori/<slug>')
def category(slug):
    category = Category.query.filter_by(slug=slug, is_active=True).first_or_404()
    products = Product.query.filter_by(category_id=category.id, is_active=True).all()
    
    return render_template('category.html', category=category, products=products)

# Ürün Detayı
@app.route('/urun/<slug>')
def product_detail(slug):
    product = Product.query.filter_by(slug=slug, is_active=True).first_or_404()
    related_products = Product.query.filter(
        Product.category_id == product.category_id,
        Product.id != product.id,
        Product.is_active == True
    ).limit(4).all()
    
    return render_template('product_detail.html', product=product, related_products=related_products)

# Sepet
@app.route('/sepet')
@login_required
def cart():
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.quantity * item.product.price for item in cart_items)
    
    return render_template('cart.html', cart_items=cart_items, total=total)

# Sepete Ekleme
@app.route('/sepet/ekle', methods=['POST'])
@login_required
def add_to_cart():
    product_id = request.form.get('product_id')
    quantity = int(request.form.get('quantity', 1))
    
    product = Product.query.get_or_404(product_id)
    
    # Mevcut sepet öğesini kontrol et
    existing_item = CartItem.query.filter_by(
        user_id=current_user.id, 
        product_id=product_id
    ).first()
    
    if existing_item:
        existing_item.quantity += quantity
    else:
        cart_item = CartItem(
            user_id=current_user.id,
            product_id=product_id,
            quantity=quantity
        )
        db.session.add(cart_item)
    
    db.session.commit()
    flash('Ürün sepete eklendi!', 'success')
    return redirect(url_for('cart'))

# Sepetten Çıkarma
@app.route('/sepet/cikar/<int:item_id>', methods=['POST'])
@login_required
def remove_from_cart(item_id):
    cart_item = CartItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    db.session.delete(cart_item)
    db.session.commit()
    flash('Ürün sepetten çıkarıldı!', 'info')
    return redirect(url_for('cart'))

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
        
        # Kullanıcı var mı kontrol et
        if User.query.filter_by(username=username).first():
            flash('Bu kullanıcı adı zaten kullanılıyor!', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Bu e-posta adresi zaten kullanılıyor!', 'error')
            return render_template('register.html')
        
        # Yeni kullanıcı oluştur
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User(
            username=username,
            email=email,
            password=hashed_password,
            first_name=first_name,
            last_name=last_name,
            phone=phone
        )
        
        db.session.add(user)
        db.session.commit()
        
        flash('Kayıt başarılı! Giriş yapabilirsiniz.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

# Kullanıcı Giriş
@app.route('/giris', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and bcrypt.check_password_hash(user.password, password):
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
    blogs = Blog.query.filter_by(is_published=True).order_by(Blog.created_at.desc()).all()
    return render_template('blog_list.html', blogs=blogs)

@app.route('/blog/<slug>')
def blog_detail(slug):
    blog = Blog.query.filter_by(slug=slug, is_published=True).first_or_404()
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
    
    stats = {
        'total_products': Product.query.count(),
        'total_orders': Order.query.count(),
        'total_users': User.query.count(),
        'total_categories': Category.query.count()
    }
    
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
    
    return render_template('admin/dashboard.html', stats=stats, recent_orders=recent_orders)

# Admin - Ürün Yönetimi
@app.route('/admin/urunler')
@login_required
def admin_products():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    products = Product.query.all()
    return render_template('admin/products.html', products=products)

@app.route('/admin/urunler/ekle', methods=['GET', 'POST'])
@login_required
def admin_add_product():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name']
        slug = request.form['slug']
        description = request.form['description']
        short_description = request.form['short_description']
        price = float(request.form['price'])
        stock_quantity = int(request.form['stock_quantity'])
        category_id = int(request.form['category_id'])
        weight = request.form.get('weight')
        brand = request.form.get('brand')
        is_featured = 'is_featured' in request.form
        
        product = Product(
            name=name,
            slug=slug,
            description=description,
            short_description=short_description,
            price=price,
            stock_quantity=stock_quantity,
            category_id=category_id,
            weight=weight,
            brand=brand,
            is_featured=is_featured
        )
        
        db.session.add(product)
        db.session.commit()
        
        flash('Ürün başarıyla eklendi!', 'success')
        return redirect(url_for('admin_products'))
    
    categories = Category.query.filter_by(is_active=True).all()
    return render_template('admin/add_product.html', categories=categories)

# Admin - Kategori Yönetimi
@app.route('/admin/kategoriler')
@login_required
def admin_categories():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    categories = Category.query.all()
    return render_template('admin/categories.html', categories=categories)

# Admin - Sipariş Yönetimi
@app.route('/admin/siparisler')
@login_required
def admin_orders():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('admin/orders.html', orders=orders)

# API Endpoints
@app.route('/api/cart/count')
@login_required
def api_cart_count():
    count = CartItem.query.filter_by(user_id=current_user.id).count()
    return jsonify({'count': count})

@app.route('/api/user/check')
@login_required
def api_user_check():
    has_address = bool(current_user.address)
    return jsonify({'has_address': has_address})

@app.route('/sepet/guncelle', methods=['POST'])
@login_required
def update_cart_item():
    item_id = request.form.get('item_id')
    quantity = int(request.form.get('quantity', 1))
    
    cart_item = CartItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    
    if quantity <= 0:
        db.session.delete(cart_item)
    else:
        cart_item.quantity = quantity
    
    db.session.commit()
    return redirect(url_for('cart'))

# Admin API Endpoints
@app.route('/admin/urunler/sil/<int:product_id>', methods=['POST'])
@login_required
def admin_delete_product(product_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/kategoriler/sil/<int:category_id>', methods=['POST'])
@login_required
def admin_delete_category(category_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    category = Category.query.get_or_404(category_id)
    db.session.delete(category)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/kategoriler/ekle', methods=['POST'])
@login_required
def admin_add_category():
    if not current_user.is_admin:
        flash('Bu sayfaya erişim yetkiniz yok!', 'error')
        return redirect(url_for('index'))
    
    name = request.form['name']
    slug = request.form['slug']
    description = request.form.get('description')
    parent_id = request.form.get('parent_id') or None
    is_active = 'is_active' in request.form
    
    category = Category(
        name=name,
        slug=slug,
        description=description,
        parent_id=parent_id,
        is_active=is_active
    )
    
    db.session.add(category)
    db.session.commit()
    
    flash('Kategori başarıyla eklendi!', 'success')
    return redirect(url_for('admin_categories'))

@app.route('/admin/siparisler/durum-guncelle', methods=['POST'])
@login_required
def admin_update_order_status():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    order_id = request.form.get('order_id')
    status = request.form.get('status')
    
    order = Order.query.get_or_404(order_id)
    order.status = status
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/siparisler/detay/<int:order_id>')
@login_required
def admin_order_detail(order_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    order = Order.query.get_or_404(order_id)
    return render_template('admin/order_detail.html', order=order)

@app.route('/admin/siparisler/yazdir/<int:order_id>')
@login_required
def admin_print_order(order_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    order = Order.query.get_or_404(order_id)
    return render_template('admin/print_order.html', order=order)

# Veritabanını başlat
def init_db():
    with app.app_context():
        db.create_all()
        
        # Admin kullanıcı oluştur
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_user = User(
                username='admin',
                email='admin@kemah.com.tr',
                password=bcrypt.generate_password_hash('admin123').decode('utf-8'),
                first_name='Admin',
                last_name='User',
                is_admin=True
            )
            db.session.add(admin_user)
        
        # Kategoriler oluştur
        categories_data = [
            {'name': 'ARI ÜRÜNLERİ', 'slug': 'ari-urunleri', 'children': [
                {'name': 'PERGA', 'slug': 'perga'},
                {'name': 'POLEN', 'slug': 'polen'},
                {'name': 'PROPOLİS', 'slug': 'propolis'}
            ]},
            {'name': 'BAL GRUBU', 'slug': 'bal-grubu', 'children': [
                {'name': 'BAL KARAKOVAN', 'slug': 'bal-karakovan'},
                {'name': 'BAL PETEK', 'slug': 'bal-pekek'},
                {'name': 'BAL SÜZME', 'slug': 'bal-suzme'}
            ]},
            {'name': 'SİRKE GRUBU', 'slug': 'sirke-grubu', 'children': [
                {'name': 'ALIÇ SİRKESİ', 'slug': 'alic-sirkesi'},
                {'name': 'BAL SİRKESİ', 'slug': 'bal-sirkesi'},
                {'name': 'DUT SİRKESİ', 'slug': 'dut-sirkesi'},
                {'name': 'ELMA SİRKESİ', 'slug': 'elma-sirkesi'}
            ]},
            {'name': 'SÜT ÜRÜNLERİ', 'slug': 'sut-urunleri', 'children': [
                {'name': 'TEREYAĞI', 'slug': 'tereyagi'},
                {'name': 'KEMAH TULUM PEYNİRİ', 'slug': 'kemah-tulum-peyniri'},
                {'name': 'SALAMURA PEYNİR', 'slug': 'salamura-peynir'},
                {'name': 'ERZİNCAN TULUM PEYNİRİ', 'slug': 'erzincan-tulum-peyniri'}
            ]},
            {'name': 'DOĞAL ÜRÜNLER', 'slug': 'dogal-urunler', 'children': [
                {'name': 'DUT PEKMEZİ', 'slug': 'dut-pekmezi'},
                {'name': 'DUT KURUSU', 'slug': 'dut-kurusu'},
                {'name': 'KAYSI KURUSU', 'slug': 'kaysi-kurusu'}
            ]},
            {'name': 'BAKLİYAT', 'slug': 'bakliyat', 'children': [
                {'name': 'BULGUR', 'slug': 'bulgur'},
                {'name': 'FASULYE', 'slug': 'fasulye'},
                {'name': 'GENDİME', 'slug': 'gendime'},
                {'name': 'NOHUT', 'slug': 'nohut'}
            ]}
        ]
        
        for cat_data in categories_data:
            parent_cat = Category.query.filter_by(slug=cat_data['slug']).first()
            if not parent_cat:
                parent_cat = Category(
                    name=cat_data['name'],
                    slug=cat_data['slug'],
                    description=f"{cat_data['name']} kategorisi"
                )
                db.session.add(parent_cat)
                db.session.flush()  # ID'yi almak için
            
            for child_data in cat_data.get('children', []):
                child_cat = Category.query.filter_by(slug=child_data['slug']).first()
                if not child_cat:
                    child_cat = Category(
                        name=child_data['name'],
                        slug=child_data['slug'],
                        description=f"{child_data['name']} kategorisi",
                        parent_id=parent_cat.id
                    )
                    db.session.add(child_cat)
        
        # Örnek ürünler oluştur
        sample_products = [
            {'name': 'KÖY SALAMURA PEYNİRİ', 'slug': 'koy-salamura-peyniri', 'price': 225.00, 'category_slug': 'salamura-peynir', 'description': 'Doğal köy salamura peyniri', 'stock': 50},
            {'name': 'ERZİNCAN TULUM PEYNİRİ 900 Gr', 'slug': 'erzincan-tulum-peyniri-900gr', 'price': 380.00, 'category_slug': 'erzincan-tulum-peyniri', 'description': 'Geleneksel Erzincan tulum peyniri', 'stock': 30},
            {'name': 'GENDİME(YARMA)', 'slug': 'gendime-yarma', 'price': 40.00, 'category_slug': 'gendime', 'description': 'Doğal gendime yarma', 'stock': 100},
            {'name': 'KAYSI KURUSU', 'slug': 'kaysi-kurusu', 'price': 200.00, 'category_slug': 'kaysi-kurusu', 'description': 'Doğal kaysı kurusu', 'stock': 75},
            {'name': 'DUT KURUSU', 'slug': 'dut-kurusu', 'price': 250.00, 'category_slug': 'dut-kurusu', 'description': 'Doğal dut kurusu', 'stock': 60},
            {'name': 'TEREYAĞI', 'slug': 'tereyagi', 'price': 425.00, 'category_slug': 'tereyagi', 'description': 'Doğal tereyağı', 'stock': 25}
        ]
        
        for prod_data in sample_products:
            existing_product = Product.query.filter_by(slug=prod_data['slug']).first()
            if not existing_product:
                category = Category.query.filter_by(slug=prod_data['category_slug']).first()
                if category:
                    product = Product(
                        name=prod_data['name'],
                        slug=prod_data['slug'],
                        price=prod_data['price'],
                        description=prod_data['description'],
                        short_description=prod_data['description'][:100],
                        stock_quantity=prod_data['stock'],
                        category_id=category.id,
                        is_featured=True
                    )
                    db.session.add(product)
        
        # Örnek blog yazıları
        sample_blogs = [
            {'title': 'ALIÇ SİRKESİ FAYDALARI', 'slug': 'alic-sirkesi-faydalari', 'content': 'Alıç sirkesi üzerine detaylı bilgiler...', 'excerpt': 'Alıç sirkesi faydaları hakkında bilmeniz gerekenler'},
            {'title': 'ARCILIK SEKTÖRÜNDE GÜVEN', 'slug': 'arilik-sektorunde-guven', 'content': 'Arı ürünlerini güvenli tüketebilir miyiz...', 'excerpt': 'Arıcılık sektöründe güven konusu'},
            {'title': 'SİRKENİN SAĞLIK ÜZERİNE ETKİLERİ', 'slug': 'sirkesin-saglik-uzerine-etkileri', 'content': 'Sirkenin sağlık üzerine etkileri...', 'excerpt': 'Sirkenin sağlık üzerine olumlu etkileri'}
        ]
        
        for blog_data in sample_blogs:
            existing_blog = Blog.query.filter_by(slug=blog_data['slug']).first()
            if not existing_blog:
                blog = Blog(
                    title=blog_data['title'],
                    slug=blog_data['slug'],
                    content=blog_data['content'],
                    excerpt=blog_data['excerpt']
                )
                db.session.add(blog)
        
        db.session.commit()
        print("Veritabanı başarıyla oluşturuldu ve örnek veriler eklendi!")

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

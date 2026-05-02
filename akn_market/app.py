import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, g
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'super-secret-key-change-in-production'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

DATABASE = 'database.db'

# ---------- Database helpers ----------
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            image TEXT,
            kaspi_link TEXT
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )''')
        db.commit()
        # Создаём админа, если ещё нет
        if not db.execute('SELECT id FROM users WHERE username = ?', ('admin',)).fetchone():
            hashed = generate_password_hash('admin123')
            db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', ('admin', hashed))
            db.commit()
            print('Created admin user (login: admin, password: admin123)')

app.teardown_appcontext(close_db)

# ---------- Auth decorator ----------
def login_required(f):
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

# ---------- Routes ----------
@app.route('/')
def index():
    db = get_db()
    products = db.execute('SELECT * FROM products').fetchall()
    return render_template('index.html', products=products)

@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    cart = session.get('cart', {})
    # В корзине храним {product_id: quantity}
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    session['cart'] = cart
    return redirect(url_for('index'))

@app.route('/cart')
def cart():
    cart = session.get('cart', {})
    if not cart:
        return render_template('cart.html', cart_items=[], total=0)

    db = get_db()
    items = []
    total = 0
    for pid, qty in cart.items():
        product = db.execute('SELECT * FROM products WHERE id = ?', (pid,)).fetchone()
        if product:
            subtotal = product['price'] * qty
            total += subtotal
            items.append({
                'id': product['id'],
                'name': product['name'],
                'price': product['price'],
                'image': product['image'],
                'quantity': qty,
                'subtotal': subtotal
            })
    return render_template('cart.html', cart_items=items, total=round(total, 2))

@app.route('/remove_from_cart/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    cart = session.get('cart', {})
    pid = str(product_id)
    if pid in cart:
        del cart[pid]
        session['cart'] = cart
    return redirect(url_for('cart'))

@app.route('/checkout')
def checkout():
    cart = session.get('cart', {})
    if not cart:
        return redirect(url_for('cart'))

    db = get_db()
    items = []
    total = 0
    for pid, qty in cart.items():
        product = db.execute('SELECT * FROM products WHERE id = ?', (pid,)).fetchone()
        if product:
            subtotal = product['price'] * qty
            total += subtotal
            items.append({
                'name': product['name'],
                'price': product['price'],
                'quantity': qty,
                'subtotal': subtotal
            })
    # Формируем сообщение для WhatsApp
    message = "🛒 *Новый заказ в AKN MARKET*\\n\\n"
    for item in items:
        message += f"▪ {item['name']} x{item['quantity']} – {item['subtotal']:.0f} ₸\\n"
    message += f"\\n *Итого: {total:.0f} ₸*"

    whatsapp_url = f"https://wa.me/77001234567?text={message}"
    return render_template('checkout.html', items=items, total=total, whatsapp_url=whatsapp_url)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin_login.html', error='Неверный логин или пароль')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('index'))

@app.route('/admin')
@login_required
def admin_dashboard():
    db = get_db()
    products = db.execute('SELECT * FROM products').fetchall()
    return render_template('admin_dashboard.html', products=products)

@app.route('/admin/add', methods=['POST'])
@login_required
def admin_add_product():
    name = request.form['name']
    description = request.form['description']
    price = float(request.form['price'])
    kaspi_link = request.form['kaspi_link']

    image_file = request.files['image']
    image_filename = None
    if image_file and image_file.filename != '':
        filename = secure_filename(image_file.filename)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image_file.save(image_path)
        image_filename = filename

    db = get_db()
    db.execute('INSERT INTO products (name, description, price, image, kaspi_link) VALUES (?, ?, ?, ?, ?)',
               (name, description, price, image_filename, kaspi_link))
    db.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<int:product_id>', methods=['POST'])
@login_required
def admin_delete_product(product_id):
    db = get_db()
    product = db.execute('SELECT image FROM products WHERE id = ?', (product_id,)).fetchone()
    if product and product['image']:
        img_path = os.path.join(app.config['UPLOAD_FOLDER'], product['image'])
        if os.path.exists(img_path):
            os.remove(img_path)
    db.execute('DELETE FROM products WHERE id = ?', (product_id,))
    db.commit()
    return redirect(url_for('admin_dashboard'))

# ---------- Run ----------
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
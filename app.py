import os
import sqlite3
import requests
import pyotp
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, session, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cortex_pro_2025_key')
app.permanent_session_lifetime = timedelta(days=90)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = os.path.join(BASE_DIR, "lifeos.db")

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# --- GELİŞMİŞ ÜRÜN ÇEKME (Hem Barkod Hem Text Arama İçin) ---
def search_product_online(query, is_barcode=False):
    # Barkodsa direkt ürüne git, Yazıysa aramaya git
    if is_barcode:
        url = f"https://world.openfoodfacts.org/api/v0/product/{query}.json"
    else:
        # Türkiye odaklı arama, JSON formatında, ilk 5 sonuç
        url = f"https://tr.openfoodfacts.org/cgi/search.pl?search_terms={query}&search_simple=1&action=process&json=1&page_size=5"
    
    try:
        res = requests.get(url, timeout=5)
        data = res.json()
        
        results = []
        
        # Eğer Barkodsa tek ürün döner
        if is_barcode:
            if data.get('status') == 1:
                products = [data['product']]
            else:
                return []
        else:
            # Arama ise ürün listesi döner
            products = data.get('products', [])

        for p in products:
            n = p.get('nutriments', {})
            # Sadece kalorisi belli olan ürünleri alalım
            if 'energy-kcal_100g' in n:
                results.append({
                    'name': p.get('product_name', 'Bilinmeyen'),
                    'brand': p.get('brands', ''),
                    'cal': int(n.get('energy-kcal_100g', 0)),
                    'pro': int(n.get('proteins_100g', 0)),
                    'carb': int(n.get('carbohydrates_100g', 0)),
                    'fat': int(n.get('fat_100g', 0))
                })
        return results
    except:
        return []

# ... (Auth ve Init_DB kısımları aynı, yer kaplamasın diye kısalttım, önceki kodun aynısı kalabilir) ...
# Sadece aşağıda Init_DB ve Auth fonksiyonlarının olduğu gibi durduğundan emin ol.
# Eğer sildiysen önceki cevabımdaki init_db ve auth kısımlarını buraya eklemeyi unutma.

def check_auth(username, password):
    if username != 'Muhammed': return False 
    secret = os.environ.get('TOTP_SECRET')
    if not secret: return password == 'admin123'
    return pyotp.TOTP(secret).verify(password)

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('logged_in'): return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response('Giriş Gerekli', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
        session['logged_in'] = True
        return f(*args, **kwargs)
    return decorated

def init_db():
    conn = get_db_connection()
    conn.execute('CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, tarih TEXT, kilo REAL)')
    conn.execute('CREATE TABLE IF NOT EXISTS goals (id INTEGER PRIMARY KEY AUTOINCREMENT, baslik TEXT, kategori TEXT, hedef_tarih TEXT, ilerleme INTEGER DEFAULT 0)')
    conn.execute('''CREATE TABLE IF NOT EXISTS nutrition (
        id INTEGER PRIMARY KEY AUTOINCREMENT, isim TEXT NOT NULL, kalori INTEGER, protein INTEGER, carbs INTEGER, fat INTEGER, category TEXT DEFAULT 'Atıştırmalık', tarih TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS products (barcode TEXT PRIMARY KEY, name TEXT, calories INTEGER, protein INTEGER, carbs INTEGER, fat INTEGER)''')
    conn.commit()
    conn.close()

init_db()

# --- ROTALAR ---

@app.route('/', methods=['GET', 'POST'])
@requires_auth
def dashboard():
    return render_template('dashboard.html', son_kilo="--", hedefler=[])

# --- YENİ: METİN ARAMA ROTASI ---
@app.route('/search_food_api')
@requires_auth
def search_food_api():
    query = request.args.get('q')
    if not query or len(query) < 2: return jsonify([])
    
    # 1. Önce veritabanımızdan ara (Hızlı)
    conn = get_db_connection()
    local_results = conn.execute("SELECT * FROM products WHERE name LIKE ? LIMIT 3", ('%'+query+'%',)).fetchall()
    results = []
    
    for l in local_results:
        results.append({'source':'local', 'name': l['name'], 'cal': l['calories'], 'pro': l['protein'], 'carb': l['carbs'], 'fat': l['fat']})
    conn.close()
    
    # 2. Sonra İnternetten ara
    online_results = search_product_online(query, is_barcode=False)
    
    # Listeleri birleştir
    return jsonify(results + online_results)

# --- BARKOD ROTASI (Güncellendi) ---
@app.route('/get_barcode_data')
@requires_auth
def get_barcode_data():
    code = request.args.get('code')
    results = search_product_online(code, is_barcode=True)
    if results:
        # İlk sonucu dön
        res = results[0]
        return jsonify({'found': True, 'name': res['name'], 'calories': res['cal'], 'protein': res['pro'], 'carbs': res['carb'], 'fat': res['fat']})
    return jsonify({'found': False})

@app.route('/nutrition', methods=['GET', 'POST'])
@requires_auth
def nutrition():
    conn = get_db_connection()
    bugun = datetime.now().strftime("%Y-%m-%d")

    if request.method == 'POST':
        if 'yemek_ekle' in request.form:
            isim = request.form.get('isim')
            # Değerler artık hesaplanmış olarak gelecek
            kal = int(float(request.form.get('kalori') or 0))
            prot = int(float(request.form.get('protein') or 0))
            carb = int(float(request.form.get('carbs') or 0))
            fat = int(float(request.form.get('fat') or 0))
            cat = request.form.get('category')
            
            # Eğer ürün yeni ve barkodu yoksa, ismine göre products tablosuna eklemeyi deneyebiliriz (Opsiyonel)
            # Ama şimdilik sadece nutrition'a ekleyelim, karmaşa olmasın.
            
            conn.execute('''INSERT INTO nutrition (isim, kalori, protein, carbs, fat, category, tarih) 
                            VALUES (?, ?, ?, ?, ?, ?, ?)''', (isim, kal, prot, carb, fat, cat, bugun))
        
        elif 'yemek_sil' in request.form:
            conn.execute('DELETE FROM nutrition WHERE id = ?', (request.form.get('yemek_id'),))
            
        conn.commit()
        return redirect(url_for('nutrition'))

    meals = conn.execute('SELECT * FROM nutrition WHERE tarih = ? ORDER BY id DESC', (bugun,)).fetchall()
    
    totals = {'cal':0, 'pro':0, 'carb':0, 'fat':0}
    for m in meals:
        totals['cal'] += m['kalori'] or 0
        totals['pro'] += m['protein'] or 0
        totals['carb'] += m['carbs'] or 0
        totals['fat'] += m['fat'] or 0

    conn.close()
    return render_template('nutrition.html', meals=meals, totals=totals)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
import os
import sqlite3
import requests
import pyotp
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, session, jsonify

app = Flask(__name__)

# --- GÜVENLİK AYARLARI ---
app.secret_key = os.environ.get('SECRET_KEY', 'gizli_cortex_anahtari_2025')
app.permanent_session_lifetime = timedelta(days=30) # Seni 30 gün hatırlar

# --- VERİTABANI BAĞLANTISI ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = os.path.join(BASE_DIR, "lifeos.db")

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# --- BARKOD MOTORU (Open Food Facts + Yerel Hafıza) ---
def get_product_info(barcode):
    conn = get_db_connection()
    
    # 1. Önce Hafızaya Bak
    local = conn.execute('SELECT * FROM products WHERE barcode = ?', (barcode,)).fetchone()
    if local:
        conn.close()
        return {'found': True, 'source': 'local', 'name': local['name'], 'calories': local['calories'], 'protein': local['protein']}
    
    # 2. Yoksa İnternete Sor
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
    try:
        res = requests.get(url, timeout=5)
        data = res.json()
        if data.get('status') == 1:
            p = data['product']
            name = p.get('product_name', 'Bilinmeyen Ürün')
            nutri = p.get('nutriments', {})
            cal = int(nutri.get('energy-kcal_100g', 0))
            prot = int(nutri.get('proteins_100g', 0))
            
            # 3. Hafızaya Kaydet
            conn.execute('INSERT INTO products (barcode, name, calories, protein) VALUES (?, ?, ?, ?)', (barcode, name, cal, prot))
            conn.commit()
            conn.close()
            return {'found': True, 'source': 'api', 'name': name, 'calories': cal, 'protein': prot}
    except:
        pass

    conn.close()
    return {'found': False}

# --- GÜVENLİK KONTROLÜ ---
def check_auth(username, password):
    if username != 'Muhammed': return False # Kendi adını buraya yaz
    secret = os.environ.get('TOTP_SECRET')
    if not secret: return password == 'admin123'
    return pyotp.TOTP(secret).verify(password)

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('logged_in'): return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response('Giriş Yapmalısınız', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
        session['logged_in'] = True
        return f(*args, **kwargs)
    return decorated

# --- DB KURULUMU ---
def init_db():
    conn = get_db_connection()
    # Tablolar
    conn.execute('CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, tarih TEXT, kilo REAL)')
    conn.execute('CREATE TABLE IF NOT EXISTS nutrition (id INTEGER PRIMARY KEY AUTOINCREMENT, isim TEXT NOT NULL, kalori INTEGER, protein INTEGER, tarih TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS products (barcode TEXT PRIMARY KEY, name TEXT, calories INTEGER, protein INTEGER)')
    conn.execute('CREATE TABLE IF NOT EXISTS goals (id INTEGER PRIMARY KEY AUTOINCREMENT, baslik TEXT, kategori TEXT, hedef_tarih TEXT, ilerleme INTEGER DEFAULT 0)')
    conn.commit()
    conn.close()

init_db()

# --- ROTALAR ---

@app.route('/', methods=['GET', 'POST'])
@requires_auth
def dashboard():
    conn = get_db_connection()
    if request.method == 'POST':
        # Hızlı Gün Sonu Girişi
        if 'gun_ozeti' in request.form:
            kilo = request.form.get('kilo')
            if kilo:
                tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
                conn.execute('INSERT INTO logs (tarih, kilo) VALUES (?, ?)', (tarih, kilo))
            # Buraya ilerde "tamamlanan görev sayısı" da eklenir
        conn.commit()
        return redirect(url_for('dashboard'))

    # Özet Veriler
    son_kilo = conn.execute('SELECT kilo FROM logs ORDER BY id DESC LIMIT 1').fetchone()
    son_kilo = son_kilo['kilo'] if son_kilo else "--"
    
    hedefler = conn.execute('SELECT * FROM goals ORDER BY hedef_tarih ASC LIMIT 3').fetchall()
    
    conn.close()
    return render_template('dashboard.html', son_kilo=son_kilo, hedefler=hedefler)

# --- BARKOD API (JS buraya istek atacak) ---
@app.route('/get_barcode_data')
@requires_auth
def get_barcode_data():
    code = request.args.get('code')
    return jsonify(get_product_info(code)) if code else jsonify({'found': False})

@app.route('/nutrition', methods=['GET', 'POST'])
@requires_auth
def nutrition():
    conn = get_db_connection()
    bugun = datetime.now().strftime("%Y-%m-%d")

    if request.method == 'POST':
        if 'yemek_ekle' in request.form:
            isim = request.form.get('isim')
            kal = int(request.form.get('kalori') or 0)
            prot = int(request.form.get('protein') or 0)
            barcode = request.form.get('barcode')
            
            # Eğer yeni barkodsa hafızaya ekle
            if barcode:
                try:
                    conn.execute('INSERT OR IGNORE INTO products (barcode, name, calories, protein) VALUES (?, ?, ?, ?)', (barcode, isim, kal, prot))
                except: pass
            
            conn.execute('INSERT INTO nutrition (isim, kalori, protein, tarih) VALUES (?, ?, ?, ?)', (isim, kal, prot, bugun))
        
        elif 'yemek_sil' in request.form:
            conn.execute('DELETE FROM nutrition WHERE id = ?', (request.form.get('yemek_id'),))
            
        conn.commit()
        return redirect(url_for('nutrition'))

    meals = conn.execute('SELECT * FROM nutrition WHERE tarih = ? ORDER BY id DESC', (bugun,)).fetchall()
    total_cal = sum(m['kalori'] for m in meals)
    total_pro = sum(m['protein'] for m in meals)
    conn.close()
    return render_template('nutrition.html', meals=meals, total_cal=total_cal, total_pro=total_pro)

# Roadmap sayfası (Basit tuttum)
@app.route('/roadmap')
@requires_auth
def roadmap():
    return "Roadmap Yakında..."

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
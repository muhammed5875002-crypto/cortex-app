import os
import sqlite3
import requests
import pyotp
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response

app = Flask(__name__)

# --- AYARLAR ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = os.path.join(BASE_DIR, "lifeos.db")

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# --- TOTP (GOOGLE AUTHENTICATOR) GÜVENLİK SİSTEMİ ---
def check_auth(username, password):
    # 1. Kullanıcı Adı Kontrolü (Senin belirlediğin isim)
    if username != 'Muhammed[*]}':
        return False
    
    # 2. Şifre Kontrolü (Render'dan gizli anahtarı çek)
    gizli_anahtar = os.environ.get('TOTP_SECRET')
    
    # Eğer Render'da anahtarı henüz ayarlamadıysak, güvenlik için false dön veya geçici şifre kullan
    if not gizli_anahtar:
        return password == '458drıIEF34Aw/'
        
    # Google Authenticator doğrulaması
    totp = pyotp.TOTP(gizli_anahtar)
    return totp.verify(password)

def authenticate():
    return Response(
    'Bu alan gizlidir. Lütfen Google Authenticator kodunu girin.', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# --- YARDIMCI FONKSİYON: API İLE KALORİ BULMA ---
def get_calories_from_api(query):
    APP_ID = os.environ.get('EDAMAM_ID')
    APP_KEY = os.environ.get('EDAMAM_KEY')
    
    if not APP_ID or not APP_KEY or not query:
        return 0
        
    url = "https://api.edamam.com/api/nutrition-data"
    params = {
        'app_id': APP_ID,
        'app_key': APP_KEY,
        'ingr': query
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        return data.get('calories', 0)
    except:
        return 0

# --- VERİTABANI KURULUMU ---
def init_db():
    conn = get_db_connection()
    # 1. Günlük Loglar
    conn.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tarih TEXT, kilo REAL)''')
    
    # 2. Todo
    conn.execute('''CREATE TABLE IF NOT EXISTS todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        baslik TEXT NOT NULL,
        durum INTEGER DEFAULT 0,
        tarih TEXT)''')

    # 3. Beslenme
    conn.execute('''CREATE TABLE IF NOT EXISTS nutrition (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        isim TEXT NOT NULL,
        kalori INTEGER,
        protein INTEGER,
        tarih TEXT)''')

    # 4. Spor
    conn.execute('''CREATE TABLE IF NOT EXISTS workouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gun_adi TEXT,
        bolge TEXT,
        hareketler TEXT,
        durum INTEGER DEFAULT 0
    )''')
    
    # Varsayılan Spor Programı
    cur = conn.execute('SELECT count(*) FROM workouts')
    if cur.fetchone()[0] == 0:
        program = [
            ('Pazartesi', 'Göğüs & Arka Kol', 'Bench Press, Incline Dumbbell, Pushdown, Dips'),
            ('Çarşamba', 'Sırt & Biceps', 'Lat Pulldown, Cable Row, Barbell Curl, Hammer Curl'),
            ('Cuma', 'Omuz & Bacak', 'Shoulder Press, Lateral Raise, Squat, Leg Extension'),
            ('Cumartesi', 'Kardiyo & Karın', '30dk Yürüyüş, Plank (3x1dk), Leg Raise, Crunch')
        ]
        conn.executemany('INSERT INTO workouts (gun_adi, bolge, hareketler) VALUES (?, ?, ?)', program)

    # 5. Hedefler
    conn.execute('''CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        baslik TEXT,
        kategori TEXT,
        hedef_tarih TEXT,
        ilerleme INTEGER DEFAULT 0
    )''')
    
    # 6. Kütüphane
    conn.execute('''CREATE TABLE IF NOT EXISTS library (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kategori TEXT,
        baslik TEXT,
        icerik TEXT,
        tarih TEXT
    )''')
    
    # 7. Notlar ve Hatırlatıcılar
    conn.execute('''CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        icerik TEXT NOT NULL,
        hedef_zaman TEXT,
        oncelik TEXT DEFAULT 'NORMAL',
        durum INTEGER DEFAULT 0
    )''')

    conn.commit()
    conn.close()

init_db()

# --- ROTALAR ---

# 1. DASHBOARD (ANA SAYFA)
@app.route('/', methods=['GET', 'POST'])
@requires_auth
def dashboard():
    conn = get_db_connection()
    
    if request.method == 'POST':
        # Kilo Girişi
        if 'kilo' in request.form:
            kilo = request.form.get('kilo')
            tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
            conn.execute('INSERT INTO logs (tarih, kilo) VALUES (?, ?)', (tarih, kilo))
        
        # Not / Hatırlatıcı Ekleme
        elif 'not_ekle' in request.form:
            icerik = request.form.get('icerik')
            hedef_zaman = request.form.get('hedef_zaman')
            oncelik = 'ACIL' if request.form.get('acil_mi') else 'NORMAL'
            if not hedef_zaman: hedef_zaman = None
            else: hedef_zaman = hedef_zaman.replace('T', ' ')
            conn.execute('INSERT INTO reminders (icerik, hedef_zaman, oncelik) VALUES (?, ?, ?)', 
                         (icerik, hedef_zaman, oncelik))
            
        # Hatırlatıcı Silme
        elif 'not_sil' in request.form:
            rem_id = request.form.get('rem_id')
            conn.execute('DELETE FROM reminders WHERE id = ?', (rem_id,))

        conn.commit()
        return redirect(url_for('dashboard'))

    # Verileri Çek
    son_log = conn.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 1').fetchone()
    bugun = datetime.now().strftime("%Y-%m-%d")
    biten_gorev = conn.execute('SELECT COUNT(*) FROM todos WHERE durum=1 AND tarih=?', (bugun,)).fetchone()[0]
    hatirlaticilar = conn.execute('SELECT * FROM reminders ORDER BY hedef_zaman ASC').fetchall()
    
    conn.close()
    return render_template('dashboard.html', son_log=son_log, biten_gorev=biten_gorev, hatirlaticilar=hatirlaticilar)

# 2. TICKTICK (GÖREVLER)
@app.route('/todo', methods=['GET', 'POST'])
@requires_auth
def todo():
    conn = get_db_connection()
    bugun = datetime.now().strftime("%Y-%m-%d")

    if request.method == 'POST':
        if 'gorev_ekle' in request.form:
            baslik = request.form.get('baslik')
            conn.execute('INSERT INTO todos (baslik, tarih) VALUES (?, ?)', (baslik, bugun))
        elif 'gorev_sil' in request.form:
            todo_id = request.form.get('todo_id')
            conn.execute('DELETE FROM todos WHERE id = ?', (todo_id,))
        elif 'gorev_toggle' in request.form:
            todo_id = request.form.get('todo_id')
            durum = request.form.get('mevcut_durum')
            yeni_durum = 0 if durum == '1' else 1
            conn.execute('UPDATE todos SET durum = ? WHERE id = ?', (yeni_durum, todo_id))
        conn.commit()
        return redirect(url_for('todo'))

    yapilacaklar = conn.execute('SELECT * FROM todos WHERE tarih=? ORDER BY durum ASC, id DESC', (bugun,)).fetchall()
    conn.close()
    return render_template('todo.html', todos=yapilacaklar, bugun=bugun)

# 3. BESLENME & KALORİ (DÜZELTİLMİŞ)
@app.route('/nutrition', methods=['GET', 'POST'])
@requires_auth
def nutrition():
    conn = get_db_connection()
    bugun = datetime.now().strftime("%Y-%m-%d")

    if request.method == 'POST':
        if 'yemek_ekle' in request.form:
            isim = request.form.get('isim')
            kalori_input = request.form.get('kalori')
            protein_input = request.form.get('protein')

            # --- AKILLI KALORİ SİSTEMİ ---
            if not kalori_input or kalori_input.strip() == "":
                bulunan_kalori = get_calories_from_api(isim) 
                kalori = int(bulunan_kalori)
            else:
                kalori = int(kalori_input)

            if not protein_input or protein_input.strip() == "":
                protein = 0
            else:
                protein = int(protein_input)

            conn.execute('INSERT INTO nutrition (isim, kalori, protein, tarih) VALUES (?, ?, ?, ?)', 
                         (isim, kalori, protein, bugun))
        
        elif 'yemek_sil' in request.form:
            yemek_id = request.form.get('yemek_id')
            conn.execute('DELETE FROM nutrition WHERE id = ?', (yemek_id,))
            
        conn.commit()
        return redirect(url_for('nutrition'))

    meals = conn.execute('SELECT * FROM nutrition WHERE tarih = ?', (bugun,)).fetchall()
    toplam_kalori = sum(row['kalori'] for row in meals)
    toplam_protein = sum(row['protein'] for row in meals)
    
    conn.close()
    return render_template('nutrition.html', meals=meals, bugun=bugun, 
                           toplam_kalori=toplam_kalori, toplam_protein=toplam_protein)

# 4. SPOR MODÜLÜ
@app.route('/sports', methods=['GET', 'POST'])
@requires_auth
def sports():
    conn = get_db_connection()
    
    if request.method == 'POST':
        workout_id = request.form.get('workout_id')
        cur = conn.execute('SELECT durum FROM workouts WHERE id = ?', (workout_id,)).fetchone()
        yeni_durum = 0 if cur['durum'] == 1 else 1
        conn.execute('UPDATE workouts SET durum = ? WHERE id = ?', (yeni_durum, workout_id))
        conn.commit()
        return redirect(url_for('sports'))

    program = conn.execute('SELECT * FROM workouts').fetchall()
    tamamlanan = sum(1 for p in program if p['durum'] == 1)
    toplam_gun = len(program)
    yuzde = int((tamamlanan / toplam_gun) * 100) if toplam_gun > 0 else 0
    
    gunler = {0: 'Pazartesi', 1: 'Salı', 2: 'Çarşamba', 3: 'Perşembe', 4: 'Cuma', 5: 'Cumartesi', 6: 'Pazar'}
    bugun_isim = gunler[datetime.now().weekday()]
    
    conn.close()
    return render_template('sports.html', program=program, yuzde=yuzde, bugun_isim=bugun_isim)

# 5. ROADMAP (YILLIK HEDEFLER)
@app.route('/roadmap', methods=['GET', 'POST'])
@requires_auth
def roadmap():
    conn = get_db_connection()
    
    if request.method == 'POST':
        if 'hedef_ekle' in request.form:
            baslik = request.form.get('baslik')
            kategori = request.form.get('kategori')
            tarih = request.form.get('tarih')
            conn.execute('INSERT INTO goals (baslik, kategori, hedef_tarih) VALUES (?, ?, ?)', 
                         (baslik, kategori, tarih))
        elif 'ilerleme_guncelle' in request.form:
            goal_id = request.form.get('goal_id')
            yeni_yuzde = request.form.get('yeni_yuzde')
            conn.execute('UPDATE goals SET ilerleme = ? WHERE id = ?', (yeni_yuzde, goal_id))
        elif 'hedef_sil' in request.form:
            goal_id = request.form.get('goal_id')
            conn.execute('DELETE FROM goals WHERE id = ?', (goal_id,))
            
        conn.commit()
        return redirect(url_for('roadmap'))

    hedefler = conn.execute('SELECT * FROM goals ORDER BY hedef_tarih ASC').fetchall()
    bugun = datetime.now()
    conn.close()
    return render_template('roadmap.html', hedefler=hedefler, bugun=bugun)

# 6. GELİŞİM KÜTÜPHANESİ
@app.route('/library', methods=['GET', 'POST'])
@requires_auth
def library():
    conn = get_db_connection()
    
    if request.method == 'POST':
        if 'bilgi_ekle' in request.form:
            baslik = request.form.get('baslik')
            icerik = request.form.get('icerik')
            kategori = request.form.get('kategori')
            tarih = datetime.now().strftime("%d.%m.%Y")
            conn.execute('INSERT INTO library (baslik, icerik, kategori, tarih) VALUES (?, ?, ?, ?)', 
                         (baslik, icerik, kategori, tarih))
        elif 'bilgi_sil' in request.form:
            lib_id = request.form.get('lib_id')
            conn.execute('DELETE FROM library WHERE id = ?', (lib_id,))
            
        conn.commit()
        return redirect(url_for('library'))

    veriler = conn.execute('SELECT * FROM library ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('library.html', veriler=veriler)

if __name__ == '__main__':
    # Render için host ayarı
    app.run(debug=True, host='0.0.0.0', port=5050)
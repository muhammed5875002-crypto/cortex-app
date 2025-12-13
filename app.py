import requests  # <-- Bunu en üstteki import'ların yanına ekle
from functools import wraps
from flask import Response, request # request zaten vardır, yanına ekle
from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime
import os
import pyotp

app = Flask(__name__)

# --- TOTP (GOOGLE AUTHENTICATOR) GÜVENLİK SİSTEMİ ---
def check_auth(username, password):
    # 1. Kullanıcı Adı Kontrolü
    if username != 'Muhammed[*]}':
        return False
    
    # 2. Şifre Kontrolü (Render'dan gizli anahtarı çek)
    gizli_anahtar = os.environ.get('TOTP_SECRET')
    
    # Eğer Render'da anahtarı henüz ayarlamadıysak, eski şifreyle aç (Güvenlik önlemi)
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

import os
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = os.path.join(BASE_DIR, "lifeos.db")

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# --- VERİTABANI KURULUMU (TÜM MODÜLLER İÇİN) ---
def init_db():
    conn = get_db_connection()
    # 1. Günlük Loglar (Eski sistem)
    conn.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tarih TEXT, kilo REAL, dgs_mat INTEGER, kelime INTEGER, proje_durum TEXT)''')
    
    # 2. Todo (TickTick Modeli)
    conn.execute('''CREATE TABLE IF NOT EXISTS todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        baslik TEXT NOT NULL,
        durum INTEGER DEFAULT 0,
        tarih TEXT)''')

    # 3. Beslenme (FatSecret Modeli)
    conn.execute('''CREATE TABLE IF NOT EXISTS nutrition (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        isim TEXT NOT NULL,
        kalori INTEGER,
        protein INTEGER,
        tarih TEXT)''')

    # 4. Spor (Haftalık Program)
    conn.execute('''CREATE TABLE IF NOT EXISTS workouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gun_adi TEXT,
        bolge TEXT,
        hareketler TEXT,
        durum INTEGER DEFAULT 0
    )''')
    
    # Varsayılan Programı Yükle (Eğer tablo boşsa)
    cur = conn.execute('SELECT count(*) FROM workouts')
    if cur.fetchone()[0] == 0:
        program = [
            ('Pazartesi', 'Göğüs & Arka Kol', 'Bench Press, Incline Dumbbell, Pushdown, Dips'),
            ('Çarşamba', 'Sırt & Biceps', 'Lat Pulldown, Cable Row, Barbell Curl, Hammer Curl'),
            ('Cuma', 'Omuz & Bacak', 'Shoulder Press, Lateral Raise, Squat, Leg Extension'),
            ('Cumartesi', 'Kardiyo & Karın', '30dk Yürüyüş, Plank (3x1dk), Leg Raise, Crunch')
        ]
        conn.executemany('INSERT INTO workouts (gun_adi, bolge, hareketler) VALUES (?, ?, ?)', program)


    # 5. Hedefler (Yıllık Roadmap)
    conn.execute('''CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        baslik TEXT,
        kategori TEXT,
        hedef_tarih TEXT,
        ilerleme INTEGER DEFAULT 0
    )''')
    
    # ... conn.commit() ...

    # ... conn.commit() ve conn.close() ...

# ... önceki tablolar ...

    # 6. Gelişim Kütüphanesi
    conn.execute('''CREATE TABLE IF NOT EXISTS library (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kategori TEXT,  -- INGILIZCE, DIKSIYON, KOD, NOT
        baslik TEXT,
        icerik TEXT,
        tarih TEXT
    )''')
    
    # ... conn.commit() ...

# ... önceki tablolar ...

    # 7. Akıllı Notlar ve Hatırlatıcılar
    conn.execute('''CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        icerik TEXT NOT NULL,
        hedef_zaman TEXT, -- Boşsa düz nottur, doluysa hatırlatıcıdır
        oncelik TEXT DEFAULT 'NORMAL', -- NORMAL veya ACIL
        durum INTEGER DEFAULT 0
    )''')

    conn.commit()
    conn.close()



init_db()

# --- API İLE KALORİ HESAPLAMA ---
def get_calories_from_api(query):
    APP_ID = os.environ.get('EDAMAM_ID')
    APP_KEY = os.environ.get('EDAMAM_KEY')
    
    if not APP_ID or not APP_KEY:
        print("API Anahtarları Eksik!")
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
    except Exception as e:
        print(f"API Hatası: {e}")
        return 0
    
# --- ROTALAR ---

# 1. DASHBOARD (ANA SAYFA) - GÜNCELLENDİ
@app.route('/', methods=['GET', 'POST'])
@requires_auth
def dashboard():
    conn = get_db_connection()
    
    # POST İSTEĞİ (Veri Girişi)
    if request.method == 'POST':
        # 1. Kilo Girişi (Eski özellik)
        if 'kilo' in request.form:
            kilo = request.form.get('kilo')
            tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
            conn.execute('INSERT INTO logs (tarih, kilo) VALUES (?, ?)', (tarih, kilo))
        
        # 2. YENİ: Not / Hatırlatıcı Ekleme
        elif 'not_ekle' in request.form:
            icerik = request.form.get('icerik')
            hedef_zaman = request.form.get('hedef_zaman') # HTML'den gelen format: 2023-12-14T15:30
            oncelik = 'ACIL' if request.form.get('acil_mi') else 'NORMAL'
            
            # Eğer tarih seçilmediyse boş kaydedelim (Düz not)
            if not hedef_zaman: 
                hedef_zaman = None
            else:
                # Tarih formatını güzelleştirebiliriz (Opsiyonel)
                hedef_zaman = hedef_zaman.replace('T', ' ')

            conn.execute('INSERT INTO reminders (icerik, hedef_zaman, oncelik) VALUES (?, ?, ?)', 
                         (icerik, hedef_zaman, oncelik))
            
        # 3. Hatırlatıcı Silme/Tamamlama
        elif 'not_sil' in request.form:
            rem_id = request.form.get('rem_id')
            conn.execute('DELETE FROM reminders WHERE id = ?', (rem_id,))

        conn.commit()
        return redirect(url_for('dashboard'))

    # GET İSTEĞİ (Verileri Çekme)
    
    # Son kiloyu çek
    son_log = conn.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 1').fetchone()
    
    # Bugünün tamamlanan görev sayısı
    bugun = datetime.now().strftime("%Y-%m-%d")
    biten_gorev = conn.execute('SELECT COUNT(*) FROM todos WHERE durum=1 AND tarih=?', (bugun,)).fetchone()[0]
    
    # YENİ: Hatırlatıcıları Çek (Tarihe göre sıralı)
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

# 3. GÜNCEL VERİ GİRİŞİ (Hızlı Ekleme)
@app.route('/add_log', methods=['POST'])
@requires_auth
def add_log():
    conn = get_db_connection()
    kilo = request.form.get('kilo')
    tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
    conn.execute('INSERT INTO logs (tarih, kilo) VALUES (?, ?)', (tarih, kilo))
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))
# --- 4. BESLENME & KALORİ ---
@app.route('/add_meal', methods=['POST'])
@requires_auth
def add_meal():
    meal_name = request.form.get('name')
    calories = request.form.get('calories')
    
    # Eğer kalori boş girildiyse API'ye sor
    if not calories or calories.strip() == "":
        detected_calories = get_calories_from_api(meal_name)
        calories = detected_calories
    
    # Veritabanına kaydet
    conn = get_db_connection()
    conn.execute('INSERT INTO meals (name, calories) VALUES (?, ?)', 
                 (meal_name, calories))
    conn.commit()
    conn.close()
    
    return redirect(url_for('meals')) # Veya senin yönlendirmen nereyeyse
# --- 5. SPOR MODÜLÜ ---
@app.route('/sports', methods=['GET', 'POST'])
@requires_auth
def sports():
    conn = get_db_connection()
    
    # Durum Güncelleme (Check/Uncheck)
    if request.method == 'POST':
        workout_id = request.form.get('workout_id')
        # Mevcut durumu tersine çevir (0 -> 1, 1 -> 0)
        cur = conn.execute('SELECT durum FROM workouts WHERE id = ?', (workout_id,)).fetchone()
        yeni_durum = 0 if cur['durum'] == 1 else 1
        conn.execute('UPDATE workouts SET durum = ? WHERE id = ?', (yeni_durum, workout_id))
        conn.commit()
        return redirect(url_for('sports'))

    # Programı Çek
    program = conn.execute('SELECT * FROM workouts').fetchall()
    
    # İstatistikler
    tamamlanan = sum(1 for p in program if p['durum'] == 1)
    toplam_gun = len(program)
    yuzde = int((tamamlanan / toplam_gun) * 100)
    
    # Bugünün Gününü Bul (Pazartesi, Salı...)
    gunler = {0: 'Pazartesi', 1: 'Salı', 2: 'Çarşamba', 3: 'Perşembe', 4: 'Cuma', 5: 'Cumartesi', 6: 'Pazar'}
    bugun_isim = gunler[datetime.now().weekday()]
    
    conn.close()
    return render_template('sports.html', program=program, yuzde=yuzde, bugun_isim=bugun_isim)

# --- 6. ROADMAP (YILLIK HEDEFLER) ---
@app.route('/roadmap', methods=['GET', 'POST'])
@requires_auth
def roadmap():
    conn = get_db_connection()
    
    if request.method == 'POST':
        # Yeni Hedef Ekleme
        if 'hedef_ekle' in request.form:
            baslik = request.form.get('baslik')
            kategori = request.form.get('kategori')
            tarih = request.form.get('tarih')
            conn.execute('INSERT INTO goals (baslik, kategori, hedef_tarih) VALUES (?, ?, ?)', 
                         (baslik, kategori, tarih))
        
        # İlerleme Güncelleme (Slider ile)
        elif 'ilerleme_guncelle' in request.form:
            goal_id = request.form.get('goal_id')
            yeni_yuzde = request.form.get('yeni_yuzde')
            conn.execute('UPDATE goals SET ilerleme = ? WHERE id = ?', (yeni_yuzde, goal_id))
            
        # Hedef Silme
        elif 'hedef_sil' in request.form:
            goal_id = request.form.get('goal_id')
            conn.execute('DELETE FROM goals WHERE id = ?', (goal_id,))
            
        conn.commit()
        return redirect(url_for('roadmap'))

    hedefler = conn.execute('SELECT * FROM goals ORDER BY hedef_tarih ASC').fetchall()
    
    # Tarih formatını güzelleştirmek için basit bir işlem
    bugun = datetime.now()
    
    conn.close()
    return render_template('roadmap.html', hedefler=hedefler, bugun=bugun)

# --- 7. GELİŞİM KÜTÜPHANESİ ---
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

    # Verileri Çek
    veriler = conn.execute('SELECT * FROM library ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('library.html', veriler=veriler)

if __name__ == '__main__':
    # Flask'a direkt dosya isimlerini veriyoruz. Kavgayı bitiriyoruz.
    app.run(debug=True, host='0.0.0.0', port=5050, ssl_context=('cert.pem', 'key.pem'))
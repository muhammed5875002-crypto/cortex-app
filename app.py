import os
import sqlite3
import requests
import pyotp
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, session

app = Flask(__name__)

# --- ÇOK ÖNEMLİ: OTURUM GÜVENLİĞİ ---
# Bunu tarayıcının seni hatırlaması için kullanıyoruz.
app.secret_key = os.environ.get('SECRET_KEY', 'cok_gizli_rastgele_bir_anahtar_123')
app.permanent_session_lifetime = timedelta(days=7) # 7 gün boyunca hatırla

# ==========================================
# 1. AYARLAR VE VERİTABANI
# ==========================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = os.path.join(BASE_DIR, "lifeos.db")

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# ==========================================
# 2. GÜVENLİK SİSTEMİ (Authenticator + Session)
# ==========================================

def check_auth(username, password):
    # Kullanıcı adı kontrolü
    if username != 'Muhammed[-]': # Buraya istediğin ismi yaz
        return False
    
    # Render'dan gizli anahtarı çek
    gizli_anahtar = os.environ.get('TOTP_SECRET')
    
    # Anahtar yoksa geçici şifre (Acil durum)
    if not gizli_anahtar:
        return password == 'admin123'
        
    # Google Authenticator doğrulaması
    totp = pyotp.TOTP(gizli_anahtar)
    return totp.verify(password)

def authenticate():
    return Response(
    'Lütfen Google Authenticator kodunu girin.', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. Önce hafızaya (Session) bak: Daha önce girmiş mi?
        if session.get('logged_in'):
            return f(*args, **kwargs)

        # 2. Girmemişse şifre sor
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        
        # 3. Şifre doğruysa hafızaya kaydet (Artık sormayacak)
        session['logged_in'] = True
        return f(*args, **kwargs)
    return decorated

# ==========================================
# 3. EDAMAM API (Kalori)
# ==========================================
def get_calories_from_api(query):
    APP_ID = os.environ.get('EDAMAM_ID')
    APP_KEY = os.environ.get('EDAMAM_KEY')
    
    if not APP_ID or not APP_KEY or not query: return 0
        
    try:
        url = "https://api.edamam.com/api/nutrition-data"
        params = {'app_id': APP_ID, 'app_key': APP_KEY, 'ingr': query}
        response = requests.get(url, params=params)
        return int(response.json().get('calories', 0))
    except:
        return 0

# ==========================================
# 4. VERİTABANI KURULUMU
# ==========================================
def init_db():
    conn = get_db_connection()
    conn.execute('CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, tarih TEXT, kilo REAL)')
    conn.execute('CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY AUTOINCREMENT, baslik TEXT NOT NULL, durum INTEGER DEFAULT 0, tarih TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS nutrition (id INTEGER PRIMARY KEY AUTOINCREMENT, isim TEXT NOT NULL, kalori INTEGER, protein INTEGER, tarih TEXT)')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS workouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, gun_adi TEXT, bolge TEXT, hareketler TEXT, durum INTEGER DEFAULT 0)''')
    cur = conn.execute('SELECT count(*) FROM workouts')
    if cur.fetchone()[0] == 0:
        program = [
            ('Pazartesi', 'Göğüs & Arka Kol', 'Bench Press, Incline Dumbbell, Pushdown, Dips'),
            ('Çarşamba', 'Sırt & Biceps', 'Lat Pulldown, Cable Row, Barbell Curl, Hammer Curl'),
            ('Cuma', 'Omuz & Bacak', 'Shoulder Press, Lateral Raise, Squat, Leg Extension'),
            ('Cumartesi', 'Kardiyo & Karın', '30dk Yürüyüş, Plank (3x1dk), Leg Raise, Crunch')
        ]
        conn.executemany('INSERT INTO workouts (gun_adi, bolge, hareketler) VALUES (?, ?, ?)', program)

    conn.execute('CREATE TABLE IF NOT EXISTS goals (id INTEGER PRIMARY KEY AUTOINCREMENT, baslik TEXT, kategori TEXT, hedef_tarih TEXT, ilerleme INTEGER DEFAULT 0)')
    conn.execute('CREATE TABLE IF NOT EXISTS library (id INTEGER PRIMARY KEY AUTOINCREMENT, kategori TEXT, baslik TEXT, icerik TEXT, tarih TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, icerik TEXT NOT NULL, hedef_zaman TEXT, oncelik TEXT DEFAULT "NORMAL", durum INTEGER DEFAULT 0)')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 5. ROTALAR
# ==========================================

@app.route('/', methods=['GET', 'POST'])
@requires_auth
def dashboard():
    conn = get_db_connection()
    if request.method == 'POST':
        if 'kilo' in request.form:
            if request.form.get('kilo'):
                conn.execute('INSERT INTO logs (tarih, kilo) VALUES (?, ?)', 
                             (datetime.now().strftime("%d.%m.%Y %H:%M"), request.form.get('kilo')))
        elif 'not_ekle' in request.form:
            hz = request.form.get('hedef_zaman').replace('T', ' ') if request.form.get('hedef_zaman') else None
            conn.execute('INSERT INTO reminders (icerik, hedef_zaman, oncelik) VALUES (?, ?, ?)', 
                         (request.form.get('icerik'), hz, 'ACIL' if request.form.get('acil_mi') else 'NORMAL'))
        elif 'not_sil' in request.form:
            conn.execute('DELETE FROM reminders WHERE id = ?', (request.form.get('rem_id'),))
        conn.commit()
        return redirect(url_for('dashboard'))

    son_log = conn.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 1').fetchone()
    biten = conn.execute('SELECT COUNT(*) FROM todos WHERE durum=1 AND tarih=?', (datetime.now().strftime("%Y-%m-%d"),)).fetchone()[0]
    hatirlaticilar = conn.execute('SELECT * FROM reminders ORDER BY hedef_zaman ASC').fetchall()
    conn.close()
    return render_template('dashboard.html', son_log=son_log, biten_gorev=biten, hatirlaticilar=hatirlaticilar)

@app.route('/todo', methods=['GET', 'POST'])
@requires_auth
def todo():
    conn = get_db_connection()
    bugun = datetime.now().strftime("%Y-%m-%d")
    if request.method == 'POST':
        if 'gorev_ekle' in request.form:
            if request.form.get('baslik'):
                conn.execute('INSERT INTO todos (baslik, tarih) VALUES (?, ?)', (request.form.get('baslik'), bugun))
        elif 'gorev_sil' in request.form:
            conn.execute('DELETE FROM todos WHERE id = ?', (request.form.get('todo_id'),))
        elif 'gorev_toggle' in request.form:
            cur = conn.execute('SELECT durum FROM todos WHERE id=?', (request.form.get('todo_id'),)).fetchone()
            conn.execute('UPDATE todos SET durum = ? WHERE id = ?', (0 if cur['durum']==1 else 1, request.form.get('todo_id')))
        conn.commit()
        return redirect(url_for('todo'))
    todos = conn.execute('SELECT * FROM todos WHERE tarih=? ORDER BY durum ASC, id DESC', (bugun,)).fetchall()
    conn.close()
    return render_template('todo.html', todos=todos, bugun=bugun)

@app.route('/nutrition', methods=['GET', 'POST'])
@requires_auth
def nutrition():
    conn = get_db_connection()
    bugun = datetime.now().strftime("%Y-%m-%d")

    if request.method == 'POST':
        if 'yemek_ekle' in request.form:
            isim = request.form.get('isim')
            kal = request.form.get('kalori')
            prot = request.form.get('protein')
            
            # API Kontrolü
            kalori = get_calories_from_api(isim) if (not kal or kal.strip() == "") else int(kal)
            protein = int(prot) if (prot and prot.strip() != "") else 0
            
            conn.execute('INSERT INTO nutrition (isim, kalori, protein, tarih) VALUES (?, ?, ?, ?)', (isim, kalori, protein, bugun))
        elif 'yemek_sil' in request.form:
            conn.execute('DELETE FROM nutrition WHERE id = ?', (request.form.get('yemek_id'),))
        conn.commit()
        return redirect(url_for('nutrition'))

    meals = conn.execute('SELECT * FROM nutrition WHERE tarih = ?', (bugun,)).fetchall()
    top_cal = sum(m['kalori'] for m in meals)
    top_pro = sum(m['protein'] for m in meals)
    conn.close()
    return render_template('nutrition.html', meals=meals, bugun=bugun, toplam_kalori=top_cal, toplam_protein=top_pro)

@app.route('/sports', methods=['GET', 'POST'])
@requires_auth
def sports():
    conn = get_db_connection()
    if request.method == 'POST':
        wid = request.form.get('workout_id')
        cur = conn.execute('SELECT durum FROM workouts WHERE id=?', (wid,)).fetchone()
        conn.execute('UPDATE workouts SET durum = ? WHERE id = ?', (0 if cur['durum']==1 else 1, wid))
        conn.commit()
        return redirect(url_for('sports'))
    program = conn.execute('SELECT * FROM workouts').fetchall()
    tamam = sum(1 for p in program if p['durum']==1)
    yuzde = int((tamam/len(program))*100) if len(program)>0 else 0
    bugun_isim = {0:'Pazartesi',1:'Salı',2:'Çarşamba',3:'Perşembe',4:'Cuma',5:'Cumartesi',6:'Pazar'}[datetime.now().weekday()]
    conn.close()
    return render_template('sports.html', program=program, yuzde=yuzde, bugun_isim=bugun_isim)

@app.route('/roadmap', methods=['GET', 'POST'])
@requires_auth
def roadmap():
    conn = get_db_connection()
    if request.method == 'POST':
        if 'hedef_ekle' in request.form:
            conn.execute('INSERT INTO goals (baslik, kategori, hedef_tarih) VALUES (?, ?, ?)', 
                         (request.form.get('baslik'), request.form.get('kategori'), request.form.get('tarih')))
        elif 'ilerleme_guncelle' in request.form:
            conn.execute('UPDATE goals SET ilerleme = ? WHERE id = ?', (request.form.get('yeni_yuzde'), request.form.get('goal_id')))
        elif 'hedef_sil' in request.form:
            conn.execute('DELETE FROM goals WHERE id = ?', (request.form.get('goal_id'),))
        conn.commit()
        return redirect(url_for('roadmap'))
    hedefler = conn.execute('SELECT * FROM goals ORDER BY hedef_tarih ASC').fetchall()
    conn.close()
    return render_template('roadmap.html', hedefler=hedefler, bugun=datetime.now())

@app.route('/library', methods=['GET', 'POST'])
@requires_auth
def library():
    conn = get_db_connection()
    if request.method == 'POST':
        if 'bilgi_ekle' in request.form:
            conn.execute('INSERT INTO library (baslik, icerik, kategori, tarih) VALUES (?, ?, ?, ?)', 
                         (request.form.get('baslik'), request.form.get('icerik'), request.form.get('kategori'), datetime.now().strftime("%d.%m.%Y")))
        elif 'bilgi_sil' in request.form:
            conn.execute('DELETE FROM library WHERE id = ?', (request.form.get('lib_id'),))
        conn.commit()
        return redirect(url_for('library'))
    veriler = conn.execute('SELECT * FROM library ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('library.html', veriler=veriler)

# --- ÇIKIŞ YAP (Opsiyonel ama gerekli) ---
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return "Çıkış yapıldı. Tarayıcıyı kapatın."

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
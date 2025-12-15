import os
import sqlite3
import pyotp
import random
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, session, flash
from itertools import groupby

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'om_fitness_pro_v15')
app.permanent_session_lifetime = timedelta(days=90)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_NAME = os.path.join(BASE_DIR, "lifeos.db")

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# --- GÜVENLİK ---
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
            return Response('Login Required', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
        session['logged_in'] = True
        return f(*args, **kwargs)
    return decorated

# --- DB KURULUM ---
def init_db():
    conn = get_db_connection()
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS supplements_def (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, dozaj TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS supplement_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, sup_id INTEGER, tarih TEXT)')
        
        # Workouts Tablosu (Gelişmiş)
        conn.execute('''CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bolge TEXT, hareket TEXT, 
            set_sayisi INTEGER DEFAULT 0, tekrar INTEGER DEFAULT 0, agirlik REAL DEFAULT 0,
            sure INTEGER DEFAULT 0, mesafe REAL DEFAULT 0, tarih TEXT)''')
            
        conn.execute('CREATE TABLE IF NOT EXISTS shortcuts (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, url TEXT, icon TEXT, color_theme TEXT)')
        
        # Eksik Kolon Kontrolü (Migration)
        cursor = conn.execute("PRAGMA table_info(workouts)")
        cols = [row['name'] for row in cursor.fetchall()]
        if 'sure' not in cols: conn.execute('ALTER TABLE workouts ADD COLUMN sure INTEGER DEFAULT 0')
        if 'mesafe' not in cols: conn.execute('ALTER TABLE workouts ADD COLUMN mesafe REAL DEFAULT 0')
        
        conn.commit()
    finally:
        conn.close()

init_db()

@app.route('/')
@requires_auth
def dashboard():
    conn = get_db_connection()
    if request.method == 'POST':
        if 'add_shortcut' in request.form:
            url = request.form.get('url')
            if not url.startswith('http'): url = 'https://' + url
            icons, colors = ['globe', 'link', 'star', 'bolt'], ['blue', 'purple', 'orange', 'green']
            conn.execute('INSERT INTO shortcuts (name, url, icon, color_theme) VALUES (?, ?, ?, ?)', 
                         (request.form.get('name'), url, random.choice(icons), random.choice(colors)))
        elif 'del_shortcut' in request.form:
            conn.execute('DELETE FROM shortcuts WHERE id = ?', (request.form.get('s_id'),))
        conn.commit()
    shortcuts = conn.execute('SELECT * FROM shortcuts').fetchall()
    conn.close()
    return render_template('dashboard.html', shortcuts=shortcuts)

@app.route('/fitness', methods=['GET', 'POST'])
@requires_auth
def fitness():
    conn = get_db_connection()
    bugun = datetime.now().strftime("%Y-%m-%d")
    
    if request.method == 'POST':
        try:
            # SUPPLEMENT İŞLEMLERİ
            if 'toggle_sup' in request.form:
                sid = request.form.get('sup_id')
                check = conn.execute('SELECT id FROM supplement_logs WHERE sup_id=? AND tarih=?', (sid, bugun)).fetchone()
                if check: conn.execute('DELETE FROM supplement_logs WHERE id=?', (check['id'],))
                else: conn.execute('INSERT INTO supplement_logs (sup_id, tarih) VALUES (?,?)', (sid, bugun))
            
            elif 'del_sup_def' in request.form:
                conn.execute('DELETE FROM supplements_def WHERE id=?', (request.form.get('sup_id'),))
            
            elif 'add_sup_def' in request.form:
                conn.execute('INSERT INTO supplements_def (name, dozaj) VALUES (?,?)', (request.form.get('name'), request.form.get('dozaj')))

            # ANTRENMAN İŞLEMLERİ
            elif 'add_workout' in request.form:
                bolge = request.form.get('bolge')
                
                if bolge == 'Kardiyo':
                    # Kardiyo Kaydı
                    conn.execute('INSERT INTO workouts (bolge, hareket, sure, mesafe, tarih) VALUES (?,?,?,?,?)',
                                 (bolge, request.form.get('hareket'), request.form.get('sure') or 0, request.form.get('mesafe') or 0, bugun))
                else:
                    # Ağırlık Kaydı
                    conn.execute('INSERT INTO workouts (bolge, hareket, set_sayisi, tekrar, agirlik, tarih) VALUES (?,?,?,?,?,?)',
                                 (bolge, request.form.get('hareket'), request.form.get('sets') or 0, request.form.get('tekrar') or 0, request.form.get('agirlik') or 0, bugun))
                
                flash('✅ Eklendi', 'success')

            elif 'del_workout' in request.form:
                conn.execute('DELETE FROM workouts WHERE id=?', (request.form.get('w_id'),))

            conn.commit()
        except Exception as e: flash(f"Hata: {e}", "danger")
        return redirect(url_for('fitness'))

    # Verileri Çek
    sups = conn.execute('SELECT * FROM supplements_def').fetchall()
    taken = [r['sup_id'] for r in conn.execute('SELECT sup_id FROM supplement_logs WHERE tarih=?', (bugun,)).fetchall()]
    sup_list = [{'id':s['id'], 'name':s['name'], 'dozaj':s['dozaj'], 'taken':(s['id'] in taken)} for s in sups]
    
    # Geçmiş Veriler
    history_raw = conn.execute('SELECT * FROM workouts ORDER BY tarih DESC, id DESC LIMIT 50').fetchall()
    history = [{'date': k, 'items': list(g)} for k, g in groupby(history_raw, lambda x: x['tarih'])]

    # Takvim
    calendar = []
    active_dates = [r['tarih'] for r in conn.execute("SELECT DISTINCT tarih FROM workouts WHERE tarih >= date('now', '-7 days')").fetchall()]
    for i in range(6, -1, -1):
        dt = (datetime.now() - timedelta(days=i))
        calendar.append({'day': dt.strftime("%a"), 'active': (dt.strftime("%Y-%m-%d") in active_dates), 'is_today': (dt.strftime("%Y-%m-%d") == bugun)})
    
    conn.close()
    return render_template('fitness.html', supplements=sup_list, history=history, calendar=calendar)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
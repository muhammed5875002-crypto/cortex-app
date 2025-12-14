import os
import sqlite3
import pyotp
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, session

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'om_system_key_fixed')
app.permanent_session_lifetime = timedelta(days=90)

# --- DB BAĞLANTISI ---
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

# --- DB KURULUMU (Onarıcı Mod) ---
def init_db():
    try:
        conn = get_db_connection()
        
        # Tabloları Garantiye Al
        conn.execute('CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, tarih TEXT, kilo REAL)')
        conn.execute('CREATE TABLE IF NOT EXISTS supplements_def (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, dozaj TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS supplement_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, sup_id INTEGER, tarih TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS workouts (id INTEGER PRIMARY KEY AUTOINCREMENT, bolge TEXT, hareket TEXT, set_sayisi INTEGER, tarih TEXT)')
        
        # Varsayılan Supplement Kontrolü
        # Hata olmaması için tabloyu kontrol et, boşsa doldur
        cur = conn.execute('SELECT count(*) FROM supplements_def')
        if cur.fetchone()[0] == 0:
            defaults = [
                ('Creatine', '5g'), 
                ('Whey Protein', '1 Ölçek'), 
                ('Multivitamin', '1 Tablet'), 
                ('Pre-Workout', '1 Ölçek'),
                ('Omega-3', '1000mg'), 
                ('ZMA', 'Yatmadan Önce')
            ]
            conn.executemany('INSERT INTO supplements_def (name, dozaj) VALUES (?, ?)', defaults)
            
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB HATASI: {e}")

# Uygulama başlarken DB'yi kontrol et
init_db()

# --- ROTALAR ---

@app.route('/', methods=['GET', 'POST'])
@requires_auth
def dashboard():
    return render_template('dashboard.html')

@app.route('/fitness', methods=['GET', 'POST'])
@requires_auth
def fitness():
    conn = get_db_connection()
    bugun = datetime.now().strftime("%Y-%m-%d")

    if request.method == 'POST':
        try:
            # SUPPLEMENT TİKLEME
            if 'toggle_sup' in request.form:
                sup_id = request.form.get('sup_id')
                check = conn.execute('SELECT id FROM supplement_logs WHERE sup_id = ? AND tarih = ?', (sup_id, bugun)).fetchone()
                if check:
                    conn.execute('DELETE FROM supplement_logs WHERE id = ?', (check['id'],))
                else:
                    conn.execute('INSERT INTO supplement_logs (sup_id, tarih) VALUES (?, ?)', (sup_id, bugun))
            
            # ANTRENMAN EKLEME
            elif 'add_workout' in request.form:
                bolge = request.form.get('bolge')
                hareket = request.form.get('hareket')
                sets = request.form.get('sets')
                conn.execute('INSERT INTO workouts (bolge, hareket, set_sayisi, tarih) VALUES (?, ?, ?, ?)', (bolge, hareket, sets, bugun))

            # ANTRENMAN SİLME
            elif 'del_workout' in request.form:
                conn.execute('DELETE FROM workouts WHERE id = ?', (request.form.get('w_id'),))
                
            conn.commit()
        except Exception as e:
            print(f"POST HATASI: {e}")
            
        return redirect(url_for('fitness'))

    # VERİ ÇEKME (Hata korumalı)
    try:
        sups_def = conn.execute('SELECT * FROM supplements_def').fetchall()
        taken_logs = conn.execute('SELECT sup_id FROM supplement_logs WHERE tarih = ?', (bugun,)).fetchall()
        taken_ids = [row['sup_id'] for row in taken_logs]
        
        supplement_list = []
        for s in sups_def:
            supplement_list.append({
                'id': s['id'],
                'name': s['name'],
                'dozaj': s['dozaj'],
                'taken': (s['id'] in taken_ids)
            })

        todays_workout = conn.execute('SELECT * FROM workouts WHERE tarih = ?', (bugun,)).fetchall()
    except:
        # Eğer tablo yoksa boş liste dön, site çökmesin
        supplement_list = []
        todays_workout = []
    
    conn.close()
    return render_template('fitness.html', supplements=supplement_list, workouts=todays_workout)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
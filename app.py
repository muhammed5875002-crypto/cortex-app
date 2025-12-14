import os
import sqlite3
import pyotp
import random
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, session, flash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'om_ultimate_pro_v10')
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
        # Mevcut Tablolar
        conn.execute('CREATE TABLE IF NOT EXISTS supplements_def (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, dozaj TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS supplement_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, sup_id INTEGER, tarih TEXT)')
        conn.execute('''CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bolge TEXT, hareket TEXT, set_sayisi INTEGER, tekrar INTEGER, agirlik REAL, tarih TEXT)''')

        # --- YENİ: KISAYOLLAR TABLOSU ---
        conn.execute('''CREATE TABLE IF NOT EXISTS shortcuts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT, 
            url TEXT, 
            icon TEXT, 
            color_theme TEXT
        )''')

        # Supplement Varsayılanları
        cur = conn.execute('SELECT count(*) FROM supplements_def')
        if cur.fetchone()[0] == 0:
            defaults = [('Creatine', '5g'), ('Whey Protein', '1 Ölçek'), ('Multivitamin', '1 Tablet'), ('Pre-Workout', '1 Ölçek'), ('Omega-3', '1000mg'), ('ZMA', 'Yatmadan Önce')]
            conn.executemany('INSERT INTO supplements_def (name, dozaj) VALUES (?, ?)', defaults)
            
        conn.commit()
    except Exception as e:
        print(f"DB HATASI: {e}")
    finally:
        conn.close()

init_db()

# --- ROTALAR ---

@app.route('/', methods=['GET', 'POST'])
@requires_auth
def dashboard():
    conn = get_db_connection()
    
    if request.method == 'POST':
        # --- KISAYOL EKLEME ---
        if 'add_shortcut' in request.form:
            name = request.form.get('name')
            url = request.form.get('url')
            # URL başında http yoksa ekle
            if not url.startswith('http') and not '://' in url:
                url = 'https://' + url
            
            # Rastgele İkon ve Renk Teması Ata
            icons = ['globe', 'link', 'star', 'bookmark', 'bolt', 'rocket', 'heart', 'coffee']
            colors = ['blue', 'purple', 'orange', 'pink', 'green', 'teal']
            
            icon = random.choice(icons)
            color = random.choice(colors)
            
            conn.execute('INSERT INTO shortcuts (name, url, icon, color_theme) VALUES (?, ?, ?, ?)', (name, url, icon, color))
            flash('Kısayol Eklendi', 'success')
            
        # --- KISAYOL SİLME ---
        elif 'del_shortcut' in request.form:
            conn.execute('DELETE FROM shortcuts WHERE id = ?', (request.form.get('s_id'),))
            flash('Kısayol Silindi', 'warning')
            
        conn.commit()
        return redirect(url_for('dashboard'))

    # Kısayolları Çek
    shortcuts = conn.execute('SELECT * FROM shortcuts').fetchall()
    conn.close()
    
    return render_template('dashboard.html', shortcuts=shortcuts)

@app.route('/fitness', methods=['GET', 'POST'])
@requires_auth
def fitness():
    # ... (Fitness kodları aynen kalıyor, burayı ellemedim) ...
    # Yer kaplamasın diye kısalttım, önceki kodun FITNESS bölümüyle birebir aynı çalışır.
    # Sadece importların ve app config'in yukarıdaki gibi olduğundan emin ol.
    conn = get_db_connection()
    bugun = datetime.now().strftime("%Y-%m-%d")

    if request.method == 'POST':
        try:
            if 'toggle_sup' in request.form:
                sup_id = request.form.get('sup_id')
                check = conn.execute('SELECT id FROM supplement_logs WHERE sup_id = ? AND tarih = ?', (sup_id, bugun)).fetchone()
                if check: conn.execute('DELETE FROM supplement_logs WHERE id = ?', (check['id'],))
                else: conn.execute('INSERT INTO supplement_logs (sup_id, tarih) VALUES (?, ?)', (sup_id, bugun))
            
            elif 'add_workout' in request.form:
                conn.execute('INSERT INTO workouts (bolge, hareket, set_sayisi, tekrar, agirlik, tarih) VALUES (?, ?, ?, ?, ?, ?)', 
                             (request.form.get('bolge'), request.form.get('hareket'), request.form.get('sets'), request.form.get('tekrar'), request.form.get('agirlik'), bugun))
                flash('Hareket Eklendi!', 'success')

            elif 'del_workout' in request.form:
                conn.execute('DELETE FROM workouts WHERE id = ?', (request.form.get('w_id'),))
                flash('Silindi.', 'danger')
                
            conn.commit()
        except Exception as e:
            print(f"HATA: {e}")
            
        return redirect(url_for('fitness'))

    sups_def = conn.execute('SELECT * FROM supplements_def').fetchall()
    taken_logs = conn.execute('SELECT sup_id FROM supplement_logs WHERE tarih = ?', (bugun,)).fetchall()
    taken_ids = [row['sup_id'] for row in taken_logs]
    
    supplement_list = [{'id': s['id'], 'name': s['name'], 'dozaj': s['dozaj'], 'taken': (s['id'] in taken_ids)} for s in sups_def]
    todays_workout = conn.execute('SELECT * FROM workouts WHERE tarih = ? ORDER BY id DESC', (bugun,)).fetchall()

    # Takvim Mantığı (Kısa versiyon)
    dates = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        day_name = (datetime.now() - timedelta(days=i)).strftime("%a")
        tr_days = {'Mon':'Pzt', 'Tue':'Sal', 'Wed':'Çar', 'Thu':'Per', 'Fri':'Cum', 'Sat':'Cmt', 'Sun':'Paz'}
        dates.append({'date': d, 'day': tr_days.get(day_name, day_name)})
        
    logs = conn.execute("SELECT DISTINCT tarih FROM workouts WHERE tarih >= date('now', '-7 days')").fetchall()
    active_dates = [l['tarih'] for l in logs]
    calendar_data = [{'day': d['day'], 'active': (d['date'] in active_dates), 'is_today': (d['date'] == bugun)} for d in dates]

    conn.close()
    return render_template('fitness.html', supplements=supplement_list, workouts=todays_workout, calendar=calendar_data)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
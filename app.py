import os
import sqlite3
import pyotp
import random
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, session, flash
from itertools import groupby

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'om_final_edition_v200')
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
        conn.execute('CREATE TABLE IF NOT EXISTS shortcuts (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, url TEXT, icon TEXT, color_theme TEXT)')
        
        conn.execute('''CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            bolge TEXT, hareket TEXT, 
            set_sayisi INTEGER DEFAULT 0, tekrar INTEGER DEFAULT 0, agirlik REAL DEFAULT 0, 
            sure INTEGER DEFAULT 0, mesafe REAL DEFAULT 0, 
            tarih TEXT
        )''')

        # Sütun Eksikse Tamamla
        cursor = conn.execute("PRAGMA table_info(workouts)")
        cols = [row['name'] for row in cursor.fetchall()]
        if 'sure' not in cols: conn.execute('ALTER TABLE workouts ADD COLUMN sure INTEGER DEFAULT 0')
        if 'mesafe' not in cols: conn.execute('ALTER TABLE workouts ADD COLUMN mesafe REAL DEFAULT 0')
        if 'tekrar' not in cols: conn.execute('ALTER TABLE workouts ADD COLUMN tekrar INTEGER DEFAULT 0')
        if 'agirlik' not in cols: conn.execute('ALTER TABLE workouts ADD COLUMN agirlik REAL DEFAULT 0')

        # Varsayılanlar
        cur = conn.execute('SELECT count(*) FROM supplements_def')
        if cur.fetchone()[0] == 0:
            defaults = [('Creatine', '5g'), ('Whey Protein', '1 Ölçek'), ('Pre-Workout', '1 Ölçek')]
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
            # 1. SUPPLEMENT TİKLEME
            if 'toggle_sup' in request.form:
                sid = request.form.get('sup_id')
                check = conn.execute('SELECT id FROM supplement_logs WHERE sup_id=? AND tarih=?', (sid, bugun)).fetchone()
                if check: conn.execute('DELETE FROM supplement_logs WHERE id=?', (check['id'],))
                else: conn.execute('INSERT INTO supplement_logs (sup_id, tarih) VALUES (?,?)', (sid, bugun))
            
            # 2. SUPPLEMENT YÖNETİMİ
            elif 'add_sup_def' in request.form:
                conn.execute('INSERT INTO supplements_def (name, dozaj) VALUES (?,?)', (request.form.get('name'), request.form.get('dozaj')))
            elif 'del_sup_def' in request.form:
                conn.execute('DELETE FROM supplements_def WHERE id=?', (request.form.get('sup_id'),))

            # 3. ANTRENMAN EKLEME
            elif 'add_workout' in request.form:
                bolge = request.form.get('bolge')
                hareket = request.form.get('hareket')
                if bolge == 'Kardiyo':
                    conn.execute('INSERT INTO workouts (bolge, hareket, sure, mesafe, tarih) VALUES (?,?,?,?,?)',
                                 (bolge, hareket, request.form.get('sure') or 0, request.form.get('mesafe') or 0, bugun))
                else:
                    conn.execute('INSERT INTO workouts (bolge, hareket, set_sayisi, tekrar, agirlik, tarih) VALUES (?,?,?,?,?,?)',
                                 (bolge, hareket, request.form.get('sets') or 0, request.form.get('tekrar') or 0, request.form.get('agirlik') or 0, bugun))
                flash('Kaydedildi', 'success')

            # 4. ANTRENMAN DÜZENLEME (YENİ!)
            elif 'edit_workout' in request.form:
                w_id = request.form.get('w_id')
                bolge = request.form.get('bolge')
                hareket = request.form.get('hareket')
                
                if bolge == 'Kardiyo':
                    conn.execute('''UPDATE workouts SET bolge=?, hareket=?, sure=?, mesafe=? WHERE id=?''',
                                 (bolge, hareket, request.form.get('sure'), request.form.get('mesafe'), w_id))
                else:
                    conn.execute('''UPDATE workouts SET bolge=?, hareket=?, set_sayisi=?, tekrar=?, agirlik=? WHERE id=?''',
                                 (bolge, hareket, request.form.get('sets'), request.form.get('tekrar'), request.form.get('agirlik'), w_id))
                flash('Güncellendi', 'info')

            # 5. ANTRENMAN SİLME
            elif 'del_workout' in request.form:
                conn.execute('DELETE FROM workouts WHERE id=?', (request.form.get('w_id'),))

            conn.commit()
        except Exception as e:
            print(f"HATA: {e}")
            flash(f"İşlem Hatası: {e}", "danger")
        
        return redirect(url_for('fitness'))

    # VERİ ÇEKME
    sups = conn.execute('SELECT * FROM supplements_def').fetchall()
    taken = [r['sup_id'] for r in conn.execute('SELECT sup_id FROM supplement_logs WHERE tarih=?', (bugun,)).fetchall()]
    sup_list = [{'id':s['id'], 'name':s['name'], 'dozaj':s['dozaj'], 'taken':(s['id'] in taken)} for s in sups]
    
    # TÜM GEÇMİŞ (GÜN GÜN GRUPLAMA)
    # LIMIT 100 ile son 100 hareketi çekiyoruz, sayfa çok uzamasın.
    all_workouts = conn.execute('SELECT * FROM workouts ORDER BY tarih DESC, id DESC LIMIT 100').fetchall()
    
    timeline = []
    for date, items in groupby(all_workouts, key=lambda x: x['tarih']):
        # Tarihi güzele çevir (2023-12-14 -> Bugün / Dün / 14.12.2023)
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        if date == bugun: display_date = "Bugün"
        elif date == (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"): display_date = "Dün"
        else: display_date = date_obj.strftime("%d.%m.%Y")
        
        timeline.append({'date': display_date, 'raw_date': date, 'items': list(items)})

    # Takvim Verisi
    calendar = []
    active_dates_raw = conn.execute("SELECT DISTINCT tarih FROM workouts WHERE tarih >= date('now', '-7 days')").fetchall()
    active_dates = [r['tarih'] for r in active_dates_raw]
    for i in range(6, -1, -1):
        dt = datetime.now() - timedelta(days=i)
        d_str = dt.strftime("%Y-%m-%d")
        calendar.append({'day': dt.strftime("%a"), 'active': (d_str in active_dates), 'is_today': (d_str == bugun)})
    
    conn.close()
    return render_template('fitness.html', supplements=sup_list, timeline=timeline, calendar=calendar)

@app.route('/analysis')
@requires_auth
def analysis():
    conn = get_db_connection()
    try:
        total = conn.execute('SELECT count(*) FROM workouts').fetchone()[0] or 0
        fav = conn.execute('SELECT bolge FROM workouts GROUP BY bolge ORDER BY count(*) DESC LIMIT 1').fetchone()
        fav_text = fav['bolge'] if fav else "Yok"
        sup_score = conn.execute("SELECT count(*) FROM supplement_logs WHERE tarih >= date('now', '-30 days')").fetchone()[0] or 0
        rows = conn.execute('SELECT bolge, count(*) as c FROM workouts GROUP BY bolge').fetchall()
        labels, data = [r['bolge'] for r in rows], [r['c'] for r in rows]
    except:
        total, fav_text, sup_score, labels, data = 0, "-", 0, [], []
    finally:
        conn.close()
    return render_template('analysis.html', total=total, fav=fav_text, sup=sup_score, labels=labels, data=data)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
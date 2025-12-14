import os
import requests
import pyotp
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, session, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cortex_simple_key')

# BASİT HAFIZA (Veritabanı yerine geçici RAM kullanıyoruz, gerekirse dosyaya yazarız)
# Ama senin isteğin "Yönlendirme" olduğu için motto'yu session'da tutabiliriz.
# Veya basit bir txt dosyası.

# --- BARKOD API ---
def get_product_from_api(barcode):
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get('status') == 1:
            p = res['product']
            n = p.get('nutriments', {})
            return {
                'found': True,
                'name': p.get('product_name', 'Bilinmeyen'),
                'calories': int(n.get('energy-kcal_100g', 0)),
                'protein': int(n.get('proteins_100g', 0)),
                'fat': int(n.get('fat_100g', 0))
            }
    except: pass
    return {'found': False}

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

# --- ROTALAR ---

@app.route('/', methods=['GET', 'POST'])
@requires_auth
def dashboard():
    if request.method == 'POST':
        session['motto'] = request.form.get('motto')
    return render_template('dashboard.html', motto=session.get('motto', ''))

@app.route('/scanner')
@requires_auth
def scanner():
    return render_template('scanner.html')

@app.route('/get_barcode_data')
@requires_auth
def get_barcode_data():
    code = request.args.get('code')
    return jsonify(get_product_from_api(code))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
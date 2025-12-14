import os
import requests
import pyotp
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, session, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cortex_hub_key_v4')

# --- API AYARLARI ---
# Open Food Facts, kimliksiz istekleri engeller. Buraya kimlik ekledik.
HEADERS = {
    'User-Agent': 'CortexOS - Student Project - Ankara (muhammed@example.com)'
}

def search_api(query, is_barcode=False):
    results = []
    try:
        if is_barcode:
            # BARKOD SORGUSU
            url = f"https://world.openfoodfacts.org/api/v0/product/{query}.json"
            res = requests.get(url, headers=HEADERS, timeout=10)
            data = res.json()
            
            if data.get('status') == 1:
                results.append(parse_product(data['product']))
        else:
            # İSİM SORGUSU (Genişletilmiş)
            # page_size=20 yaptık, world veritabanını kullanıyoruz.
            url = f"https://world.openfoodfacts.org/cgi/search.pl?search_terms={query}&search_simple=1&action=process&json=1&page_size=20"
            
            res = requests.get(url, headers=HEADERS, timeout=10)
            data = res.json()
            
            products = data.get('products', [])
            for p in products:
                # Sadece ismi olanları al, gerisi çöp veri olmasın
                if 'product_name' in p and p['product_name'].strip() != "":
                    results.append(parse_product(p))
                
    except Exception as e:
        print(f"API HATASI: {e}") # Loglara hata basar
        return [] # Hata olursa boş liste dön
        
    return results

def parse_product(p):
    n = p.get('nutriments', {})
    # Veriler boşsa 0 ata ama hata verme
    return {
        'name': p.get('product_name', 'İsimsiz Ürün'),
        'brand': p.get('brands', ''),
        'cal': int(n.get('energy-kcal_100g', 0) or n.get('energy-kcal', 0) or 0),
        'pro': int(n.get('proteins_100g', 0) or n.get('proteins', 0) or 0),
        'fat': int(n.get('fat_100g', 0) or n.get('fat', 0) or 0),
        'carb': int(n.get('carbohydrates_100g', 0) or n.get('carbohydrates', 0) or 0)
    }

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

@app.route('/api_search')
@requires_auth
def api_search():
    q = request.args.get('q')
    type_ = request.args.get('type')
    if not q: return jsonify([])
    
    is_barcode = (type_ == 'barcode')
    # Arama sonucunu JSON olarak döndür
    return jsonify(search_api(q, is_barcode))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
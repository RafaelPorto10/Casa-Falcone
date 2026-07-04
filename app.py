from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3
import os
import qrcode
import io
import base64
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'casa_falcone_secret_2024'

UPLOAD_FOLDER = os.path.join('static', 'images')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

DB_PATH = 'cardapio.db'

# ─── Banco de Dados ────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS pratos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        categoria TEXT NOT NULL CHECK(categoria IN ('comida','bebida','sobremesa')),
        descricao TEXT,
        ingredientes TEXT,
        preco REAL NOT NULL,
        foto TEXT DEFAULT 'default.jpg',
        disponivel INTEGER DEFAULT 1,
        destaque INTEGER DEFAULT 0,
        criado_em TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS admin (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT UNIQUE NOT NULL,
        senha_hash TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS config (
        chave TEXT PRIMARY KEY,
        valor TEXT
    )''')

    # Admin padrão: usuário=admin, senha=falcone123
    c.execute("SELECT COUNT(*) FROM admin")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO admin (usuario, senha_hash) VALUES (?, ?)",
                  ('admin', generate_password_hash('falcone123')))

    # Config padrão
    configs = [
        ('horario', 'Seg a Sex: 8h–18h | Sáb: 8h–14h'),
        ('telefone', '(31) 9xxxx-xxxx'),
        ('instagram', '@casafalcone'),
    ]
    for chave, valor in configs:
        c.execute("INSERT OR IGNORE INTO config (chave, valor) VALUES (?, ?)", (chave, valor))

    # Pratos de exemplo
    c.execute("SELECT COUNT(*) FROM pratos")
    if c.fetchone()[0] == 0:
        pratos_exemplo = [
            ('Panino Focaccia', 'comida', 'Sanduíche artesanal feito no nosso pão focaccia da casa, recheado com ingredientes selecionados.', 'Pão focaccia, queijo muçarela, pesto de limão siciliano, rúcula, ragù de pancetta', 38.00, 'default_food.jpg', 1, 1),
            ('Bem Amado', 'comida', 'Um clássico da casa: ovos frescos com tomates cereja e alecrim sobre pão artesanal torrado.', 'Ovos, tomates cereja, alecrim, pão artesanal', 30.00, 'default_food.jpg', 1, 0),
            ('Bruschetta', 'comida', 'Bruschetta italiana tradicional com tomates frescos, manjericão e azeite extra virgem.', 'Pão italiano, tomates, manjericão, azeite, alho', 30.00, 'default_food.jpg', 1, 0),
            ('Crostone com Bacon', 'comida', 'Pão crocante tostado coberto com bacon crocante e queijo derretido.', 'Pão, bacon, queijo, ervas', 30.00, 'default_food.jpg', 1, 0),
            ('Cappuccino', 'bebida', 'Cappuccino italiano clássico com espresso encorpado e leite vaporizado cremoso.', 'Café espresso, leite vaporizado', 14.00, 'default_drink.jpg', 1, 1),
            ('Café Espresso', 'bebida', 'Espresso puro, intenso e aromático extraído na hora.', 'Café selecionado', 8.00, 'default_drink.jpg', 1, 0),
            ('Suco de Laranja', 'bebida', 'Suco natural de laranja espremido na hora, sem adição de açúcar.', 'Laranja fresca', 12.00, 'default_drink.jpg', 1, 0),
            ('Tiramisù', 'sobremesa', 'Clássico tiramisù italiano feito com mascarpone, biscoitos savoiardi e café.', 'Mascarpone, biscoito savoiardi, café, cacau em pó, ovos', 22.00, 'default_dessert.jpg', 1, 1),
            ('Panna Cotta', 'sobremesa', 'Panna cotta cremosa com calda de caramelo artesanal.', 'Creme de leite, açúcar, gelatina, baunilha, caramelo', 18.00, 'default_dessert.jpg', 1, 0),
            ('Torta de Limão', 'sobremesa', 'Torta refrescante de limão siciliano com massa crocante e merengue.', 'Limão siciliano, ovos, manteiga, açúcar, massa folhada', 20.00, 'default_dessert.jpg', 1, 0),
        ]
        c.executemany('''INSERT INTO pratos 
            (nome, categoria, descricao, ingredientes, preco, foto, disponivel, destaque)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', pratos_exemplo)

    conn.commit()
    conn.close()

# ─── Helpers ───────────────────────────────────────────────────────────────────

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin_logged' not in session:
            flash('Faça login para acessar o painel.', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

def get_config():
    conn = get_db()
    rows = conn.execute("SELECT chave, valor FROM config").fetchall()
    conn.close()
    return {r['chave']: r['valor'] for r in rows}

# ─── Rotas Públicas ────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('cardapio'))

@app.route('/cardapio')
def cardapio():
    conn = get_db()
    busca = request.args.get('busca', '').strip()
    categoria = request.args.get('categoria', 'comida')
    ordem = request.args.get('ordem', 'destaque')

    query = "SELECT * FROM pratos WHERE categoria = ?"
    params = [categoria]

    if busca:
        query = "SELECT * FROM pratos WHERE categoria = ? AND nome LIKE ?"
        params.append(f'%{busca}%')

    if ordem == 'az':
        query += " ORDER BY nome ASC"
    else:
        query += " ORDER BY destaque DESC, disponivel DESC, nome ASC"

    pratos = conn.execute(query, params).fetchall()
    config = get_config()
    conn.close()

    return render_template('cardapio.html',
                           pratos=pratos,
                           categoria=categoria,
                           busca=busca,
                           ordem=ordem,
                           config=config)

@app.route('/qrcode')
def gerar_qrcode():
    host = request.host_url
    url = f"{host}cardapio"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.getvalue()).decode()
    return render_template('qrcode.html', qr_b64=img_b64, url=url)

# ─── Rotas Admin ────────────────────────────────────────────────────────────────

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        senha = request.form.get('senha', '')
        conn = get_db()
        admin = conn.execute("SELECT * FROM admin WHERE usuario = ?", (usuario,)).fetchone()
        conn.close()
        if admin and check_password_hash(admin['senha_hash'], senha):
            session['admin_logged'] = True
            session['admin_user'] = usuario
            flash('Bem-vinda, dona Falcone! 🍕', 'success')
            return redirect(url_for('admin_painel'))
        flash('Usuário ou senha incorretos.', 'error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/admin')
@login_required
def admin_painel():
    conn = get_db()
    busca = request.args.get('busca', '').strip()
    categoria = request.args.get('categoria', 'todos')

    query = "SELECT * FROM pratos"
    params = []
    where = []

    if categoria != 'todos':
        where.append("categoria = ?")
        params.append(categoria)
    if busca:
        where.append("nome LIKE ?")
        params.append(f'%{busca}%')

    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY categoria, nome ASC"

    pratos = conn.execute(query, params).fetchall()
    config = get_config()
    conn.close()

    stats = {
        'total': len(pratos),
        'disponiveis': sum(1 for p in pratos if p['disponivel']),
        'indisponiveis': sum(1 for p in pratos if not p['disponivel']),
        'destaques': sum(1 for p in pratos if p['destaque']),
    }

    return render_template('admin_painel.html',
                           pratos=pratos,
                           categoria=categoria,
                           busca=busca,
                           config=config,
                           stats=stats)

@app.route('/admin/prato/novo', methods=['GET', 'POST'])
@login_required
def admin_novo_prato():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        categoria = request.form.get('categoria')
        descricao = request.form.get('descricao', '').strip()
        ingredientes = request.form.get('ingredientes', '').strip()
        preco = request.form.get('preco', 0)
        disponivel = 1 if request.form.get('disponivel') else 0
        destaque = 1 if request.form.get('destaque') else 0

        foto_nome = 'default_food.jpg'
        if categoria == 'bebida':
            foto_nome = 'default_drink.jpg'
        elif categoria == 'sobremesa':
            foto_nome = 'default_dessert.jpg'

        if 'foto' in request.files:
            file = request.files['foto']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
                foto_nome = unique_name

        try:
            preco = float(str(preco).replace(',', '.'))
        except:
            preco = 0.0

        conn = get_db()
        conn.execute('''INSERT INTO pratos 
            (nome, categoria, descricao, ingredientes, preco, foto, disponivel, destaque)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (nome, categoria, descricao, ingredientes, preco, foto_nome, disponivel, destaque))
        conn.commit()
        conn.close()
        flash(f'Prato "{nome}" adicionado com sucesso! 🍽️', 'success')
        return redirect(url_for('admin_painel'))

    return render_template('admin_form_prato.html', prato=None, acao='novo')

@app.route('/admin/prato/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def admin_editar_prato(id):
    conn = get_db()
    prato = conn.execute("SELECT * FROM pratos WHERE id = ?", (id,)).fetchone()
    if not prato:
        conn.close()
        flash('Prato não encontrado.', 'error')
        return redirect(url_for('admin_painel'))

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        categoria = request.form.get('categoria')
        descricao = request.form.get('descricao', '').strip()
        ingredientes = request.form.get('ingredientes', '').strip()
        preco = request.form.get('preco', 0)
        disponivel = 1 if request.form.get('disponivel') else 0
        destaque = 1 if request.form.get('destaque') else 0

        foto_nome = prato['foto']
        if 'foto' in request.files:
            file = request.files['foto']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
                foto_nome = unique_name

        try:
            preco = float(str(preco).replace(',', '.'))
        except:
            preco = 0.0

        conn.execute('''UPDATE pratos SET nome=?, categoria=?, descricao=?, ingredientes=?,
            preco=?, foto=?, disponivel=?, destaque=? WHERE id=?''',
            (nome, categoria, descricao, ingredientes, preco, foto_nome, disponivel, destaque, id))
        conn.commit()
        conn.close()
        flash(f'Prato "{nome}" atualizado! ✅', 'success')
        return redirect(url_for('admin_painel'))

    conn.close()
    return render_template('admin_form_prato.html', prato=prato, acao='editar')

@app.route('/admin/prato/<int:id>/disponibilidade', methods=['POST'])
@login_required
def toggle_disponivel(id):
    conn = get_db()
    prato = conn.execute("SELECT * FROM pratos WHERE id = ?", (id,)).fetchone()
    if prato:
        novo = 0 if prato['disponivel'] else 1
        conn.execute("UPDATE pratos SET disponivel = ? WHERE id = ?", (novo, id))
        conn.commit()
        status = "disponível" if novo else "indisponível"
        flash(f'"{prato["nome"]}" marcado como {status}.', 'success')
    conn.close()
    return redirect(request.referrer or url_for('admin_painel'))

@app.route('/admin/prato/<int:id>/destaque', methods=['POST'])
@login_required
def toggle_destaque(id):
    conn = get_db()
    prato = conn.execute("SELECT * FROM pratos WHERE id = ?", (id,)).fetchone()
    if prato:
        novo = 0 if prato['destaque'] else 1
        conn.execute("UPDATE pratos SET destaque = ? WHERE id = ?", (novo, id))
        conn.commit()
        status = "em destaque ⭐" if novo else "removido dos destaques"
        flash(f'"{prato["nome"]}" {status}.', 'success')
    conn.close()
    return redirect(request.referrer or url_for('admin_painel'))

@app.route('/admin/prato/<int:id>/apagar', methods=['POST'])
@login_required
def apagar_prato(id):
    conn = get_db()
    prato = conn.execute("SELECT * FROM pratos WHERE id = ?", (id,)).fetchone()
    if prato:
        conn.execute("DELETE FROM pratos WHERE id = ?", (id,))
        conn.commit()
        flash(f'Prato "{prato["nome"]}" apagado permanentemente. 🗑️', 'success')
    conn.close()
    return redirect(url_for('admin_painel'))

@app.route('/admin/config', methods=['GET', 'POST'])
@login_required
def admin_config():
    conn = get_db()
    if request.method == 'POST':
        for chave in ['horario', 'telefone', 'instagram']:
            valor = request.form.get(chave, '').strip()
            conn.execute("INSERT OR REPLACE INTO config (chave, valor) VALUES (?, ?)", (chave, valor))
        
        # Troca de senha
        nova_senha = request.form.get('nova_senha', '').strip()
        if nova_senha:
            if len(nova_senha) >= 6:
                hash_nova = generate_password_hash(nova_senha)
                conn.execute("UPDATE admin SET senha_hash = ? WHERE usuario = ?",
                             (hash_nova, session.get('admin_user')))
                flash('Senha alterada com sucesso! 🔐', 'success')
            else:
                flash('A senha deve ter pelo menos 6 caracteres.', 'error')

        conn.commit()
        flash('Configurações salvas! ✅', 'success')
        return redirect(url_for('admin_config'))

    config = get_config()
    conn.close()
    return render_template('admin_config.html', config=config)

if __name__ == '__main__':
    init_db()
    print("\n🍕 Casa Falcone — Sistema de Cardápio")
    print("=" * 40)
    print("✅ Servidor rodando em: http://localhost:5000")
    print("📱 Cardápio público:   http://localhost:5000/cardapio")
    print("🔐 Painel admin:       http://localhost:5000/admin/login")
    print("📲 Gerar QR Code:      http://localhost:5000/qrcode")
    print("=" * 40)
    print("🔑 Login admin: usuário=admin | senha=falcone123")
    print("   (Troque a senha no painel de configurações!)\n")
    app.run(debug=True, host='0.0.0.0', port=5000)

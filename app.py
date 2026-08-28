from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import asyncpg
import bcrypt
import os
from datetime import datetime, timedelta
from functools import wraps
import asyncio

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vdr442_site_secret_2024")
CORS(app)

# =========================================================
# CONFIGURAÇÕES
# =========================================================
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")

# =========================================================
# CONEXÃO COM O BANCO
# =========================================================
async def get_db():
    return await asyncpg.connect(DATABASE_URL)

def run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    else:
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

# =========================================================
# MODELO DE USUÁRIO
# =========================================================
async def criar_tabela_usuarios():
    conn = await get_db()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios_web (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(20) DEFAULT 'usuario',
            criado_em TIMESTAMP DEFAULT NOW()
        )
    """)
    await conn.close()

# =========================================================
# DECORATOR DE AUTENTICAÇÃO
# =========================================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# =========================================================
# ROTAS - LOGIN
# =========================================================
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    
    username = request.form.get('username')
    password = request.form.get('password')
    
    conn = run_async(get_db())
    user = run_async(conn.fetchrow(
        "SELECT * FROM usuarios_web WHERE username = $1",
        username
    ))
    run_async(conn.close())
    
    if not user:
        return render_template('login.html', erro="Usuário não encontrado")
    
    if not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
        return render_template('login.html', erro="Senha incorreta")
    
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']
    
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# =========================================================
# ROTAS - DASHBOARD
# =========================================================
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', username=session.get('username'))

# =========================================================
# API - MÉTRICAS DO DASHBOARD
# =========================================================
@app.route('/api/metricas')
@login_required
def api_metricas():
    conn = run_async(get_db())
    
    # Metas
    metas_count = run_async(conn.fetchval("SELECT COUNT(*) FROM metas"))
    
    # Vendas hoje
    hoje = datetime.now().strftime("%d/%m/%Y")
    vendas_hoje = run_async(conn.fetchval(
        "SELECT COALESCE(SUM(valor), 0) FROM vendas WHERE data = $1",
        hoje
    ))
    
    # Produções ativas
    producoes_ativas = run_async(conn.fetchval(
        "SELECT COUNT(*) FROM producoes WHERE fim > NOW()"
    ))
    
    # Ações da semana
    acoes_semana = run_async(conn.fetchval(
        "SELECT COUNT(*) FROM acoes_semana WHERE status = 'concluida' AND data > NOW() - INTERVAL '7 days'"
    ))
    
    # Estoque
    estoque_pt = run_async(conn.fetchval(
        "SELECT COALESCE(quantidade, 0) FROM estoque_municoes WHERE tipo = 'PT'"
    ))
    estoque_sub = run_async(conn.fetchval(
        "SELECT COALESCE(quantidade, 0) FROM estoque_municoes WHERE tipo = 'SUB'"
    ))
    
    # Total de membros
    total_membros = run_async(conn.fetchval(
        "SELECT COUNT(DISTINCT user_id) FROM registros_historico"
    ))
    
    run_async(conn.close())
    
    return jsonify({
        "metas": metas_count or 0,
        "vendas_hoje": vendas_hoje or 0,
        "producoes_ativas": producoes_ativas or 0,
        "acoes_semana": acoes_semana or 0,
        "estoque_pt": estoque_pt or 0,
        "estoque_sub": estoque_sub or 0,
        "total_membros": total_membros or 0
    })

# =========================================================
# API - METAS (RANKING)
# =========================================================
@app.route('/api/metas')
@login_required
def api_metas():
    conn = run_async(get_db())
    rows = run_async(conn.fetch("""
        SELECT 
            m.user_id,
            m.dinheiro,
            m.dinheiro_acoes,
            m.saldo_excedente,
            r.nome as nome_membro,
            r.user_name
        FROM metas m
        LEFT JOIN registros_historico r ON r.user_id = m.user_id
        ORDER BY (m.dinheiro + m.dinheiro_acoes) DESC
        LIMIT 30
    """))
    run_async(conn.close())
    
    metas = []
    for row in rows:
        nome = row['nome_membro'] or row['user_name'] or row['user_id']
        metas.append({
            "user_id": row['user_id'],
            "nome": nome,
            "dinheiro": row['dinheiro'] or 0,
            "dinheiro_acoes": row['dinheiro_acoes'] or 0,
            "saldo_excedente": row['saldo_excedente'] or 0,
            "total": (row['dinheiro'] or 0) + (row['dinheiro_acoes'] or 0)
        })
    
    return jsonify(metas)

# =========================================================
# API - VENDAS
# =========================================================
@app.route('/api/vendas')
@login_required
def api_vendas():
    conn = run_async(get_db())
    rows = run_async(conn.fetch("""
        SELECT * FROM vendas 
        ORDER BY id DESC 
        LIMIT 50
    """))
    run_async(conn.close())
    
    vendas = []
    for row in rows:
        vendas.append({
            "pedido_numero": row['pedido_numero'],
            "user_id": row['user_id'],
            "valor": row['valor'],
            "data": row['data']
        })
    
    return jsonify(vendas)

# =========================================================
# API - VENDAS RESUMO
# =========================================================
@app.route('/api/vendas/resumo')
@login_required
def api_vendas_resumo():
    conn = run_async(get_db())
    
    mes_atual = datetime.now().strftime("%m/%Y")
    total_mes = run_async(conn.fetchval(
        "SELECT COALESCE(SUM(valor), 0) FROM vendas WHERE data LIKE $1",
        f"%/{mes_atual}"
    ))
    
    semana = datetime.now() - timedelta(days=7)
    total_semana = run_async(conn.fetchval(
        "SELECT COALESCE(SUM(valor), 0) FROM vendas WHERE data::date > $1",
        semana.date()
    ))
    
    top_vendedores = run_async(conn.fetch("""
        SELECT user_id, SUM(valor) as total 
        FROM vendas 
        GROUP BY user_id 
        ORDER BY total DESC 
        LIMIT 5
    """))
    
    run_async(conn.close())
    
    top = []
    for row in top_vendedores:
        top.append({
            "user_id": row['user_id'],
            "total": row['total']
        })
    
    return jsonify({
        "total_mes": total_mes or 0,
        "total_semana": total_semana or 0,
        "top_vendedores": top
    })

# =========================================================
# API - PRODUÇÃO
# =========================================================
@app.route('/api/producao')
@login_required
def api_producao():
    conn = run_async(get_db())
    
    ativas = run_async(conn.fetch("""
        SELECT * FROM producoes WHERE fim > NOW() ORDER BY fim ASC
    """))
    
    historico = run_async(conn.fetch("""
        SELECT * FROM producoes_finalizadas ORDER BY data DESC LIMIT 20
    """))
    
    capsulas = run_async(conn.fetchval(
        "SELECT COALESCE(quantidade, 0) FROM estoque_capsulas WHERE id = 1"
    ))
    
    embalagens = run_async(conn.fetchval(
        "SELECT COALESCE(quantidade, 0) FROM estoque_embalagens WHERE id = 1"
    ))
    
    run_async(conn.close())
    
    ativas_lista = []
    for row in ativas:
        ativas_lista.append({
            "galpao": row['galpao'],
            "autor": row['autor'],
            "inicio": row['inicio'].isoformat() if row['inicio'] else None,
            "fim": row['fim'].isoformat() if row['fim'] else None
        })
    
    historico_lista = []
    for row in historico:
        historico_lista.append({
            "user_id": row['user_id'],
            "capsulas": row['capsulas'],
            "data": row['data'].isoformat() if row['data'] else None
        })
    
    return jsonify({
        "ativas": ativas_lista,
        "historico": historico_lista,
        "insumos": {
            "capsulas": capsulas or 0,
            "embalagens": embalagens or 0
        }
    })

# =========================================================
# API - AÇÕES
# =========================================================
@app.route('/api/acoes')
@login_required
def api_acoes():
    conn = run_async(get_db())
    rows = run_async(conn.fetch("""
        SELECT * FROM acoes_semana 
        WHERE status = 'concluida' 
        AND data > NOW() - INTERVAL '7 days'
        ORDER BY data DESC
    """))
    run_async(conn.close())
    
    acoes = []
    for row in rows:
        acoes.append({
            "id": row['id'],
            "tipo": row['tipo'],
            "resultado": row['resultado'],
            "valor": row['valor'],
            "data": row['data'].isoformat() if row['data'] else None
        })
    
    return jsonify(acoes)

# =========================================================
# API - USUÁRIOS
# =========================================================
@app.route('/api/usuarios')
@login_required
def api_usuarios():
    conn = run_async(get_db())
    rows = run_async(conn.fetch("""
        SELECT user_id, user_name, tipo, data_registro 
        FROM registros_historico 
        ORDER BY data_registro DESC 
        LIMIT 50
    """))
    run_async(conn.close())
    
    usuarios = []
    for row in rows:
        usuarios.append({
            "user_id": row['user_id'],
            "user_name": row['user_name'],
            "tipo": row['tipo'],
            "data_registro": row['data_registro'].isoformat() if row['data_registro'] else None
        })
    
    return jsonify(usuarios)

# =========================================================
# SETUP - CRIAR USUÁRIO ADMIN
# =========================================================
@app.route('/setup')
def setup():
    run_async(criar_tabela_usuarios())
    
    conn = run_async(get_db())
    admin = run_async(conn.fetchrow("SELECT * FROM usuarios_web WHERE username = 'admin'"))
    
    if not admin:
        senha_hash = bcrypt.hashpw("vdr442".encode('utf-8'), bcrypt.gensalt())
        run_async(conn.execute(
            "INSERT INTO usuarios_web (username, password_hash, role) VALUES ($1, $2, $3)",
            "admin", senha_hash.decode('utf-8'), "admin"
        ))
        run_async(conn.close())
        return "✅ Usuário admin criado! (login: admin / senha: vdr442)"
    
    run_async(conn.close())
    return "ℹ️ Usuário admin já existe!"

# =========================================================
# INICIAR
# =========================================================
if __name__ == '__main__':
    # Criar tabela na inicialização
    try:
        run_async(criar_tabela_usuarios())
        print("✅ Tabela de usuários verificada")
    except Exception as e:
        print(f"⚠️ Erro ao criar tabela: {e}")
    
    app.run(host='0.0.0.0', port=5000, debug=False)

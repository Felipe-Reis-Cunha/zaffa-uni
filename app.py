from flask import Flask, render_template, request, redirect, url_for, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sua_chave_secreta_123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- Modelos do Banco de Dados ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(100))
    role = db.Column(db.String(20))  # 'vendedor', 'gerente', 'suporte'

class MeioPagamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True)
    desconto_percentual = db.Column(db.Float)
    ativo = db.Column(db.Boolean, default=True)

class Acao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(10))  # 'MOB' ou 'SITE'
    cliente_codigo = db.Column(db.String(50))
    produtos = db.relationship('Produto', backref='acao', lazy=True)
    status = db.Column(db.String(20), default='pendente')  # 'pendente', 'aprovado', 'reprovado', 'concluido'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User', backref='acoes')
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    meio_pagamento_id = db.Column(db.Integer, db.ForeignKey('meio_pagamento.id'))
    meio_pagamento = db.relationship('MeioPagamento', backref='acoes')

class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50))
    valor_atual = db.Column(db.Float)
    valor_desejado = db.Column(db.Float)  # Valor informado pelo vendedor
    valor_final = db.Column(db.Float)      # Valor após desconto do meio de pagamento
    acao_id = db.Column(db.Integer, db.ForeignKey('acao.id'))

# Cria o banco de dados e o usuário padrão do suporte
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='suporte').first():
        senha_hash = generate_password_hash('senha_inicial_123')
        suporte = User(username='suporte', password=senha_hash, role='suporte')
        db.session.add(suporte)
        db.session.commit()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Rotas de Autenticação ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Credenciais inválidas!', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- Redirecionamento para Dashboard ---
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'vendedor':
        return redirect(url_for('dashboard_vendedor'))
    elif current_user.role == 'gerente':
        return redirect(url_for('dashboard_gerente'))
    elif current_user.role == 'suporte':
        return redirect(url_for('dashboard_suporte'))

# --- Vendedor ---
@app.route('/vendedor')
@login_required
def dashboard_vendedor():
    if current_user.role != 'vendedor':
        return redirect(url_for('dashboard'))
    acoes = Acao.query.filter_by(user_id=current_user.id).all()
    return render_template('vendedor.html', acoes=acoes)

@app.route('/criar_acao', methods=['GET', 'POST'])
@login_required
def criar_acao():
    if current_user.role != 'vendedor':
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        tipo = request.form['tipo']
        cliente_codigo = request.form['cliente_codigo']
        produtos = request.form.getlist('produto[]')
        valores_atuais = request.form.getlist('valor_atual[]')
        valores_desejados = request.form.getlist('valor_desejado[]')
        meio_pagamento_id = request.form.get('meio_pagamento', None) if tipo == 'MOB' else None
        
        meio_pagamento = MeioPagamento.query.get(meio_pagamento_id) if meio_pagamento_id else None
        
        nova_acao = Acao(
            tipo=tipo,
            cliente_codigo=cliente_codigo,
            user_id=current_user.id,
            meio_pagamento=meio_pagamento
        )
        db.session.add(nova_acao)
        db.session.commit()
        
        for i in range(len(produtos)):
            valor_atual = float(valores_atuais[i])
            valor_desejado = float(valores_desejados[i])
            
            # Cálculo do valor final
            if tipo == 'MOB' and meio_pagamento:
                desconto = valor_desejado * (meio_pagamento.desconto_percentual / 100)
                valor_final = valor_desejado - desconto
            else:
                valor_final = valor_desejado
            
            produto = Produto(
                codigo=produtos[i],
                valor_atual=valor_atual,
                valor_desejado=valor_desejado,
                valor_final=round(valor_final, 2),
                acao_id=nova_acao.id
            )
            db.session.add(produto)
        db.session.commit()
        
        flash('Ação criada com sucesso!', 'success')
        return redirect(url_for('dashboard_vendedor'))
    
    meios_pagamento = MeioPagamento.query.filter_by(ativo=True).all()
    return render_template('criar_acao.html', meios_pagamento=meios_pagamento)

# --- Gerente ---
@app.route('/gerente')
@login_required
def dashboard_gerente():
    if current_user.role != 'gerente':
        return redirect(url_for('dashboard'))
    
    acoes = Acao.query.all()
    total_produtos = sum(len(acao.produtos) for acao in acoes)  # Calcula o total de produtos
    return render_template('gerente.html', acoes=acoes, total_produtos=total_produtos)

@app.route('/aprovar_acao', methods=['POST'])
@login_required
def aprovar_acao():
    if current_user.role != 'gerente':
        return redirect(url_for('dashboard'))
    
    acoes_ids = request.form.getlist('acao_ids')
    acao = request.form.get('action')  # 'aprovar' ou 'reprovar'

    for acao_id in acoes_ids:
        acao_obj = Acao.query.get(acao_id)
        if acao == 'aprovar':
            acao_obj.status = 'aprovado'
        elif acao == 'reprovar':
            acao_obj.status = 'reprovado'
    
    db.session.commit()

    if acao == 'aprovar':
        flash('Ações aprovadas com sucesso!', 'success')
    else:
        flash('Ações reprovadas com sucesso!', 'warning')
    
    return redirect(url_for('dashboard_gerente'))

@app.route('/gerar_relatorio', methods=['GET', 'POST'])
@login_required
def gerar_relatorio():
    if current_user.role != 'gerente':
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        filtro_vendedor = request.form.get('filtro_vendedor')
        filtro_cliente = request.form.get('filtro_cliente')
        
        query = Acao.query
        if filtro_vendedor:
            query = query.filter(Acao.user.has(username=filtro_vendedor))
        if filtro_cliente:
            query = query.filter_by(cliente_codigo=filtro_cliente)
        
        acoes = query.all()
    else:
        acoes = Acao.query.all()
    
    data = []
    for acao in acoes:
        for produto in acao.produtos:
            desconto = ((produto.valor_atual - produto.valor_desejado) / produto.valor_atual) * 100
            linha = {
                'Vendedor': acao.user.username,
                'Cliente': acao.cliente_codigo,
                'Produto': produto.codigo,
                'Valor Atual': produto.valor_atual,
                'Valor Desejado': produto.valor_desejado,
                'Valor Final': produto.valor_final,
                'Desconto (%)': round(desconto, 2),
                'Tipo': acao.tipo
            }
            
            if acao.tipo == 'MOB' and acao.meio_pagamento:
                linha['% Meio Pagamento'] = acao.meio_pagamento.desconto_percentual
            
            data.append(linha)
    
    df = pd.DataFrame(data)
    df.to_excel('relatorio_acoes.xlsx', index=False)
    return send_file('relatorio_acoes.xlsx', as_attachment=True)

# --- Suporte ---
@app.route('/suporte')
@login_required
def dashboard_suporte():
    if current_user.role != 'suporte':
        return redirect(url_for('dashboard'))
    
    acoes = Acao.query.all()  # Passa todas as ações, como no dashboard do gerente
    usuarios = User.query.all()
    return render_template('suporte.html', acoes=acoes, usuarios=usuarios)

@app.route('/concluir_acao/<int:id>')
@login_required
def concluir_acao(id):
    if current_user.role != 'suporte':
        return redirect(url_for('dashboard'))
    
    acao = Acao.query.get_or_404(id)
    acao.status = 'concluido'
    db.session.commit()
    flash('Ação concluída!', 'success')
    return redirect(url_for('dashboard_suporte'))

@app.route('/meios_pagamento', methods=['GET', 'POST'])
@login_required
def meios_pagamento():
    if current_user.role != 'suporte':
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        nome = request.form['nome']
        desconto = float(request.form['desconto'])
        
        novo_meio = MeioPagamento(nome=nome, desconto_percentual=desconto)
        db.session.add(novo_meio)
        db.session.commit()
        flash('Meio de pagamento criado!', 'success')
        return redirect(url_for('meios_pagamento'))
    
    meios = MeioPagamento.query.all()
    return render_template('meios_pagamento.html', meios=meios)

@app.route('/toggle_meio_pagamento/<int:id>')
@login_required
def toggle_meio_pagamento(id):
    if current_user.role != 'suporte':
        return redirect(url_for('dashboard'))
    
    meio = MeioPagamento.query.get_or_404(id)
    meio.ativo = not meio.ativo
    db.session.commit()
    flash('Status atualizado!', 'success')
    return redirect(url_for('meios_pagamento'))

@app.route('/excluir_meio_pagamento/<int:id>')
@login_required
def excluir_meio_pagamento(id):
    if current_user.role != 'suporte':
        return redirect(url_for('dashboard'))
    
    meio = MeioPagamento.query.get_or_404(id)
    db.session.delete(meio)
    db.session.commit()
    flash('Meio de pagamento excluído!', 'success')
    return redirect(url_for('meios_pagamento'))

@app.route('/criar_usuario', methods=['POST'])
@login_required
def criar_usuario():
    if current_user.role != 'suporte':
        return redirect(url_for('dashboard'))
    
    username = request.form['username']
    if User.query.filter_by(username=username).first():
        flash('Nome de usuário já existe!', 'danger')
        return redirect(url_for('dashboard_suporte'))
    
    password = generate_password_hash(request.form['password'])
    role = request.form['role']
    
    novo_usuario = User(username=username, password=password, role=role)
    db.session.add(novo_usuario)
    db.session.commit()
    
    flash('Usuário criado com sucesso!', 'success')
    return redirect(url_for('dashboard_suporte'))

@app.route('/editar_usuario/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_usuario(id):
    if current_user.role != 'suporte':
        return redirect(url_for('dashboard'))
    
    usuario = User.query.get_or_404(id)
    
    if request.method == 'POST':
        usuario.username = request.form['username']
        usuario.role = request.form['role']
        if request.form['password']:
            usuario.password = generate_password_hash(request.form['password'])
        db.session.commit()
        flash('Usuário atualizado com sucesso!', 'success')
        return redirect(url_for('dashboard_suporte'))
    
    return render_template('editar_usuario.html', usuario=usuario)

@app.route('/excluir_usuario/<int:id>')
@login_required
def excluir_usuario(id):
    if current_user.role != 'suporte':
        return redirect(url_for('dashboard'))
    
    usuario = User.query.get_or_404(id)
    db.session.delete(usuario)
    db.session.commit()
    flash('Usuário excluído com sucesso!', 'success')
    return redirect(url_for('dashboard_suporte'))

if __name__ == '__main__':
    app.run(debug=True)
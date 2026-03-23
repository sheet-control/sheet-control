from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = "sheetcontrol_chave_secreta_2311"

def usuario_logado():
    return session.get("logado") == True

def get_db():
    return sqlite3.connect("banco.db")

def add_months(date_obj, months):
    month = date_obj.month - 1 + months
    year = date_obj.year + month // 12
    month = month % 12 + 1

    day = min(date_obj.day, [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31
    ][month - 1])

    return date_obj.replace(year=year, month=month, day=day)

def parse_brl_number(value):
    if not value:
        return 0.0
    return float(str(value).strip().replace(".", "").replace(",", "."))

def format_date_br(data_str):
    if not data_str:
        return ""
    try:
        return datetime.strptime(data_str, "%Y-%m-%d").strftime("%d/%m/%Y")
    except:
        return data_str

def format_brl(valor):
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def calcular_dias(vencimento, pagamento):
    data_prev = datetime.strptime(vencimento, "%Y-%m-%d").date()
    data_pag = datetime.strptime(pagamento, "%Y-%m-%d").date()

    diff = (data_pag - data_prev).days

    if diff == 0:
        return "Em dia"
    elif diff > 0:
        return f"{diff} dia(s) de atraso"
    else:
        return f"{abs(diff)} dia(s) adiantado"

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artista TEXT,
            cidade TEXT,
            data_show TEXT,
            valor_total REAL,
            iss_pct REAL,
            ir_pct REAL,
            num_parcelas INTEGER,
            primeiro_vencimento TEXT,
            tributo_momento TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS parcelas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            show_id INTEGER,
            numero_parcela INTEGER,
            valor_bruto REAL,
            valor_iss REAL,
            valor_ir REAL,
            valor_liquido REAL,
            status TEXT,
            vencimento_previsto TEXT,
            data_pagamento TEXT,
            dias_pagamento TEXT
        )
    """)

    conn.commit()
    conn.close()

@app.route("/login", methods=["GET", "POST"])
def login():
    if usuario_logado():
        return redirect(url_for("index"))

    erro = ""

    if request.method == "POST":
        usuario = request.form["usuario"]
        senha = request.form["senha"]

        if usuario == "admin" and senha == "123456":
            session["logado"] = True
            session["usuario"] = usuario
            return redirect(url_for("index"))
        else:
            erro = "Usuário ou senha inválidos."

    return render_template("login.html", erro=erro)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def index():
    if not usuario_logado():
        return redirect(url_for("login"))

    conn = get_db()

    shows = conn.execute("""
        SELECT id, artista, cidade, data_show, valor_total,
               iss_pct, ir_pct, num_parcelas, primeiro_vencimento, tributo_momento
        FROM shows
        ORDER BY id DESC
    """).fetchall()

    total_shows = conn.execute("SELECT COUNT(*) FROM shows").fetchone()[0]

    total_recebido = conn.execute("""
        SELECT COALESCE(SUM(valor_liquido), 0)
        FROM parcelas
        WHERE status = 'Recebido'
    """).fetchone()[0]

    total_a_receber = conn.execute("""
        SELECT COALESCE(SUM(valor_liquido), 0)
        FROM parcelas
        WHERE status = 'A Receber'
    """).fetchone()[0]

    conn.close()

    return render_template(
        "index.html",
        shows=shows,
        total_shows=total_shows,
        total_recebido=format_brl(total_recebido),
        total_a_receber=format_brl(total_a_receber),
        format_date_br=format_date_br,
        format_brl=format_brl
    )

@app.route("/add", methods=["POST"])
def add():
    if not usuario_logado():
        return redirect(url_for("login"))

    artista = request.form["artista"]
    cidade = request.form["cidade"]
    data_show = request.form["data_show"]
    valor_total = parse_brl_number(request.form["valor_total"])
    iss_pct = parse_brl_number(request.form["iss_pct"])
    ir_pct = parse_brl_number(request.form["ir_pct"])
    num_parcelas = int(request.form["num_parcelas"])
    primeiro_vencimento = request.form["primeiro_vencimento"]
    tributo_momento = request.form["tributo_momento"]

    conn = get_db()
    c = conn.cursor()

    c.execute("""
        INSERT INTO shows (
            artista, cidade, data_show, valor_total,
            iss_pct, ir_pct, num_parcelas, primeiro_vencimento, tributo_momento
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        artista, cidade, data_show, valor_total,
        iss_pct, ir_pct, num_parcelas, primeiro_vencimento, tributo_momento
    ))

    show_id = c.lastrowid

    valor_base = round(valor_total / num_parcelas, 2)
    valores = [valor_base] * num_parcelas

    diferenca = round(valor_total - sum(valores), 2)
    valores[-1] = round(valores[-1] + diferenca, 2)

    data_base = datetime.strptime(primeiro_vencimento, "%Y-%m-%d")

    for i in range(num_parcelas):
        bruto = valores[i]

        valor_iss = 0.0
        valor_ir = 0.0

        if (tributo_momento == "INICIO" and i == 0) or \
           (tributo_momento == "FINAL" and i == num_parcelas - 1):
            valor_iss = round(bruto * (iss_pct / 100), 2)
            valor_ir = round(bruto * (ir_pct / 100), 2)

        liquido = round(bruto - valor_iss - valor_ir, 2)
        vencimento = add_months(data_base, i).strftime("%Y-%m-%d")

        c.execute("""
            INSERT INTO parcelas (
                show_id, numero_parcela, valor_bruto, valor_iss,
                valor_ir, valor_liquido, status,
                vencimento_previsto, data_pagamento, dias_pagamento
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            show_id,
            i + 1,
            bruto,
            valor_iss,
            valor_ir,
            liquido,
            "A Receber",
            vencimento,
            "",
            ""
        ))

    conn.commit()
    conn.close()

    return redirect("/")

@app.route("/editar_show/<int:show_id>")
def editar_show(show_id):
    if not usuario_logado():
        return redirect(url_for("login"))

    conn = get_db()
    show = conn.execute("""
        SELECT id, artista, cidade, data_show, valor_total,
               iss_pct, ir_pct, num_parcelas, primeiro_vencimento, tributo_momento
        FROM shows
        WHERE id = ?
    """, (show_id,)).fetchone()
    conn.close()

    return render_template("editar_show.html", show=show, format_brl=format_brl)

@app.route("/atualizar_show/<int:show_id>", methods=["POST"])
def atualizar_show(show_id):
    if not usuario_logado():
        return redirect(url_for("login"))

    artista = request.form["artista"]
    cidade = request.form["cidade"]
    data_show = request.form["data_show"]
    valor_total = parse_brl_number(request.form["valor_total"])
    iss_pct = parse_brl_number(request.form["iss_pct"])
    ir_pct = parse_brl_number(request.form["ir_pct"])
    num_parcelas = int(request.form["num_parcelas"])
    primeiro_vencimento = request.form["primeiro_vencimento"]
    tributo_momento = request.form["tributo_momento"]

    conn = get_db()
    c = conn.cursor()

    c.execute("""
        UPDATE shows
        SET artista = ?, cidade = ?, data_show = ?, valor_total = ?,
            iss_pct = ?, ir_pct = ?, num_parcelas = ?, primeiro_vencimento = ?, tributo_momento = ?
        WHERE id = ?
    """, (
        artista, cidade, data_show, valor_total,
        iss_pct, ir_pct, num_parcelas, primeiro_vencimento, tributo_momento, show_id
    ))

    c.execute("DELETE FROM parcelas WHERE show_id = ?", (show_id,))

    valor_base = round(valor_total / num_parcelas, 2)
    valores = [valor_base] * num_parcelas

    diferenca = round(valor_total - sum(valores), 2)
    valores[-1] = round(valores[-1] + diferenca, 2)

    data_base = datetime.strptime(primeiro_vencimento, "%Y-%m-%d")

    for i in range(num_parcelas):
        bruto = valores[i]

        valor_iss = 0.0
        valor_ir = 0.0

        if (tributo_momento == "INICIO" and i == 0) or \
           (tributo_momento == "FINAL" and i == num_parcelas - 1):
            valor_iss = round(bruto * (iss_pct / 100), 2)
            valor_ir = round(bruto * (ir_pct / 100), 2)

        liquido = round(bruto - valor_iss - valor_ir, 2)
        vencimento = add_months(data_base, i).strftime("%Y-%m-%d")

        c.execute("""
            INSERT INTO parcelas (
                show_id, numero_parcela, valor_bruto, valor_iss,
                valor_ir, valor_liquido, status,
                vencimento_previsto, data_pagamento, dias_pagamento
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            show_id,
            i + 1,
            bruto,
            valor_iss,
            valor_ir,
            liquido,
            "A Receber",
            vencimento,
            "",
            ""
        ))

    conn.commit()
    conn.close()

    return redirect("/")

@app.route("/parcelas/<int:show_id>")
def parcelas(show_id):
    if not usuario_logado():
        return redirect(url_for("login"))

    conn = get_db()

    show = conn.execute("""
        SELECT * FROM shows WHERE id = ?
    """, (show_id,)).fetchone()

    parcelas = conn.execute("""
        SELECT * FROM parcelas
        WHERE show_id = ?
        ORDER BY numero_parcela
    """, (show_id,)).fetchall()

    conn.close()

    hoje = date.today().strftime("%Y-%m-%d")

    return render_template(
        "parcelas.html",
        show=show,
        parcelas=parcelas,
        hoje=hoje,
        format_date_br=format_date_br,
        format_brl=format_brl
    )

@app.route("/receber/<int:parcela_id>/<int:show_id>", methods=["POST"])
def receber(parcela_id, show_id):
    if not usuario_logado():
        return redirect(url_for("login"))

    data_pagamento = request.form["data_pagamento"]

    conn = get_db()

    parcela = conn.execute("""
        SELECT vencimento_previsto
        FROM parcelas
        WHERE id = ?
    """, (parcela_id,)).fetchone()

    dias = calcular_dias(parcela[0], data_pagamento)

    conn.execute("""
        UPDATE parcelas
        SET status = 'Recebido',
            data_pagamento = ?,
            dias_pagamento = ?
        WHERE id = ?
    """, (data_pagamento, dias, parcela_id))

    conn.commit()
    conn.close()

    return redirect(f"/parcelas/{show_id}")

@app.route("/excluir_show/<int:show_id>", methods=["POST"])
def excluir_show(show_id):
    if not usuario_logado():
        return redirect(url_for("login"))

    conn = get_db()
    c = conn.cursor()

    c.execute("DELETE FROM parcelas WHERE show_id = ?", (show_id,))
    c.execute("DELETE FROM shows WHERE id = ?", (show_id,))

    conn.commit()
    conn.close()

    return redirect("/")

if __name__ == "__main__":
    init_db()
    app.run()
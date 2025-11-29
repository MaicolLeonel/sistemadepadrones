from flask import Flask, render_template, request, redirect, url_for, send_file
import sqlite3
import pandas as pd
import io
import os

app = Flask(__name__)

# ============================================================
#  BASE GENERAL DE USUARIOS
# ============================================================

USERS_DB = "usuarios.db"


def init_usuarios_db():
    conn = sqlite3.connect(USERS_DB)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def get_usuarios():
    conn = sqlite3.connect(USERS_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre FROM usuarios ORDER BY id DESC")
    users = cursor.fetchall()
    conn.close()
    return users


def crear_usuario(nombre):
    conn = sqlite3.connect(USERS_DB)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO usuarios (nombre) VALUES (?)", (nombre,))
    conn.commit()
    conn.close()


init_usuarios_db()


# ============================================================
#  DB PRIVADA PARA CADA USUARIO
# ============================================================

def get_db_path(user: str) -> str:
    path = os.path.join(os.getcwd(), f"padron_{user}.db")
    return path


def init_user_db(user):
    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS padrones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS socios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            padron_id INTEGER,
            nombre TEXT,
            dni TEXT,
            voto INTEGER DEFAULT 0,
            FOREIGN KEY (padron_id) REFERENCES padrones(id)
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
#  PADRONES POR USUARIO
# ============================================================

def get_padrones(user):
    init_user_db(user)
    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre FROM padrones ORDER BY id DESC")
    padrones = cursor.fetchall()
    conn.close()
    return padrones


def crear_padron(user, nombre):
    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO padrones (nombre) VALUES (?)", (nombre,))
    conn.commit()
    conn.close()


# ============================================================
#  SOCIOS
# ============================================================

def get_socios(user, padron_id, buscar=""):
    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()

    if buscar:
        like = f"%{buscar.lower()}%"
        cursor.execute("""
            SELECT id, nombre, dni, voto
            FROM socios
            WHERE padron_id = ?
              AND (lower(nombre) LIKE ? OR lower(dni) LIKE ?)
            ORDER BY nombre
        """, (padron_id, like, like))
    else:
        cursor.execute("""
            SELECT id, nombre, dni, voto
            FROM socios
            WHERE padron_id = ?
            ORDER BY nombre
        """, (padron_id,))

    socios = cursor.fetchall()
    conn.close()
    return socios


def get_resumen_padron(user, padron_id):
    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN voto = 1 THEN 1 ELSE 0 END)
        FROM socios
        WHERE padron_id = ?
    """, (padron_id,))
    total, votaron = cursor.fetchone()
    total = total or 0
    votaron = votaron or 0
    restan = total - votaron

    conn.close()
    return total, votaron, restan


# ============================================================
#        PROCESAR ARCHIVO EXCEL — MEJORADO AL MÁXIMO
# ============================================================

def process_file(file):
    # ============================
    #   LECTURA DEL ARCHIVO
    # ============================
    if file.filename.endswith((".xlsx", ".xls")):
        df = pd.read_excel(file, dtype=str)
    elif file.filename.endswith(".csv"):
        df = pd.read_csv(file, dtype=str)
    else:
        return None, "Formato no soportado (solo Excel o CSV)"

    # Normalizar nombres de columnas
    df.columns = df.columns.str.lower().str.strip().str.replace(" ", "")

    # Buscar columnas relevantes
    col_apellido = next((c for c in df.columns if "apellido" in c), None)
    col_nombre = next((c for c in df.columns if "nombre" in c and c != col_apellido), None)
    col_dni = next((c for c in df.columns if "dni" in c), None)

    # Validar que exista DNI
    if not col_dni:
        return None, f"No se encontró la columna DNI. Columnas detectadas: {list(df.columns)}"

    # ============================
    #   GENERAR NOMBRE COMPLETO
    # ============================
    if col_apellido and col_nombre:
        df["full"] = (
            df[col_apellido].fillna("") + " " +
            df[col_nombre].fillna("")
        )
    elif col_apellido:
        df["full"] = df[col_apellido].fillna("")
    elif col_nombre:
        df["full"] = df[col_nombre].fillna("")
    else:
        df["full"] = df[df.columns[0]].fillna("")

    # Quitar espacios repetidos y normalizar
    df["full"] = df["full"].astype(str)
    df["full"] = df["full"].str.replace(r"\s+", " ", regex=True)
    df["full"] = df["full"].str.strip()
    df["full"] = df["full"].str.upper()

    # Normalizar DNI
    df[col_dni] = df[col_dni].astype(str)
    df[col_dni] = df[col_dni].str.replace(r"\D", "", regex=True).str.strip()

    # Filtrar columnas importantes
    df_clean = df[["full", col_dni]].copy()
    df_clean.columns = ["nombre", "dni"]

    # Eliminar duplicados reales
    df_clean = df_clean.drop_duplicates()

    # Eliminar filas vacías o inválidas
    df_clean = df_clean[(df_clean["nombre"] != "") & (df_clean["dni"] != "")]

    return df_clean, None


# ============================================================
#  RUTAS PRINCIPALES
# ============================================================

@app.route("/")
def home():
    usuarios = get_usuarios()
    return render_template("usuarios.html", usuarios=usuarios)


@app.route("/usuarios/nuevo", methods=["POST"])
def nuevo_usuario():
    nombre = request.form.get("nombre", "").strip()
    if nombre:
        crear_usuario(nombre)
        init_user_db(nombre)
    return redirect(url_for("home"))


@app.route("/panel/<user>/padrones", methods=["GET", "POST"])
def padrones(user):
    if request.method == "POST":
        nombre = request.form.get("nombre_padron", "").strip()
        if nombre:
            crear_padron(user, nombre)
        return redirect(url_for("padrones", user=user))

    lista = get_padrones(user)
    return render_template("select_padron.html", user=user, padrones=lista)


@app.route("/panel/<user>/padron/<int:padron_id>", methods=["GET", "POST"])
def panel_padron(user, padron_id):
    if request.method == "POST":
        file = request.files.get("file")
        if not file:
            return "No seleccionaste archivo."

        df_clean, error = process_file(file)
        if error:
            return error

        db = get_db_path(user)
        conn = sqlite3.connect(db)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM socios WHERE padron_id = ?", (padron_id,))

        for _, row in df_clean.iterrows():
            cursor.execute("""
                INSERT INTO socios (padron_id, nombre, dni)
                VALUES (?, ?, ?)
            """, (padron_id, row["nombre"], row["dni"]))

        conn.commit()
        conn.close()

        return redirect(url_for("panel_padron", user=user, padron_id=padron_id))

    buscar = request.args.get("buscar", "").strip()
    socios = get_socios(user, padron_id, buscar)
    total, votaron, restan = get_resumen_padron(user, padron_id)

    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("SELECT nombre FROM padrones WHERE id = ?", (padron_id,))
    nombre_padron = cursor.fetchone()[0]
    conn.close()

    return render_template(
        "padron.html",
        user=user,
        padron_id=padron_id,
        nombre_padron=nombre_padron,
        socios=socios,
        total=total,
        votaron=votaron,
        restan=restan,
        buscar=buscar
    )


@app.route("/panel/<user>/padron/<int:padron_id>/votar/<int:socio_id>")
def votar(user, padron_id, socio_id):
    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("UPDATE socios SET voto = 1 WHERE id = ? AND padron_id = ?", (socio_id, padron_id))
    conn.commit()
    conn.close()
    return redirect(url_for("panel_padron", user=user, padron_id=padron_id))


@app.route("/panel/<user>/padron/<int:padron_id>/borrar/<int:socio_id>")
def borrar(user, padron_id, socio_id):
    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM socios WHERE id = ? AND padron_id = ?", (socio_id, padron_id))
    conn.commit()
    conn.close()
    return redirect(url_for("panel_padron", user=user, padron_id=padron_id))


@app.route("/panel/<user>/padron/<int:padron_id>/agregar", methods=["POST"])
def agregar(user, padron_id):
    apellido = request.form.get("apellido", "").strip()
    nombre = request.form.get("nombre", "").strip()
    dni = request.form.get("dni", "").strip()

    if apellido and nombre and dni:
        nombre_final = f"{apellido} {nombre}"
        db = get_db_path(user)
        conn = sqlite3.connect(db)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO socios (padron_id, nombre, dni)
            VALUES (?, ?, ?)
        """, (padron_id, nombre_final, dni))
        conn.commit()
        conn.close()

    return redirect(url_for("panel_padron", user=user, padron_id=padron_id))


@app.route("/panel/<user>/padron/<int:padron_id>/descargar")
def descargar(user, padron_id):
    socios = get_socios(user, padron_id, "")
    df = pd.DataFrame(socios, columns=["ID", "Nombre", "DNI", "Voto"])
    df["Voto"] = df["Voto"].map({1: "VOTÓ", 0: "NO VOTÓ"})

    total = len(df)
    votaron = (df["Voto"] == "VOTÓ").sum()
    restan = total - votaron

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Padrón")

        resumen = pd.DataFrame({
            "Descripción": ["Total", "Votaron", "Faltan"],
            "Cantidad": [total, votaron, restan]
        })
        resumen.to_excel(writer, index=False, sheet_name="Padrón", startrow=len(df) + 2)

    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f"padron_{user}_{padron_id}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


if __name__ == "__main__":
    app.run(debug=True)

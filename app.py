import os
import re
import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv

load_dotenv()

from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__, static_folder="frontend", static_url_path="")

app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )

def init_db():
    conn = None
    curr = None
    try:
        conn = get_db()
        curr = conn.cursor()
        curr.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        conn.commit()
        return True
    except psycopg2.OperationalError as exc:
        print(f"Warning: Could not initialize database at startup: {exc}")
        return False
    finally:
        if curr:
            curr.close()
        if conn:
            conn.close()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login_page"

class User(UserMixin):  # tracks who is logged in during a session
    def __init__(self, id, email):
        self.id = id
        self.email = email

@login_manager.user_loader
def load_user(user_id):
    conn = None
    curr = None
    try:
        conn = get_db()
        curr = conn.cursor()
        curr.execute("SELECT id, email FROM users WHERE id = %s", (user_id,))
        row = curr.fetchone()
    except psycopg2.OperationalError:
        return None
    finally:
        if curr:
            curr.close()
        if conn:
            conn.close()
    if row:
        return User(row["id"], row["email"])
    return None


@app.errorhandler(psycopg2.OperationalError)
def handle_db_operational_error(_exc):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Database unavailable. Check DATABASE_URL (or DB_HOST/DB_PORT) and try again."}), 503
    return "Database unavailable. Please start PostgreSQL or update your DB connection settings.", 503


@app.route("/")
@login_required
def index():
    return send_from_directory("frontend", "index.html")


@app.route("/api/stats")
@login_required
def stats():
    conn = get_db()
    curr = conn.cursor()
    curr.execute("""
        SELECT
            COUNT(*) AS total,
            MIN(date_of_licensure) AS earliest,
            MAX(date_of_licensure) AS latest
        FROM rn_licenses
    """)
    row = curr.fetchone()
    curr.close()
    conn.close()
    return jsonify({
        "total": row["total"],
        "earliest": str(row["earliest"]) if row["earliest"] else None,
        "latest": str(row["latest"]) if row["latest"] else None,
    })


VALID_SORT_COLS = {"name", "license_number", "address", "date_of_licensure", "profession"}


@app.route("/api/licenses")
@login_required
def licenses():
    name = request.args.get("name", "").strip()
    address = request.args.get("address", "").strip()
    license_number = request.args.get("license_number", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    match_type = request.args.get("match_type", "contains").strip().lower()
    sort_by = request.args.get("sort_by", "name")
    sort_dir = "DESC" if request.args.get("sort_dir", "asc").lower() == "desc" else "ASC"
    export = request.args.get("export", "").lower() == "true"

    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        per_page = min(100, max(10, int(request.args.get("per_page", 25))))
    except ValueError:
        per_page = 25

    if sort_by not in VALID_SORT_COLS:
        sort_by = "name"

    if match_type not in {"contains", "starts", "exact", "word"}:
        match_type = "contains"

    conditions = []
    params = []

    def add_text_filter(column, value):
        if not value:
            return
        if match_type == "contains":
            conditions.append(f"{column} ILIKE %s")
            params.append(f"%{value}%")
        elif match_type == "starts":
            conditions.append(f"{column} ILIKE %s")
            params.append(f"{value}%")
        elif match_type == "exact":
            conditions.append(f"{column} ILIKE %s")
            params.append(value)
        else:
            conditions.append(f"{column} ~* %s")
            params.append(rf"\m{re.escape(value)}\M")

    add_text_filter("name", name)
    add_text_filter("address", address)
    add_text_filter("license_number", license_number)
    if date_from:
        conditions.append("date_of_licensure >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("date_of_licensure <= %s")
        params.append(date_to)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    conn = get_db()
    curr = conn.cursor()

    curr.execute(f"SELECT COUNT(*) AS total FROM rn_licenses {where}", params)
    total = curr.fetchone()["total"]

    if export:
        curr.execute(
            f"SELECT license_number, name, profession, address, date_of_licensure "
            f"FROM rn_licenses {where} ORDER BY {sort_by} {sort_dir}",
            params,
        )
    else:
        offset = (page - 1) * per_page
        curr.execute(
            f"SELECT license_number, name, profession, address, date_of_licensure "
            f"FROM rn_licenses {where} ORDER BY {sort_by} {sort_dir} LIMIT %s OFFSET %s",
            params + [per_page, offset],
        )

    rows = curr.fetchall()
    curr.close()
    conn.close()

    results = []
    for r in rows:
        results.append({
            "license_number": r["license_number"],
            "name": r["name"],
            "profession": r["profession"],
            "address": r["address"],
            "date_of_licensure": str(r["date_of_licensure"]) if r["date_of_licensure"] else None,
        })

    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "results": results,
    })


@app.route("/api/licenses/<license_number>")
@login_required
def license_detail(license_number):
    conn = get_db()
    curr = conn.cursor()
    curr.execute("SELECT * FROM rn_licenses WHERE license_number = %s", (license_number,))
    row = curr.fetchone()
    curr.close()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({
        "license_number": row["license_number"],
        "name": row["name"],
        "profession": row["profession"],
        "address": row["address"],
        "date_of_licensure": str(row["date_of_licensure"]) if row["date_of_licensure"] else None,
    })

# create login page route and api endpoints for login/logout
@app.route("/login")
def login_page():
    return send_from_directory("frontend", "login.html")

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    conn = None
    curr = None
    try:
        conn = get_db()
        curr = conn.cursor()
        curr.execute("SELECT id, email, password_hash FROM users WHERE email = %s", (email,))
        row = curr.fetchone()
    except psycopg2.OperationalError:
        return jsonify({"error": "Database unavailable. Check DATABASE_URL (or DB_HOST/DB_PORT) and try again."}), 503
    finally:
        if curr:
            curr.close()
        if conn:
            conn.close()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401
    login_user(User(row["id"], row["email"]), remember=True)
    return jsonify({"ok": True})

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    conn = None
    curr = None
    try:
        conn = get_db()
        curr = conn.cursor()
        curr.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
            (email, generate_password_hash(password))
        )
        conn.commit()
    except psycopg2.OperationalError:
        return jsonify({"error": "Database unavailable. Check DATABASE_URL (or DB_HOST/DB_PORT) and try again."}), 503
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({"error": "An account with that email already exists"}), 409
    finally:
        if curr:
            curr.close()
        if conn:
            conn.close()
    return jsonify({"ok": True})

@app.route("/api/logout", methods=["POST"])
@login_required
def api_logout():
    logout_user()
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", "5001"))
    app.run(host="0.0.0.0", debug=False, port=port)

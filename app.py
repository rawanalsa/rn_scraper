import os
import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="frontend", static_url_path="")

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


@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")


@app.route("/api/stats")
def stats():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COUNT(*) AS total,
            MIN(date_of_licensure) AS earliest,
            MAX(date_of_licensure) AS latest
        FROM rn_licenses
    """)
    row = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify({
        "total": row["total"],
        "earliest": str(row["earliest"]) if row["earliest"] else None,
        "latest": str(row["latest"]) if row["latest"] else None,
    })


VALID_SORT_COLS = {"name", "license_number", "address", "date_of_licensure", "profession"}


@app.route("/api/licenses")
def licenses():
    name = request.args.get("name", "").strip()
    address = request.args.get("address", "").strip()
    license_number = request.args.get("license_number", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
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

    conditions = []
    params = []
    if name:
        conditions.append("name ILIKE %s")
        params.append(f"%{name}%")
    if address:
        conditions.append("address ILIKE %s")
        params.append(f"%{address}%")
    if license_number:
        conditions.append("license_number ILIKE %s")
        params.append(f"%{license_number}%")
    if date_from:
        conditions.append("date_of_licensure >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("date_of_licensure <= %s")
        params.append(date_to)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    conn = get_db()
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) AS total FROM rn_licenses {where}", params)
    total = cur.fetchone()["total"]

    if export:
        cur.execute(
            f"SELECT license_number, name, profession, address, date_of_licensure "
            f"FROM rn_licenses {where} ORDER BY {sort_by} {sort_dir}",
            params,
        )
    else:
        offset = (page - 1) * per_page
        cur.execute(
            f"SELECT license_number, name, profession, address, date_of_licensure "
            f"FROM rn_licenses {where} ORDER BY {sort_by} {sort_dir} LIMIT %s OFFSET %s",
            params + [per_page, offset],
        )

    rows = cur.fetchall()
    cur.close()
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
def license_detail(license_number):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rn_licenses WHERE license_number = %s", (license_number,))
    row = cur.fetchone()
    cur.close()
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


if __name__ == "__main__":
    app.run(debug=True, port=5000)

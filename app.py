from contextlib import contextmanager
from datetime import date
from functools import wraps
from pathlib import Path
import os
import re
import sqlite3

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Configuration
#   * DATABASE_URL (or POSTGRES_URL) set -> permanent Postgres (Neon etc.)
#   * otherwise                          -> local SQLite file
#     (on Vercel without a database URL, SQLite lives in temporary /tmp)
#   * SECRET_KEY signs the login cookie. REQUIRED on Vercel.
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
USE_POSTGRES = bool(DATABASE_URL)
ON_VERCEL = bool(os.environ.get("VERCEL"))

if ON_VERCEL:
    DATABASE = Path("/tmp/adc_brew_cafe.db")
else:
    DATABASE = BASE_DIR / "adc_brew_cafe.db"

SECRET_KEY = os.environ.get("SECRET_KEY") or (None if ON_VERCEL else "dev-only-change-me")

# Works whether index.html is in a "templates" folder or next to app.py
TEMPLATE_DIR = BASE_DIR / "templates" if (BASE_DIR / "templates" / "index.html").exists() else BASE_DIR

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
app.secret_key = SECRET_KEY
app.config["JSON_SORT_KEYS"] = False
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = ON_VERCEL
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 14  # 14 days

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

MENU_ITEMS = [
    {"id": 1, "category": "coffee", "name": "ADC Signature Latte", "description": "Silky espresso, steamed milk, and a little everyday luxury.", "price": 180},
    {"id": 2, "category": "coffee", "name": "Classic Cappuccino", "description": "A rich espresso under a cloud of soft milk foam.", "price": 160},
    {"id": 3, "category": "coffee", "name": "Caramel Macchiato", "description": "Espresso, creamy milk, and a delicate caramel finish.", "price": 190},
    {"id": 4, "category": "coffee", "name": "Masala Chai", "description": "Comfort in a cup, brewed with warming Indian spices.", "price": 90},
    {"id": 5, "category": "bakes", "name": "Butter Croissant", "description": "Golden, flaky layers baked for a slow morning.", "price": 130},
    {"id": 6, "category": "bakes", "name": "Chocolate Brownie", "description": "Deep cocoa, a soft centre, and just the right bite.", "price": 140},
    {"id": 7, "category": "bakes", "name": "Blueberry Muffin", "description": "A tender bake with juicy berries in every bite.", "price": 120},
    {"id": 8, "category": "cold", "name": "Classic Iced Latte", "description": "Chilled espresso and milk over ice. Simple, refreshing.", "price": 180},
    {"id": 9, "category": "cold", "name": "Cold Coffee", "description": "Blended smooth, creamy, and ready for sunny days.", "price": 170},
    {"id": 10, "category": "cold", "name": "Mocha Frappe", "description": "Coffee and chocolate in a cool, indulgent blend.", "price": 210},
]

MENU_BY_ID = {item["id"]: item for item in MENU_ITEMS}

# ---------------------------------------------------------------------------
# Database layer (works with SQLite and Postgres)
# ---------------------------------------------------------------------------
SQLITE_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT,
        guests INTEGER NOT NULL CHECK (guests BETWEEN 1 AND 8),
        visit_date TEXT NOT NULL,
        visit_time TEXT NOT NULL,
        message TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS contact_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        total INTEGER NOT NULL,
        note TEXT,
        status TEXT NOT NULL DEFAULT 'placed',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES orders(id),
        item_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        quantity INTEGER NOT NULL
    )""",
]

POSTGRES_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS reservations (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT,
        guests INTEGER NOT NULL CHECK (guests BETWEEN 1 AND 8),
        visit_date TEXT NOT NULL,
        visit_time TEXT NOT NULL,
        message TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS contact_messages (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS orders (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id),
        total INTEGER NOT NULL,
        note TEXT,
        status TEXT NOT NULL DEFAULT 'placed',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS order_items (
        id BIGSERIAL PRIMARY KEY,
        order_id BIGINT NOT NULL REFERENCES orders(id),
        item_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        quantity INTEGER NOT NULL
    )""",
]

_db_ready = False


def connect_postgres():
    import psycopg  # imported here so local SQLite use does not need it
    from psycopg.rows import dict_row

    # prepare_threshold=None keeps it compatible with Neon's pooled connections
    return psycopg.connect(DATABASE_URL, prepare_threshold=None, row_factory=dict_row)


def _clean(row):
    """Turn a database row into a plain dict with JSON-friendly values."""
    out = {}
    for key, value in dict(row).items():
        out[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


class Db:
    """Tiny helper so the same SQL (written with ? marks) runs on both databases."""

    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        if USE_POSTGRES:
            sql = sql.replace("?", "%s")
        return self.conn.execute(sql, tuple(params))

    def one(self, sql, params=()):
        row = self.execute(sql, params).fetchone()
        return _clean(row) if row else None

    def all(self, sql, params=()):
        return [_clean(row) for row in self.execute(sql, params).fetchall()]

    def insert(self, sql, params=()):
        """Run an INSERT and return the new row's id."""
        if USE_POSTGRES:
            return self.execute(sql + " RETURNING id", params).fetchone()["id"]
        return self.execute(sql, params).lastrowid


@contextmanager
def db():
    """Open a connection; commits on success, rolls back on error, always closes."""
    global _db_ready
    if USE_POSTGRES:
        with connect_postgres() as conn:
            handle = Db(conn)
            if not _db_ready:
                for statement in POSTGRES_SCHEMA:
                    handle.execute(statement)
                _db_ready = True
            yield handle
    else:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                handle = Db(conn)
                if not _db_ready:
                    for statement in SQLITE_SCHEMA:
                        handle.execute(statement)
                    _db_ready = True
                yield handle
        finally:
            conn.close()


DB_ERROR = "Sorry, we could not complete that right now. Please try again shortly."


def db_error():
    return jsonify({"error": DB_ERROR}), 503


# ---------------------------------------------------------------------------
# Login helpers
# ---------------------------------------------------------------------------
@app.before_request
def require_secret_key():
    if request.path.startswith(("/api/auth/", "/api/orders")) and not app.secret_key:
        return jsonify({"error": "Accounts are not set up yet (the SECRET_KEY setting is missing)."}), 503


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "Please sign in first."}), 401
        return view(*args, **kwargs)
    return wrapper


def start_session(user):
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True


def public_user(user):
    return {"id": user["id"], "name": user["name"], "email": user["email"]}


# ---------------------------------------------------------------------------
# Pages and menu
# ---------------------------------------------------------------------------
@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "ADC Brew Cafe backend"})


@app.get("/api/menu")
def menu():
    category = request.args.get("category")
    allowed = {"coffee", "bakes", "cold"}
    if category and category not in allowed:
        return jsonify({"error": "Unknown menu category."}), 400
    items = [item for item in MENU_ITEMS if not category or item["category"] == category]
    return jsonify({"items": items, "count": len(items)})


# ---------------------------------------------------------------------------
# Accounts: register / login / logout / me
# ---------------------------------------------------------------------------
@app.post("/api/auth/register")
def register():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Please submit valid JSON."}), 400
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))

    if not name or len(name) > 100:
        return jsonify({"error": "Enter your name (up to 100 characters)."}), 400
    if not EMAIL_RE.fullmatch(email) or len(email) > 254:
        return jsonify({"error": "Enter a valid email address."}), 400
    if len(password) < 8 or len(password) > 128:
        return jsonify({"error": "Password must be 8 to 128 characters."}), 400

    password_hash = generate_password_hash(password, method="pbkdf2:sha256")
    try:
        with db() as d:
            if d.one("SELECT id FROM users WHERE email = ?", (email,)):
                return jsonify({"error": "An account with this email already exists. Try signing in."}), 409
            user_id = d.insert(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, password_hash),
            )
    except Exception:
        app.logger.exception("Could not register user")
        return db_error()

    user = {"id": user_id, "name": name, "email": email}
    start_session(user)
    return jsonify({"message": "Account created.", "user": public_user(user)}), 201


@app.post("/api/auth/login")
def login():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Please submit valid JSON."}), 400
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    try:
        with db() as d:
            user = d.one("SELECT id, name, email, password_hash FROM users WHERE email = ?", (email,))
    except Exception:
        app.logger.exception("Could not sign in")
        return db_error()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Incorrect email or password."}), 401
    start_session(user)
    return jsonify({"message": "Signed in.", "user": public_user(user)})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"message": "Signed out."})


@app.get("/api/auth/me")
def me():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"user": None})
    try:
        with db() as d:
            user = d.one("SELECT id, name, email FROM users WHERE id = ?", (user_id,))
    except Exception:
        app.logger.exception("Could not load user")
        return db_error()
    if not user:
        session.clear()
    return jsonify({"user": public_user(user) if user else None})


# ---------------------------------------------------------------------------
# Orders (pay at the counter; prices always come from the server's menu)
# ---------------------------------------------------------------------------
@app.post("/api/orders")
@login_required
def create_order():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Please submit valid JSON."}), 400
    raw_items = payload.get("items")
    note = str(payload.get("note", "")).strip()

    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > 30:
        return jsonify({"error": "Your cart is empty."}), 400
    if len(note) > 500:
        return jsonify({"error": "Note must be 500 characters or fewer."}), 400

    quantities = {}
    for entry in raw_items:
        if not isinstance(entry, dict):
            return jsonify({"error": "Invalid cart."}), 400
        try:
            item_id = int(entry.get("id"))
            quantity = int(entry.get("quantity"))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid cart."}), 400
        if item_id not in MENU_BY_ID:
            return jsonify({"error": "One of the items is no longer on the menu."}), 400
        quantities[item_id] = quantities.get(item_id, 0) + quantity
    if any(q < 1 or q > 20 for q in quantities.values()):
        return jsonify({"error": "Each item can be ordered 1 to 20 times."}), 400

    lines = [(MENU_BY_ID[i], q) for i, q in quantities.items()]
    total = sum(item["price"] * q for item, q in lines)

    try:
        with db() as d:
            order_id = d.insert(
                "INSERT INTO orders (user_id, total, note) VALUES (?, ?, ?)",
                (session["user_id"], total, note),
            )
            for item, q in lines:
                d.execute(
                    "INSERT INTO order_items (order_id, item_id, name, price, quantity) VALUES (?, ?, ?, ?, ?)",
                    (order_id, item["id"], item["name"], item["price"], q),
                )
    except Exception:
        app.logger.exception("Could not save order")
        return db_error()

    return jsonify({
        "message": "Order placed.",
        "id": order_id,
        "total": total,
        "status": "placed",
        "items": [{"name": item["name"], "price": item["price"], "quantity": q} for item, q in lines],
    }), 201


@app.get("/api/orders")
@login_required
def list_orders():
    try:
        with db() as d:
            orders = d.all(
                "SELECT id, total, note, status, created_at FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 20",
                (session["user_id"],),
            )
            if orders:
                marks = ", ".join("?" for _ in orders)
                items = d.all(
                    f"SELECT order_id, name, price, quantity FROM order_items WHERE order_id IN ({marks}) ORDER BY id",
                    [o["id"] for o in orders],
                )
            else:
                items = []
    except Exception:
        app.logger.exception("Could not load orders")
        return db_error()

    by_order = {}
    for item in items:
        by_order.setdefault(item["order_id"], []).append(
            {"name": item["name"], "price": item["price"], "quantity": item["quantity"]}
        )
    for order in orders:
        order["items"] = by_order.get(order["id"], [])
    return jsonify({"orders": orders})


# ---------------------------------------------------------------------------
# Reservations and contact form
# ---------------------------------------------------------------------------
@app.post("/api/reservations")
def create_reservation():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Please submit the form using valid JSON."}), 400

    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    phone = str(payload.get("phone", "")).strip()
    visit_date = str(payload.get("date", "")).strip()
    visit_time = str(payload.get("time", "")).strip()
    message = str(payload.get("message", "")).strip()

    try:
        guests = int(payload.get("guests", 0))
    except (TypeError, ValueError):
        guests = 0

    if not name or len(name) > 100:
        return jsonify({"error": "Enter your name (up to 100 characters)."}), 400
    if not EMAIL_RE.fullmatch(email) or len(email) > 254:
        return jsonify({"error": "Enter a valid email address."}), 400
    if len(phone) > 30:
        return jsonify({"error": "Phone number must be 30 characters or fewer."}), 400
    if guests < 1 or guests > 8:
        return jsonify({"error": "Guest count must be between 1 and 8."}), 400
    try:
        parsed_date = date.fromisoformat(visit_date)
    except ValueError:
        return jsonify({"error": "Choose a valid date."}), 400
    if parsed_date < date.today():
        return jsonify({"error": "Please choose today or a future date."}), 400
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", visit_time):
        return jsonify({"error": "Choose a valid time."}), 400
    if len(message) > 1000:
        return jsonify({"error": "Special request must be 1000 characters or fewer."}), 400

    try:
        with db() as d:
            reservation_id = d.insert(
                """INSERT INTO reservations
                   (name, email, phone, guests, visit_date, visit_time, message)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (name, email, phone, guests, visit_date, visit_time, message),
            )
    except Exception:
        app.logger.exception("Could not save reservation")
        return db_error()

    return jsonify({
        "message": "Reservation request received.",
        "id": reservation_id,
        "name": name,
        "status": "pending",
    }), 201


@app.post("/api/contact")
def create_contact_message():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Please submit valid JSON."}), 400
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    message = str(payload.get("message", "")).strip()
    if not name or len(name) > 100:
        return jsonify({"error": "Enter your name (up to 100 characters)."}), 400
    if not EMAIL_RE.fullmatch(email) or len(email) > 254:
        return jsonify({"error": "Enter a valid email address."}), 400
    if not message or len(message) > 2000:
        return jsonify({"error": "Message is required and must be under 2000 characters."}), 400
    try:
        with db() as d:
            message_id = d.insert(
                "INSERT INTO contact_messages (name, email, message) VALUES (?, ?, ?)",
                (name, email, message),
            )
    except Exception:
        app.logger.exception("Could not save contact message")
        return db_error()
    return jsonify({"message": "Message received.", "id": message_id}), 201


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "API endpoint not found."}), 404
    return "Page not found", 404


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "Request is too large."}), 413


if __name__ == "__main__":
    app.run(debug=True)

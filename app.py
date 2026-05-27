"""
app.py
Application factory — wires together all blueprints.
Business logic lives in blueprints/ and services/.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import logging
from datetime import datetime

from flask import Flask, session, send_from_directory, redirect
from flask_cors import CORS
from werkzeug.security import generate_password_hash

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── App factory ───────────────────────────────────────────────
app = Flask(__name__, static_folder="static", template_folder="templates")

_secret = os.environ.get("SECRET_KEY", "").strip()
if not _secret:
    raise RuntimeError(
        "SECRET_KEY is not set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\" "
        "and add it to your .env file."
    )
app.secret_key = _secret
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024   # 16 MB

CORS(app, supports_credentials=True,
     origins=["http://localhost:5000", "http://127.0.0.1:5000"])

from utils.csrf import init_csrf
init_csrf(app)

# ── Database initialisation ───────────────────────────────────
from extensions import init_db
init_db()

# ── Register blueprints ───────────────────────────────────────
from blueprints.auth       import auth_bp
from blueprints.complaints import complaints_bp
from blueprints.admin      import admin_bp
from blueprints.department import department_bp
from blueprints.ai_proxy   import ai_bp

app.register_blueprint(auth_bp)
app.register_blueprint(complaints_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(department_bp)
app.register_blueprint(ai_bp)

# ── Top-level page routes (index + dashboard redirect) ────────
@app.route("/")
def index():
    return send_from_directory("templates", "index.html")


@app.route("/dashboard")
def dashboard_page():
    if "user_id" not in session:
        return send_from_directory("templates", "login.html")
    role = session.get("role")
    if role == "admin":
        return send_from_directory("templates", "admin_dashboard.html")
    if role == "department":
        return redirect("/dept/dashboard")
    return send_from_directory("templates", "user_dashboard.html")


# ── Seed helpers ──────────────────────────────────────────────
def seed_admin():
    from extensions import users_col
    if not users_col.find_one({"role": "admin"}):
        users_col.insert_one({
            "name":       "Admin",
            "email":      "admin@civic.gov",
            "password":   generate_password_hash("Admin@123"),
            "role":       "admin",
            "created_at": datetime.utcnow(),
        })
        logger.info("Admin seeded → admin@civic.gov / Admin@123")


def seed_departments():
    """
    Seed department accounts into the users collection on first run.

    Passwords come from environment variables so they are never stored
    in source code.  Each variable follows the pattern:

        DEPT_PASSWORD_<SLUG>   e.g. DEPT_PASSWORD_PUBLIC_WORKS

    If a variable is absent the department is skipped and a warning is
    logged — the app still starts so existing departments are unaffected.
    """
    from extensions import users_col

    departments = [
        {"name": "Public Works",             "email": "publicworks@civic.gov", "slug": "PUBLIC_WORKS"},
        {"name": "Water & Sanitation",       "email": "water@civic.gov",       "slug": "WATER_SANITATION"},
        {"name": "Electricity",              "email": "electricity@civic.gov", "slug": "ELECTRICITY"},
        {"name": "Roads & Transport",        "email": "roads@civic.gov",       "slug": "ROADS_TRANSPORT"},
        {"name": "Parks & Recreation",       "email": "parks@civic.gov",       "slug": "PARKS_RECREATION"},
        {"name": "Health & Hygiene",         "email": "health@civic.gov",      "slug": "HEALTH_HYGIENE"},
        {"name": "Municipal Administration", "email": "municipal@civic.gov",   "slug": "MUNICIPAL_ADMIN"},
    ]

    for dept in departments:
        if users_col.find_one({"email": dept["email"]}):
            continue  # already seeded — skip

        env_var  = f"DEPT_PASSWORD_{dept['slug']}"
        password = os.environ.get(env_var, "").strip()

        if not password:
            logger.warning(
                "Department '%s' not seeded — %s is not set in .env",
                dept["name"], env_var,
            )
            continue

        users_col.insert_one({
            "name":       dept["name"],
            "email":      dept["email"],
            "password":   generate_password_hash(password),
            "role":       "department",
            "department": dept["name"],
            "created_at": datetime.utcnow(),
        })
        logger.info("Department seeded → %s", dept["email"])


# ── Startup seeding — runs after all functions are defined ──────
# Safe under both `python app.py` and Gunicorn/uWSGI.
# Seed functions are idempotent: they skip if records already exist.
with app.app_context():
    seed_admin()
    seed_departments()

# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(debug=debug_mode, port=5000)

"""
blueprints/auth.py
Handles all authentication flows:
  - Citizen registration with OTP email verification
  - Login (citizen / admin / department)
  - Logout & session info
  - Forgot / reset password
"""
import random
import secrets
import logging
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, session, send_from_directory, redirect
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import users_col, otp_col, reset_col
from services.email_service import (
    send_otp_email,
    send_password_reset_email,
)
from utils.helpers import login_required
from utils.rate_limit import rate_limit
from utils.helpers import sanitise_text, validate_length, MAX_NAME, MAX_EMAIL

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# ── Department helpers ────────────────────────────────────────

def _find_dept(email: str, password: str):
    """
    Look up a department account by email + password.
    Credentials live in the database (hashed), not in source code.
    Returns the department name on success, None on failure.
    """
    user = users_col.find_one({"email": email, "role": "department"})
    if user and check_password_hash(user["password"], password):
        return user["department"]
    return None


# Keep a lightweight name-only list for dropdowns / assignment UI.
# This never touches passwords.
def get_department_names() -> list[str]:
    return sorted(
        doc["department"]
        for doc in users_col.find({"role": "department"}, {"department": 1})
    )


def _set_dept_session(dept_name: str, email: str) -> None:
    session["user_id"]    = f"dept_{dept_name.lower().replace(' ','_').replace('&','and')}"
    session["name"]       = dept_name
    session["email"]      = email
    session["role"]       = "department"
    session["department"] = dept_name


# ── Page routes ───────────────────────────────────────────────

@auth_bp.route("/login")
def login_page():
    return send_from_directory("templates", "login.html")

@auth_bp.route("/register")
def register_page():
    return send_from_directory("templates", "register.html")

@auth_bp.route("/forgot-password")
def forgot_password_page():
    return send_from_directory("templates", "forgot_password.html")

@auth_bp.route("/reset-password")
def reset_password_page():
    return send_from_directory("templates", "reset_password.html")


# ── API: register ─────────────────────────────────────────────

@auth_bp.route("/api/register", methods=["POST"])
@rate_limit("register", limit=5, window_seconds=3600)   # 5 per IP per hour
def register():
    data     = request.get_json() or {}
    name     = data.get("name",     "").strip()
    email    = data.get("email",    "").strip().lower()
    password = data.get("password", "")
    phone    = data.get("phone",    "").strip()

    if not name or not email or not password:
        return jsonify({"error": "All fields required"}), 400

    # Length limits
    for value, limit, field in [(name, MAX_NAME, "Name"), (email, MAX_EMAIL, "Email")]:
        err = validate_length(value, limit, field)
        if err:
            return jsonify({"error": err}), 400
    if len(password) > 128:
        return jsonify({"error": "Password must be 128 characters or fewer"}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if users_col.find_one({"email": email}):
        return jsonify({"error": "Email already registered"}), 409

    otp = str(random.randint(100_000, 999_999))
    otp_col.delete_many({"email": email})
    otp_col.insert_one({
        "email":      email,
        "otp":        otp,
        "name":       sanitise_text(name),
        "phone":      phone,
        "password":   generate_password_hash(password),
        "expires_at": datetime.utcnow() + timedelta(minutes=10),
        "attempts":   0,
    })
    try:
        send_otp_email(email, otp, name)
    except Exception as exc:
        otp_col.delete_many({"email": email})
        logger.error("OTP email failed: %s", exc)
        return jsonify({"error": f"Failed to send OTP email: {exc}"}), 500

    return jsonify({"message": "OTP sent to your Gmail. Please verify to complete registration."}), 200


# ── API: verify OTP ───────────────────────────────────────────

@auth_bp.route("/api/verify-otp", methods=["POST"])
@rate_limit("verify_otp", limit=10, window_seconds=3600)   # 10 per IP per hour
def verify_otp():
    data  = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    otp   = data.get("otp",   "").strip()

    if not email or not otp:
        return jsonify({"error": "Email and OTP are required"}), 400

    record = otp_col.find_one({"email": email})
    if not record:
        return jsonify({"error": "No pending verification found. Please register again."}), 404
    if datetime.utcnow() > record["expires_at"]:
        otp_col.delete_many({"email": email})
        return jsonify({"error": "OTP has expired. Please register again."}), 410
    if record.get("attempts", 0) >= 5:
        otp_col.delete_many({"email": email})
        return jsonify({"error": "Too many wrong attempts. Please register again."}), 429
    if record["otp"] != otp:
        new_attempts = record.get("attempts", 0) + 1
        otp_col.update_one({"email": email}, {"$inc": {"attempts": 1}})
        remaining = 5 - new_attempts
        return jsonify({"error": f"Incorrect OTP. {remaining} attempt(s) remaining."}), 400

    users_col.insert_one({
        "name":       record["name"],
        "email":      email,
        "phone":      record.get("phone", ""),
        "password":   record["password"],
        "role":       "user",
        "created_at": datetime.utcnow(),
    })
    otp_col.delete_many({"email": email})
    return jsonify({"message": "Email verified! Registration complete. Please log in."}), 201


# ── API: login ────────────────────────────────────────────────

@auth_bp.route("/api/login", methods=["POST"])
@rate_limit("login", limit=10, window_seconds=900)   # 10 per IP per 15 min
def login():
    data     = request.get_json() or {}
    email    = data.get("email",    "").strip().lower()
    password = data.get("password", "")
    portal   = data.get("portal",   "citizen")   # "citizen" or "admin"

    # Department credential check
    dept = _find_dept(email, password)
    if dept:
        if portal == "citizen":
            return jsonify({"error": "Department staff must log in via the Admin portal."}), 403
        _set_dept_session(dept, email)
        return jsonify({"message": "Login successful", "name": dept, "role": "department"})

    # Regular user / admin
    user = users_col.find_one({"email": email})
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Invalid email or password"}), 401

    if portal == "admin" and user["role"] not in ("admin", "department"):
        return jsonify({"error": "Access denied. This portal is for administrators only."}), 403
    if portal == "citizen" and user["role"] == "admin":
        return jsonify({"error": "Admins must log in via the Admin portal."}), 403

    session["user_id"] = str(user["_id"])
    session["name"]    = user["name"]
    session["email"]   = user["email"]
    session["role"]    = user["role"]
    return jsonify({"message": "Login successful", "name": user["name"], "role": user["role"]})


@auth_bp.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})


@auth_bp.route("/api/me")
def me():
    if "user_id" not in session:
        return jsonify({"authenticated": False}), 401
    data = {
        "authenticated": True,
        "user_id": session["user_id"],
        "name":    session["name"],
        "role":    session["role"],
    }
    if session.get("prev_admin_id"):
        data["prev_admin_id"] = session["prev_admin_id"]
    return jsonify(data)


# ── API: forgot / reset password ─────────────────────────────

@auth_bp.route("/api/forgot-password", methods=["POST"])
@rate_limit("forgot_password", limit=3, window_seconds=900)   # 3 per IP per 15 min
def forgot_password():
    email = (request.get_json() or {}).get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email required"}), 400

    user = users_col.find_one({"email": email})
    if user:
        token = secrets.token_urlsafe(32)
        reset_col.delete_many({"email": email})
        reset_col.insert_one({
            "email":      email,
            "token":      token,
            "expires_at": datetime.utcnow() + timedelta(minutes=30),
        })
        base_url   = request.host_url.rstrip("/")
        reset_link = f"{base_url}/reset-password?token={token}"
        try:
            send_password_reset_email(email, user.get("name", "User"), reset_link)
        except Exception as exc:
            logger.error("Reset email failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    return jsonify({"message": "If that email is registered, a reset link has been sent."}), 200


@auth_bp.route("/api/reset-password", methods=["POST"])
@rate_limit("reset_password", limit=5, window_seconds=900)   # 5 per IP per 15 min
def reset_password():
    data   = request.get_json() or {}
    token  = data.get("token",    "").strip()
    new_pw = data.get("password", "")

    if not token or not new_pw:
        return jsonify({"error": "Token and new password required"}), 400
    if len(new_pw) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    record = reset_col.find_one({"token": token})
    if not record:
        return jsonify({"error": "Invalid or expired reset link. Please request a new one."}), 400
    if datetime.utcnow() > record["expires_at"]:
        reset_col.delete_one({"token": token})
        return jsonify({"error": "Reset link has expired. Please request a new one."}), 410

    users_col.update_one(
        {"email": record["email"]},
        {"$set": {"password": generate_password_hash(new_pw)}},
    )
    reset_col.delete_one({"token": token})
    return jsonify({"message": "Password reset successful. You can now log in."}), 200

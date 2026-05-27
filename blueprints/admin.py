"""
blueprints/admin.py
Admin-only routes:
  - Complaint listing & status updates
  - Analytics API
  - CSV / Excel export
  - Department credential listing
  - Activity log
"""
import logging
import os
import hashlib
from datetime import datetime

from flask import Blueprint, request, jsonify, send_from_directory, make_response, redirect, session
from werkzeug.security import generate_password_hash

from extensions import complaints_col, activity_col
from services.email_service import send_status_notification
from services.export_service import generate_csv, generate_excel
from utils.helpers import admin_required, serialize, fmt_dt, parse_object_id, paginate, VALID_STATUSES, VALID_PRIORITIES
from blueprints.auth import get_department_names

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)


# ── Page routes ───────────────────────────────────────────────

@admin_bp.route("/admin/complaints")
@admin_required
def admin_complaints_page():
    return send_from_directory("templates", "admin_complaints.html")

@admin_bp.route("/admin/analytics")
@admin_required
def admin_analytics_page():
    return send_from_directory("templates", "admin_analytics.html")

@admin_bp.route("/admin/departments")
@admin_required
def admin_departments_page():
    return send_from_directory("templates", "admin_departments.html")

@admin_bp.route("/admin/open-dept-portal", methods=["POST"])
@admin_required
def open_dept_portal():
    """
    Admin-only: set a department session so the admin can access
    the department portal directly without knowing the password.
    """
    from extensions import users_col
    data      = request.get_json() or {}
    dept_name = data.get("department", "").strip()
    if not dept_name:
        return jsonify({"error": "Department name required"}), 400

    dept_user = users_col.find_one({"role": "department", "department": dept_name})
    if not dept_user:
        return jsonify({"error": "Department not found"}), 404

    # Store previous admin session so we can restore it
    session["prev_admin_id"]    = session.get("user_id")
    session["prev_admin_name"]  = session.get("name")
    session["prev_admin_email"] = session.get("email")

    session["user_id"]    = f"dept_{dept_name.lower().replace(' ','_').replace('&','and')}"
    session["name"]       = dept_name
    session["email"]      = dept_user["email"]
    session["role"]       = "department"
    session["department"] = dept_name
    return jsonify({"message": "ok", "redirect": "/dept/dashboard"})


@admin_bp.route("/admin/restore-session", methods=["POST"])
def restore_admin_session():
    """Return from department portal view back to admin session."""
    prev_id = session.get("prev_admin_id")
    if not prev_id:
        return jsonify({"error": "No admin session to restore"}), 400
    session["user_id"] = prev_id
    session["name"]    = session.pop("prev_admin_name", "Admin")
    session["email"]   = session.pop("prev_admin_email", "")
    session["role"]    = "admin"
    session.pop("department", None)
    session.pop("prev_admin_id", None)
    return jsonify({"redirect": "/admin/departments"})


# ── API: complaints list ──────────────────────────────────────

@admin_bp.route("/api/admin/complaints")
@admin_required
def get_complaints():
    query = {}
    for field in ("status", "priority", "category", "department"):
        val = request.args.get(field)
        if val:
            query[field] = val

    skip, limit = paginate(request.args)
    total = complaints_col.count_documents(query)
    docs  = complaints_col.find(query, sort=[("created_at", -1)]).skip(skip).limit(limit)

    result = []
    for doc in docs:
        c = serialize(doc)
        c["created_at"] = fmt_dt(doc.get("created_at"))
        result.append(c)

    return jsonify({
        "data":     result,
        "total":    total,
        "page":     max(1, skip // limit + 1) if limit else 1,
        "per_page": limit,
        "pages":    max(1, -(-total // limit)) if limit else 1,   # ceil division
    })


# ── API: update a complaint ───────────────────────────────────

@admin_bp.route("/api/admin/complaints/<complaint_id>", methods=["PATCH"])
@admin_required
def update_complaint(complaint_id):
    # complaint_id is the human-readable CMP-YYYYMMDD-XXXXXX string, not a MongoDB ObjectId
    data    = request.get_json() or {}
    allowed = {"status", "priority", "department"}
    update  = {k: v for k, v in data.items() if k in allowed}
    if not update:
        return jsonify({"error": "No valid fields"}), 400

    # Validate enum values
    if "status" in update and update["status"] not in VALID_STATUSES:
        return jsonify({"error": "Invalid status value"}), 400
    if "priority" in update and update["priority"] not in VALID_PRIORITIES:
        return jsonify({"error": "Invalid priority value"}), 400

    update["updated_at"] = datetime.utcnow()
    existing = complaints_col.find_one({"complaint_id": complaint_id})
    if not existing:
        return jsonify({"error": "Complaint not found"}), 404

    complaints_col.update_one({"complaint_id": complaint_id}, {"$set": update})

    # ── Audit log — record every changed field ────────────────
    for field in ("status", "priority", "department"):
        if field in update and update[field] != existing.get(field):
            activity_col.insert_one({
                "complaint_id":  str(existing["_id"]),
                "complaint_ref": existing.get("complaint_id"),
                "department":    existing.get("department", "Unassigned"),
                "updated_by":    f"admin:{session.get('email', 'admin')}",
                "field":         field,
                "old_value":     existing.get(field),
                "new_value":     update[field],
                "old_status":    existing.get("status")  if field == "status" else None,
                "new_status":    update.get("status")    if field == "status" else None,
                "comment":       f"Admin changed {field}",
                "timestamp":     datetime.utcnow(),
            })

    # Email notification on status change
    if "status" in update and update["status"] != existing.get("status"):
        try:
            send_status_notification(
                existing, update["status"],
                existing.get("user_email", ""), existing.get("user_name", ""),
            )
        except Exception as exc:
            logger.warning("Status notification failed: %s", exc)

    return jsonify({"message": "Updated successfully"})


# ── API: analytics ────────────────────────────────────────────

@admin_bp.route("/api/admin/analytics")
@admin_required
def analytics():
    total       = complaints_col.count_documents({})
    pending     = complaints_col.count_documents({"status": "Pending"})
    in_progress = complaints_col.count_documents({"status": "In Progress"})
    resolved    = complaints_col.count_documents({"status": "Resolved"})

    def agg(field):
        return {
            d["_id"]: d["count"]
            for d in complaints_col.aggregate([
                {"$group": {"_id": f"${field}", "count": {"$sum": 1}}}
            ])
        }

    # Sort descending to get the 6 most recent months, then reverse for chronological display
    monthly_raw = list(complaints_col.aggregate([
        {"$group": {
            "_id":   {"year": {"$year": "$created_at"}, "month": {"$month": "$created_at"}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id.year": -1, "_id.month": -1}},
        {"$limit": 6},
    ]))
    monthly = list(reversed(monthly_raw))

    return jsonify({
        "total": total, "pending": pending,
        "in_progress": in_progress, "resolved": resolved,
        "categories":  agg("category"),
        "priorities":  agg("priority"),
        "departments": agg("department"),
        "monthly": [
            {"label": f"{m['_id']['year']}-{str(m['_id']['month']).zfill(2)}", "count": m["count"]}
            for m in monthly
        ],
    })


# ── API: exports ──────────────────────────────────────────────

@admin_bp.route("/api/admin/export/csv")
@admin_required
def export_csv():
    docs = list(complaints_col.find({}, sort=[("created_at", -1)]))
    csv_str = generate_csv(docs)
    resp = make_response(csv_str)
    resp.headers["Content-Type"]        = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="complaints-{datetime.utcnow().strftime("%Y%m%d")}.csv"'
    )
    return resp


@admin_bp.route("/api/admin/export/excel")
@admin_required
def export_excel():
    docs      = list(complaints_col.find({}, sort=[("created_at", -1)]))
    xlsx_bytes = generate_excel(docs)
    resp = make_response(xlsx_bytes)
    resp.headers["Content-Type"]        = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="complaints-{datetime.utcnow().strftime("%Y%m%d")}.xlsx"'
    )
    return resp


# ── API: department list ──────────────────────────────────────

@admin_bp.route("/api/admin/departments")
@admin_required
def list_departments():
    """
    Returns department name + email only.
    Passwords are NEVER included in API responses.
    """
    from extensions import users_col
    docs = users_col.find(
        {"role": "department"},
        {"name": 1, "email": 1, "department": 1, "_id": 0},  # password field excluded
    )
    return jsonify([
        {"name": doc["department"], "email": doc["email"]}
        for doc in docs
    ])


@admin_bp.route("/api/admin/departments/create", methods=["POST"])
@admin_required
def create_department():
    """
    Admin creates a department account. Stores hashed password in DB.
    Returns success — password is shown only at creation time on the frontend.
    """
    from extensions import users_col
    data     = request.get_json() or {}
    name     = data.get("name",     "").strip()
    email    = data.get("email",    "").strip().lower()
    password = data.get("password", "").strip()

    if not name or not email or not password:
        return jsonify({"error": "Name, email and password are all required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if users_col.find_one({"email": email}):
        return jsonify({"error": "That email is already registered"}), 409
    if users_col.find_one({"role": "department", "department": name}):
        return jsonify({"error": f"Department '{name}' already exists"}), 409

    users_col.insert_one({
        "name":       name,
        "email":      email,
        "department": name,
        "password":   generate_password_hash(password),
        "role":       "department",
        "created_at": datetime.utcnow(),
    })
    logger.info("Admin created department account: %s <%s>", name, email)
    return jsonify({"message": f"Department '{name}' created successfully"}), 201


# ── API: activity log ─────────────────────────────────────────

@admin_bp.route("/api/activity")
@admin_required
def activity_log():
    complaint_id = request.args.get("complaint_id")
    query = {}
    if complaint_id:
        query["complaint_id"] = complaint_id

    logs   = list(activity_col.find(query, sort=[("timestamp", -1)], limit=100))
    result = []
    for log in logs:
        l = serialize(log)
        l["timestamp"] = fmt_dt(log.get("timestamp"))
        result.append(l)
    return jsonify(result)


# ── API: public stats (landing page) ─────────────────────────

@admin_bp.route("/api/public/stats")
def public_stats():
    total    = complaints_col.count_documents({})
    resolved = complaints_col.count_documents({"status": "Resolved"})
    in_prog  = complaints_col.count_documents({"status": "In Progress"})
    return jsonify({"total": total, "resolved": resolved, "in_progress": in_prog})


# ── API: department invite code ───────────────────────────────

@admin_bp.route("/api/admin/invite-code")
@admin_required
def get_invite_code():
    """
    Returns a deterministic invite code derived from the app SECRET_KEY.
    The code is stable (same every call) so admins can share it with
    department staff to use during registration.
    """
    secret = os.environ.get("SECRET_KEY", "civiconnect-default")
    # Take first 8 chars of SHA256 hex, uppercased — e.g. "A3F7B21C"
    raw    = hashlib.sha256(f"dept-invite:{secret}".encode()).hexdigest()
    code   = raw[:8].upper()
    return jsonify({"code": code})


# ── Debug: test email sending ─────────────────────────────────
@admin_bp.route("/api/admin/test-email", methods=["POST"])
@admin_required
def test_email():
    """Send a test email to verify Brevo config is working."""
    import os, json, urllib.request as _req, urllib.error as _err
    from flask import session

    api_key    = os.environ.get("BREVO_API_KEY", "").strip()
    from_email = os.environ.get("BREVO_FROM_EMAIL", "").strip()
    from_name  = os.environ.get("BREVO_FROM_NAME", "CivicConnect").strip()
    to_email   = session.get("email", "")

    # Config checks
    if not api_key:
        return jsonify({"error": "BREVO_API_KEY not set in .env"}), 500
    if not from_email or "@" not in from_email:
        return jsonify({"error": f"BREVO_FROM_EMAIL is invalid: '{from_email}'"}), 500
    if not to_email:
        return jsonify({"error": "No session email found"}), 500

    payload = json.dumps({
        "sender":      {"name": from_name, "email": from_email},
        "to":          [{"email": to_email}],
        "subject":     "CivicConnect — Email Test",
        "htmlContent": f"<p>✅ Email is working! Sent from <b>{from_email}</b> to <b>{to_email}</b></p>",
    }).encode("utf-8")

    req = _req.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={"Content-Type": "application/json", "api-key": api_key},
        method="POST",
    )
    try:
        with _req.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return jsonify({
            "success": True,
            "message": f"Test email sent to {to_email}",
            "brevo_response": result,
            "from": from_email,
            "to": to_email,
        })
    except _err.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            msg = json.loads(body)
        except Exception:
            msg = body
        return jsonify({"error": f"Brevo error {exc.code}", "details": msg}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

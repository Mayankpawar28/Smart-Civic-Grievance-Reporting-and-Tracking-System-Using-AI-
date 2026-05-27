"""
blueprints/department.py
Department-staff portal:
  - Dashboard / complaints / analytics pages
  - Complaint status updates with activity logging
  - Department-scoped analytics API
"""
import logging
from datetime import datetime

from flask import Blueprint, request, jsonify, session, send_from_directory, redirect

from extensions import complaints_col, activity_col
from services.email_service import send_status_notification
from utils.helpers import dept_required, serialize, fmt_dt, paginate, sanitise_text, validate_length, MAX_COMMENT, VALID_STATUSES

logger = logging.getLogger(__name__)

department_bp = Blueprint("department", __name__)


# ── Page routes ───────────────────────────────────────────────

@department_bp.route("/dept/login")
def dept_login_page():
    return redirect("/login")

@department_bp.route("/dept/dashboard")
@dept_required
def dept_dashboard_page():
    return send_from_directory("templates", "dept_dashboard.html")

@department_bp.route("/dept/complaints")
@dept_required
def dept_complaints_page():
    return send_from_directory("templates", "dept_complaints.html")

@department_bp.route("/dept/analytics")
@dept_required
def dept_analytics_page():
    return send_from_directory("templates", "dept_analytics.html")


# ── API: current department identity ─────────────────────────

@department_bp.route("/api/dept/me")
def dept_me():
    if "user_id" not in session or session.get("role") != "department":
        return jsonify({"authenticated": False}), 401
    return jsonify({
        "authenticated": True,
        "name":          session["department"],
        "email":         session["email"],
        "department":    session["department"],
        "role":          "department",
    })


# ── API: complaints (dept-scoped) ─────────────────────────────

@department_bp.route("/api/dept/complaints")
@dept_required
def get_complaints():
    dept  = session["department"]
    query = {"department": dept}
    for field in ("status", "priority", "category"):
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
        "pages":    max(1, -(-total // limit)) if limit else 1,
    })


# ── API: update complaint status ──────────────────────────────

@department_bp.route("/api/dept/complaints/<complaint_id>/update", methods=["POST"])
@dept_required
def update_complaint(complaint_id):
    # complaint_id is the human-readable CMP-YYYYMMDD-XXXXXX string, not a MongoDB ObjectId
    data         = request.get_json() or {}
    status       = data.get("status",      "").strip()
    comment      = data.get("comment",     "").strip()
    work_images  = data.get("work_images", [])  # list of uploaded image URLs

    if not status:
        return jsonify({"error": "Status is required"}), 400
    if status not in VALID_STATUSES:
        return jsonify({"error": "Invalid status value"}), 400

    err = validate_length(comment, MAX_COMMENT, "Comment")
    if err:
        return jsonify({"error": err}), 400

    # Validate work image URLs
    if not isinstance(work_images, list):
        work_images = []
    work_images = [u for u in work_images if isinstance(u, str) and u.startswith("/static/uploads/")][:5]

    complaint = complaints_col.find_one({"complaint_id": complaint_id})
    if not complaint:
        return jsonify({"error": "Complaint not found"}), 404
    if complaint.get("department") != session["department"]:
        return jsonify({"error": "Unauthorized"}), 403

    old_status = complaint.get("status")
    complaints_col.update_one(
        {"complaint_id": complaint_id},
        {"$set": {"status": status, "updated_at": datetime.utcnow()}},
    )
    activity_col.insert_one({
        "complaint_id":  str(complaint["_id"]),
        "complaint_ref": complaint.get("complaint_id"),
        "department":    session["department"],
        "updated_by":    session["department"],
        "old_status":    old_status,
        "new_status":    status,
        "comment":       sanitise_text(comment),
        "work_images":   work_images,
        "timestamp":     datetime.utcnow(),
    })
    try:
        send_status_notification(
            complaint, status,
            complaint.get("user_email", ""), complaint.get("user_name", ""),
        )
    except Exception as exc:
        logger.warning("Status notification failed: %s", exc)

    return jsonify({"message": "Updated successfully"})


# ── API: dept stats ───────────────────────────────────────────

@department_bp.route("/api/dept/stats")
@dept_required
def dept_stats():
    dept     = session["department"]
    total    = complaints_col.count_documents({"department": dept})
    pending  = complaints_col.count_documents({"department": dept, "status": "Pending"})
    progress = complaints_col.count_documents({"department": dept, "status": "In Progress"})
    resolved = complaints_col.count_documents({"department": dept, "status": "Resolved"})
    return jsonify({"total": total, "pending": pending, "in_progress": progress, "resolved": resolved})


# ── API: dept analytics ───────────────────────────────────────

@department_bp.route("/api/dept/analytics")
@dept_required
def dept_analytics():
    dept = session["department"]
    base = {"department": dept}

    total    = complaints_col.count_documents(base)
    pending  = complaints_col.count_documents({**base, "status": "Pending"})
    progress = complaints_col.count_documents({**base, "status": "In Progress"})
    resolved = complaints_col.count_documents({**base, "status": "Resolved"})

    def agg(field):
        return {
            d["_id"]: d["count"]
            for d in complaints_col.aggregate([
                {"$match": base},
                {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
            ])
        }

    monthly = list(complaints_col.aggregate([
        {"$match": base},
        {"$group": {
            "_id":   {"year": {"$year": "$created_at"}, "month": {"$month": "$created_at"}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id.year": 1, "_id.month": 1}},
        {"$limit": 6},
    ]))

    return jsonify({
        "total": total, "pending": pending,
        "in_progress": progress, "resolved": resolved,
        "categories": agg("category"),
        "priorities":  agg("priority"),
        "monthly": [
            {"label": f"{m['_id']['year']}-{str(m['_id']['month']).zfill(2)}", "count": m["count"]}
            for m in monthly
        ],
    })


# ── API: activity log (dept-scoped) ──────────────────────────

@department_bp.route("/api/dept/activity")
@dept_required
def dept_activity():
    complaint_id = request.args.get("complaint_id")
    query = {"department": session["department"]}
    if complaint_id:
        query["complaint_id"] = complaint_id

    logs   = list(activity_col.find(query, sort=[("timestamp", -1)], limit=100))
    result = []
    for log in logs:
        l = serialize(log)
        l["timestamp"] = fmt_dt(log.get("timestamp"))
        result.append(l)
    return jsonify(result)

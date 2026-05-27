"""
blueprints/complaints.py
Citizen-facing complaint submission, listing, PDF download,
image upload, and profile/avatar management.
"""
import os
import uuid
import logging
from datetime import datetime

from flask import (
    Blueprint, request, jsonify, session,
    send_from_directory, make_response,
)

from extensions import users_col, complaints_col
from services.pdf_service import generate_complaint_pdf

# ── Category → Department auto-routing ───────────────────────
CATEGORY_DEPT_MAP = {
    "Potholes & Roads":       "Roads & Transport",
    "Garbage & Sanitation":   "Water & Sanitation",
    "Water Supply":           "Water & Sanitation",
    "Streetlights":           "Electricity",
    "Drainage & Flooding":    "Water & Sanitation",
    "Parks & Public Spaces":  "Parks & Recreation",
    "Noise Pollution":        "Municipal Administration",
    "Other":                  "Municipal Administration",
}

def auto_assign_department(category: str) -> str:
    """Return the department name for a given category, or 'Unassigned'."""
    return CATEGORY_DEPT_MAP.get(category, "Unassigned")

from utils.helpers import (
    login_required, allowed_file, make_complaint_id,
    serialize, fmt_dt, parse_object_id, paginate,
    sanitise_text, validate_length,
    MAX_TITLE, MAX_DESCRIPTION, MAX_LOCATION, MAX_IMAGES,
    VALID_CATEGORIES,
)

logger = logging.getLogger(__name__)

complaints_bp = Blueprint("complaints", __name__)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
AVATAR_FOLDER = os.path.join(UPLOAD_FOLDER, "avatars")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AVATAR_FOLDER, exist_ok=True)


# ── Page routes ───────────────────────────────────────────────

@complaints_bp.route("/submit-complaint")
@login_required
def submit_complaint_page():
    return send_from_directory("templates", "submit_complaint.html")

@complaints_bp.route("/my-complaints")
@login_required
def my_complaints_page():
    return send_from_directory("templates", "my_complaints.html")


# ── Static file serving ───────────────────────────────────────

@complaints_bp.route("/static/uploads/avatars/<filename>")
def serve_avatar(filename):
    return send_from_directory(AVATAR_FOLDER, filename)

@complaints_bp.route("/static/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ── API: image upload ─────────────────────────────────────────

@complaints_bp.route("/api/upload-image", methods=["POST"])
@login_required
def upload_image():
    if "image" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["image"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed. Use PNG, JPG, GIF or WEBP"}), 400

    # Per-file size limit: 5 MB
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    if file_size > 5 * 1024 * 1024:
        return jsonify({"error": "Image too large. Maximum size is 5 MB"}), 400

    ext      = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    return jsonify({"url": f"/static/uploads/{filename}", "filename": filename})


# ── API: submit complaint ─────────────────────────────────────

@complaints_bp.route("/api/complaints", methods=["POST"])
@login_required
def submit_complaint():
    data = request.get_json() or {}
    title       = data.get("title",       "").strip()
    description = data.get("description", "").strip()
    category    = data.get("category",    "").strip()
    location    = data.get("location",    "").strip()

    # Presence check
    if not all([title, description, category, location]):
        return jsonify({"error": "All fields required"}), 400

    # Length limits
    for value, limit, name in [
        (title,       MAX_TITLE,       "Title"),
        (description, MAX_DESCRIPTION, "Description"),
        (location,    MAX_LOCATION,    "Location"),
    ]:
        err = validate_length(value, limit, name)
        if err:
            return jsonify({"error": err}), 400

    # Category must be one of the known values
    if category not in VALID_CATEGORIES:
        return jsonify({"error": "Invalid category"}), 400

    # Image count cap + validate all URLs are from our own upload folder
    images = data.get("images", [])
    if not isinstance(images, list):
        return jsonify({"error": "Images must be a list"}), 400
    if len(images) > MAX_IMAGES:
        return jsonify({"error": f"Maximum {MAX_IMAGES} images per complaint"}), 400
    for img_url in images:
        if not isinstance(img_url, str) or not img_url.startswith("/static/uploads/"):
            return jsonify({"error": "Invalid image URL"}), 400

    complaint = {
        "complaint_id": make_complaint_id(),
        "user_id":      session["user_id"],
        "user_name":    session["name"],
        "user_email":   session["email"],
        "title":        sanitise_text(title),
        "description":  sanitise_text(description),
        "category":     category,           # already validated against whitelist
        "location":     sanitise_text(location),
        "lat":          data.get("lat"),
        "lng":          data.get("lng"),
        "images":       images,
        "priority":     "Medium",
        "status":       "Pending",
        "department":   auto_assign_department(category),
        "created_at":   datetime.utcnow(),
        "updated_at":   datetime.utcnow(),
    }
    complaints_col.insert_one(complaint)
    return jsonify({"message": "Complaint submitted successfully",
                    "complaint_id": complaint["complaint_id"]}), 201


# ── API: my complaints ────────────────────────────────────────

@complaints_bp.route("/api/complaints/my")
@login_required
def my_complaints():
    query = {"user_id": session["user_id"]}
    for field in ("status", "priority", "category"):
        val = request.args.get(field)
        if val:
            query[field] = val
    skip, limit  = paginate(request.args)
    total        = complaints_col.count_documents(query)
    docs         = complaints_col.find(query, sort=[("created_at", -1)]).skip(skip).limit(limit)

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


# ── API: PDF download ─────────────────────────────────────────

@complaints_bp.route("/api/complaints/<complaint_id>/pdf")
@login_required
def download_complaint_pdf(complaint_id):
    complaint = complaints_col.find_one({"complaint_id": complaint_id})
    if not complaint:
        return jsonify({"error": "Complaint not found"}), 404
    if session.get("role") != "admin" and str(complaint.get("user_id")) != session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 403

    try:
        pdf_bytes = generate_complaint_pdf(complaint)
    except Exception as exc:
        logger.error("PDF generation failed: %s", exc, exc_info=True)
        return jsonify({"error": "Could not generate PDF. Please try again."}), 500

    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"]        = "application/pdf"
    resp.headers["Content-Disposition"] = f'attachment; filename="complaint-{complaint_id}.pdf"'
    return resp


# ── API: profile ──────────────────────────────────────────────

@complaints_bp.route("/api/profile")
@login_required
def get_profile():
    # Department users have a non-ObjectId session user_id (e.g. "dept_public_works")
    # so look them up by email instead
    if session.get("role") in ("department", "admin"):
        user = users_col.find_one({"email": session.get("email")})
    else:
        oid = parse_object_id(session["user_id"])
        if oid is None:
            return jsonify({"error": "User not found"}), 404
        user = users_col.find_one({"_id": oid})
    if not user:
        return jsonify({"error": "User not found"}), 404

    uid         = session["user_id"]
    total       = complaints_col.count_documents({"user_id": uid})
    resolved    = complaints_col.count_documents({"user_id": uid, "status": "Resolved"})
    in_progress = complaints_col.count_documents({"user_id": uid, "status": "In Progress"})
    pending     = complaints_col.count_documents({"user_id": uid, "status": "Pending"})
    joined      = user.get("created_at")

    return jsonify({
        "name":       user["name"],
        "email":      user["email"],
        "phone":      user.get("phone", ""),
        "role":       user["role"],
        "joined":     joined.strftime("%d %b %Y") if isinstance(joined, datetime) else "—",
        "avatar_url": user.get("avatar_url", ""),
        "stats": {
            "total": total, "resolved": resolved,
            "in_progress": in_progress, "pending": pending,
        },
    })


# ── API: avatar upload / delete ───────────────────────────────

@complaints_bp.route("/api/profile/avatar", methods=["POST"])
@login_required
def upload_avatar():
    if "avatar" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["avatar"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed. Use PNG, JPG or WEBP"}), 400
    # Check real file size (not the spoofable Content-Length header)
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    if file_size > 5 * 1024 * 1024:
        return jsonify({"error": "File too large. Max 5MB"}), 400

    ext      = file.filename.rsplit(".", 1)[1].lower()
    uid      = session["user_id"]
    filename = f"avatar_{uid}.{ext}"

    for old in os.listdir(AVATAR_FOLDER):
        if old.startswith(f"avatar_{uid}."):
            os.remove(os.path.join(AVATAR_FOLDER, old))

    file.save(os.path.join(AVATAR_FOLDER, filename))
    avatar_url = f"/static/uploads/avatars/{filename}"
    oid = parse_object_id(uid)
    if oid:
        users_col.update_one({"_id": oid}, {"$set": {"avatar_url": avatar_url}})
    return jsonify({"avatar_url": avatar_url})


@complaints_bp.route("/api/profile/avatar", methods=["DELETE"])
@login_required
def delete_avatar():
    uid = session["user_id"]
    oid = parse_object_id(uid)
    if oid:
        user = users_col.find_one({"_id": oid})
        if user and user.get("avatar_url"):
            filepath = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                user["avatar_url"].lstrip("/"),
            )
            if os.path.exists(filepath):
                os.remove(filepath)
        users_col.update_one({"_id": oid}, {"$unset": {"avatar_url": ""}})
    return jsonify({"message": "Avatar removed"})


# ── API: citizen edit complaint (only while Unassigned) ───────

@complaints_bp.route("/api/complaints/<complaint_id>/edit", methods=["PATCH"])
@login_required
def edit_complaint(complaint_id):
    complaint = complaints_col.find_one({
        "complaint_id": complaint_id,
        "user_id": session["user_id"]
    })
    if not complaint:
        return jsonify({"error": "Complaint not found"}), 404
    if complaint.get("department", "Unassigned") != "Unassigned":
        return jsonify({"error": "Cannot edit — complaint has already been assigned to a department"}), 403

    data        = request.get_json() or {}
    title       = data.get("title",       "").strip()
    description = data.get("description", "").strip()
    category    = data.get("category",    "").strip()
    location    = data.get("location",    "").strip()

    if not all([title, description, category, location]):
        return jsonify({"error": "All fields are required"}), 400

    for value, limit, name in [
        (title,       MAX_TITLE,       "Title"),
        (description, MAX_DESCRIPTION, "Description"),
        (location,    MAX_LOCATION,    "Location"),
    ]:
        err = validate_length(value, limit, name)
        if err:
            return jsonify({"error": err}), 400

    if category not in VALID_CATEGORIES:
        return jsonify({"error": "Invalid category"}), 400

    complaints_col.update_one(
        {"complaint_id": complaint_id, "user_id": session["user_id"]},
        {"$set": {
            "title":       sanitise_text(title),
            "description": sanitise_text(description),
            "category":    category,
            "location":    sanitise_text(location),
            "lat":         data.get("lat"),
            "lng":         data.get("lng"),
            "updated_at":  datetime.utcnow(),
        }}
    )
    return jsonify({"message": "Complaint updated successfully"})


# ── API: citizen delete complaint (only while Unassigned) ─────

@complaints_bp.route("/api/complaints/<complaint_id>/delete", methods=["DELETE"])
@login_required
def delete_complaint(complaint_id):
    complaint = complaints_col.find_one({
        "complaint_id": complaint_id,
        "user_id": session["user_id"]
    })
    if not complaint:
        return jsonify({"error": "Complaint not found"}), 404
    if complaint.get("department", "Unassigned") != "Unassigned":
        return jsonify({"error": "Cannot delete — complaint has already been assigned to a department"}), 403

    # Clean up uploaded image files from disk before deleting the record
    for img_url in complaint.get("images", []):
        if isinstance(img_url, str) and img_url.startswith("/static/uploads/"):
            filepath = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                img_url.lstrip("/"),
            )
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except OSError as exc:
                logger.warning("Could not delete image file %s: %s", filepath, exc)

    complaints_col.delete_one({"complaint_id": complaint_id, "user_id": session["user_id"]})
    return jsonify({"message": "Complaint deleted successfully"})


# ── API: activity log for citizen (own complaints only) ───────

@complaints_bp.route("/api/complaints/<complaint_id>/activity")
@login_required
def complaint_activity(complaint_id):
    from extensions import activity_col
    complaint = complaints_col.find_one({"complaint_id": complaint_id})
    if not complaint:
        return jsonify([])
    # Citizens can only see activity on their own complaints
    if session.get("role") == "citizen" and str(complaint.get("user_id")) != session.get("user_id"):
        return jsonify([])
    from utils.helpers import fmt_dt, serialize
    logs = list(activity_col.find(
        {"complaint_id": str(complaint["_id"])},
        sort=[("timestamp", 1)]   # oldest first for timeline
    ))
    result = []
    for log in logs:
        l = serialize(log)
        l["timestamp"] = fmt_dt(log.get("timestamp"))
        result.append(l)
    return jsonify(result)

"""
utils/helpers.py
Shared utility functions used across blueprints.
"""
import html
import uuid
import logging
from datetime import datetime
from functools import wraps
from flask import session, jsonify
from bson import ObjectId
from bson.errors import InvalidId

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

# ── Field length limits ───────────────────────────────────────
MAX_TITLE       = 120
MAX_DESCRIPTION = 2000
MAX_LOCATION    = 200
MAX_COMMENT     = 1000
MAX_NAME        = 100
MAX_EMAIL       = 254    # RFC 5321 hard limit
MAX_IMAGES      = 5      # max images per complaint submission

# ── Valid enum values ─────────────────────────────────────────
VALID_CATEGORIES = {
    "Potholes & Roads",
    "Garbage & Sanitation",
    "Water Supply",
    "Streetlights",
    "Drainage & Flooding",
    "Parks & Public Spaces",
    "Noise Pollution",
    "Other",
}
VALID_STATUSES   = {"Pending", "In Progress", "Resolved"}
VALID_PRIORITIES = {"Low", "Medium", "High"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def sanitise_text(value: str) -> str:
    """
    Escape HTML special characters to neutralise stored XSS.
    All user-supplied text fields are passed through this before storage.
    The frontend renders these as text content, not innerHTML, so
    the escaped characters display correctly to the end user.
    """
    return html.escape(value, quote=True)


def validate_length(value: str, max_len: int, field_name: str) -> str | None:
    """
    Return an error message string if value exceeds max_len, else None.
    Usage:
        err = validate_length(title, MAX_TITLE, "Title")
        if err: return jsonify({"error": err}), 400
    """
    if len(value) > max_len:
        return f"{field_name} must be {max_len} characters or fewer (got {len(value)})"
    return None


def make_complaint_id() -> str:
    return f"CMP-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def serialize(doc: dict) -> dict:
    """Convert a MongoDB document to a JSON-serialisable dict."""
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    return doc


def fmt_dt(dt) -> str:
    """Format a datetime for API responses."""
    if isinstance(dt, datetime):
        return dt.strftime("%d %b %Y, %H:%M")
    return "—"


def parse_object_id(value: str) -> ObjectId | None:
    """
    Safely parse a string into a MongoDB ObjectId.

    Returns None if the value is not a valid 24-character hex ObjectId,
    so callers can return a clean 404 instead of crashing with a 500.

    Usage:
        oid = parse_object_id(complaint_id)
        if oid is None:
            return jsonify({"error": "Invalid ID"}), 404
    """
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def paginate(request_args, default_per_page: int = 25, max_per_page: int = 100) -> tuple[int, int]:
    """
    Parse and clamp pagination query params from a Flask request.

    Returns (skip, limit) ready to pass directly to MongoDB:
        docs = col.find(query).skip(skip).limit(limit)

    Query params:
        page     — 1-based page number (default 1)
        per_page — items per page (default 25, max 100)
    """
    try:
        page = max(1, int(request_args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = min(max_per_page, max(1, int(request_args.get("per_page", default_per_page))))
    except (ValueError, TypeError):
        per_page = default_per_page

    skip = (page - 1) * per_page
    return skip, per_page


# ── Auth decorators ───────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        if session.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


def dept_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        role = session.get("role")
        # Allow admin to impersonate a department (has prev_admin_id set)
        if role == "department":
            return f(*args, **kwargs)
        if role == "admin" and session.get("prev_admin_id"):
            return f(*args, **kwargs)
        return jsonify({"error": "Department access required"}), 403
    return decorated

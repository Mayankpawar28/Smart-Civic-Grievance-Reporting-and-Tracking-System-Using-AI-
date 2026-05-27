"""
utils/rate_limit.py
IP-based rate limiting backed by MongoDB.

Uses a TTL collection so windows expire automatically — no cron job needed.
Each rate-limit record is keyed by (action, ip) and holds a hit counter.
When the counter exceeds the limit the request is rejected with 429.

Usage:
    from utils.rate_limit import rate_limit

    @auth_bp.route("/api/login", methods=["POST"])
    @rate_limit("login", limit=10, window_seconds=900)   # 10 per 15 min per IP
    def login():
        ...
"""
import logging
from datetime import datetime, timedelta
from functools import wraps

from flask import request, jsonify
from pymongo import ASCENDING

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependency with extensions.py
_rate_col = None


def _get_col():
    global _rate_col
    if _rate_col is None:
        from extensions import db
        _rate_col = db["rate_limits"]
        # TTL index: MongoDB deletes the document automatically at expires_at
        _rate_col.create_index("expires_at", expireAfterSeconds=0)
        # Compound index for fast lookups
        _rate_col.create_index([("action", ASCENDING), ("ip", ASCENDING)])
    return _rate_col


def _get_ip() -> str:
    """
    Return the real client IP.
    X-Forwarded-For is only trusted when TRUST_PROXY=true is set in the
    environment, preventing clients from spoofing their IP to bypass rate limits.
    """
    import os
    if os.environ.get("TRUST_PROXY", "").lower() == "true":
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def check_rate_limit(action: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    """
    Increment the hit counter for (action, ip) and check against limit.

    Returns:
        (allowed: bool, remaining: int)
    """
    col = _get_col()
    ip  = _get_ip()
    now = datetime.utcnow()
    key = {"action": action, "ip": ip}

    doc = col.find_one(key)

    if not doc:
        # First hit — create a fresh window
        col.insert_one({
            **key,
            "hits":       1,
            "window_start": now,
            "expires_at": now + timedelta(seconds=window_seconds),
        })
        return True, limit - 1

    hits = doc.get("hits", 0) + 1

    if hits > limit:
        remaining_secs = max(0, int((doc["expires_at"] - now).total_seconds()))
        logger.warning(
            "Rate limit exceeded: action=%s ip=%s hits=%d limit=%d",
            action, ip, hits, limit,
        )
        return False, remaining_secs

    col.update_one(key, {"$inc": {"hits": 1}})
    return True, limit - hits


def rate_limit(action: str, limit: int, window_seconds: int):
    """
    Decorator that enforces a rate limit on the decorated endpoint.

    Args:
        action:         Short string key identifying the endpoint (e.g. "login")
        limit:          Maximum number of requests allowed in the window
        window_seconds: Length of the window in seconds
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            allowed, info = check_rate_limit(action, limit, window_seconds)
            if not allowed:
                minutes = max(1, info // 60)
                return jsonify({
                    "error": f"Too many attempts. Please try again in {minutes} minute(s)."
                }), 429
            return f(*args, **kwargs)
        return wrapper
    return decorator

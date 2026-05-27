"""
utils/csrf.py
CSRF protection using the Double Submit Cookie pattern.

How it works:
  1. On every response, Flask sets a random `csrf_token` cookie (non-HttpOnly
     so JavaScript can read it).
  2. On every state-changing request (POST / PATCH / DELETE), the server
     checks that the `X-CSRF-Token` header matches the cookie value.
  3. A cross-origin attacker can trigger a request with the cookie attached
     (that's what CSRF is) but cannot READ the cookie to copy it into the
     header — so the check fails for them and passes for our own JS.

Exempt endpoints are pre-login flows where no session exists yet, so there
is nothing worth forging anyway.
"""
import os
import secrets
import logging
from functools import wraps
from flask import request, jsonify, make_response, g

logger = logging.getLogger(__name__)

CSRF_COOKIE   = "csrf_token"
CSRF_HEADER   = "X-CSRF-Token"
CSRF_METHODS  = {"POST", "PATCH", "PUT", "DELETE"}

# These endpoints are called before the user has a session, so CSRF
# protection has no value and would break the registration / login flow.
CSRF_EXEMPT = {
    "/api/login",
    "/api/register",
    "/api/verify-otp",
    "/api/forgot-password",
    "/api/reset-password",
    "/api/public/stats",
    "/api/logout",   # clearing your own session is not a CSRF risk
}


def _get_or_create_token(response):
    """
    Read the existing csrf_token cookie or mint a new one.
    Always refreshes the cookie so the expiry slides forward.
    """
    token = request.cookies.get(CSRF_COOKIE)
    if not token:
        token = secrets.token_hex(32)

    # SameSite=Lax blocks the most common CSRF vectors.
    # HttpOnly=False is intentional — JS must be able to read this cookie.
    # secure flag is driven by HTTPS_ENABLED env var so it works locally and in production.
    https_enabled = os.environ.get("HTTPS_ENABLED", "false").lower() == "true"
    response.set_cookie(
        CSRF_COOKIE,
        token,
        samesite="Lax",
        httponly=False,
        secure=https_enabled,
    )
    return token


def init_csrf(app):
    """
    Register the two Flask hooks that implement CSRF protection.
    Call this once in app.py after creating the Flask app.
    """

    @app.before_request
    def enforce_csrf():
        if request.method not in CSRF_METHODS:
            return  # safe methods — no check needed

        if request.path in CSRF_EXEMPT:
            return  # pre-login flows — exempt

        cookie_token  = request.cookies.get(CSRF_COOKIE, "")
        header_token  = request.headers.get(CSRF_HEADER, "")

        if not cookie_token or not header_token:
            logger.warning("CSRF token missing on %s %s", request.method, request.path)
            return jsonify({"error": "CSRF token missing"}), 403

        # Use hmac.compare_digest equivalent to prevent timing attacks
        if not secrets.compare_digest(cookie_token, header_token):
            logger.warning("CSRF token mismatch on %s %s", request.method, request.path)
            return jsonify({"error": "CSRF token invalid"}), 403

    @app.after_request
    def set_csrf_cookie(response):
        _get_or_create_token(response)
        return response

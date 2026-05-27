"""
services/email_service.py
All outbound email logic using the Brevo (Sendinblue) API.
Keeps every HTML template and sending helper in one place.
"""
import os
import json
import logging
import urllib.request as _req
import urllib.error   as _err

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
def _brevo_config() -> tuple:
    """Read Brevo credentials at call-time so missing values surface clearly."""
    key   = os.environ.get("BREVO_API_KEY",    "").strip()
    email = os.environ.get("BREVO_FROM_EMAIL", "").strip()
    name  = os.environ.get("BREVO_FROM_NAME",  "CivicConnect").strip()
    return key, email, name

STATUS_ICONS  = {"Pending": "⏳", "In Progress": "🔧", "Resolved": "✅"}
STATUS_COLORS = {"Pending": "#f59e0b", "In Progress": "#3b82f6", "Resolved": "#10b981"}


# ── Low-level sender ──────────────────────────────────────────

def _brevo_send(to_email: str, subject: str, html: str, *, raise_on_error: bool = False) -> None:
    """
    Send one transactional email via Brevo.
    By default silently swallows errors so a mail failure never crashes
    the app. Pass raise_on_error=True for the OTP flow where we want
    the caller to surface the problem to the user.
    """
    api_key, from_email, from_name = _brevo_config()

    if not api_key:
        msg = "BREVO_API_KEY is not set in .env"
        if raise_on_error:
            raise RuntimeError(msg)
        logger.warning(msg)
        return
    if not from_email or "@" not in from_email:
        msg = "BREVO_FROM_EMAIL is not set or invalid in .env"
        if raise_on_error:
            raise RuntimeError(msg)
        logger.warning(msg)
        return

    payload = json.dumps({
        "sender":      {"name": from_name, "email": from_email},
        "to":          [{"email": to_email}],
        "subject":     subject,
        "htmlContent": html,
    }).encode("utf-8")

    request = _req.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={"Content-Type": "application/json", "api-key": api_key},
        method="POST",
    )
    try:
        with _req.urlopen(request, timeout=15) as resp:
            resp.read()
    except _err.HTTPError as exc:
        body = exc.read().decode("utf-8")
        msg  = f"Brevo API error {exc.code}: {body}"
        logger.error(msg)
        if raise_on_error:
            raise RuntimeError(msg) from exc
    except Exception as exc:
        logger.error("Brevo request failed: %s", exc)
        if raise_on_error:
            raise


# ── Public helpers ─────────────────────────────────────────────

def send_otp_email(to_email: str, otp: str, name: str) -> None:
    """Send OTP verification code. Raises on failure."""
    html = f"""
    <div style="font-family:DM Sans,Arial,sans-serif;max-width:480px;margin:auto;
                padding:2rem;background:#f8fafc;border-radius:12px;">
      <h2 style="color:#0f172a;font-size:1.4rem;margin-bottom:.5rem;">Verify your Gmail</h2>
      <p style="color:#475569;margin-bottom:1.5rem;">
        Hi {name}, use the code below to complete your CivicConnect registration.
        It expires in <strong>10 minutes</strong>.
      </p>
      <div style="background:#fff;border:2px dashed #4f46e5;border-radius:12px;
                  padding:1.5rem;text-align:center;margin-bottom:1.5rem;">
        <span style="font-size:2.4rem;font-weight:800;letter-spacing:.3em;color:#4f46e5;">
          {otp}
        </span>
      </div>
      <p style="color:#94a3b8;font-size:.82rem;">
        If you didn't request this, ignore this email. Do not share this code with anyone.
      </p>
    </div>"""
    _brevo_send(to_email, "Your CivicConnect Verification Code", html, raise_on_error=True)


def send_status_notification(complaint: dict, new_status: str,
                              user_email: str, user_name: str) -> None:
    """Notify a citizen that their complaint status changed."""
    icon  = STATUS_ICONS.get(new_status, "📋")
    color = STATUS_COLORS.get(new_status, "#4f46e5")
    html = f"""
    <div style="font-family:DM Sans,Arial,sans-serif;max-width:520px;margin:auto;
                padding:0;border-radius:14px;overflow:hidden;
                box-shadow:0 4px 24px rgba(0,0,0,.08);">
      <div style="background:linear-gradient(135deg,#1a2e6b,#1e4fd8);
                  padding:1.8rem 2rem;text-align:center;">
        <div style="font-size:2.5rem;">{icon}</div>
        <h1 style="color:#fff;font-size:1.3rem;margin:.5rem 0 .25rem;
                   font-family:Georgia,serif;">Complaint Status Updated</h1>
        <p style="color:rgba(255,255,255,.75);font-size:.85rem;margin:0;">
          CivicConnect Grievance Portal
        </p>
      </div>
      <div style="background:#fff;padding:1.8rem 2rem;">
        <p style="color:#475569;margin-bottom:1.2rem;">
          Hi <strong>{user_name}</strong>, your complaint status has been updated.
        </p>
        <div style="background:#f8fafc;border:1px solid #e5e7eb;border-radius:10px;
                    padding:1rem 1.2rem;margin-bottom:1.2rem;">
          <div style="font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;
                      color:#64748b;margin-bottom:.3rem;">Complaint</div>
          <div style="font-size:1rem;font-weight:700;color:#0f172a;">
            {complaint.get('title','')}
          </div>
          <div style="font-size:.78rem;color:#64748b;margin-top:.2rem;">
            ID: {complaint.get('complaint_id','')}
          </div>
        </div>
        <div style="text-align:center;margin:1.5rem 0;">
          <span style="background:{color};color:#fff;padding:.55rem 1.5rem;
                       border-radius:999px;font-weight:700;font-size:1rem;">
            {icon} {new_status}
          </span>
        </div>
        <p style="color:#64748b;font-size:.82rem;text-align:center;">
          Log in to CivicConnect to view full details and track progress.
        </p>
      </div>
      <div style="background:#f8fafc;padding:1rem 2rem;text-align:center;
                  border-top:1px solid #e5e7eb;">
        <p style="color:#94a3b8;font-size:.75rem;margin:0;">
          CivicConnect · Civic Grievance Management System
        </p>
      </div>
    </div>"""
    _brevo_send(user_email, f"[CivicConnect] Your complaint is now: {new_status}", html)


def send_password_reset_email(to_email: str, name: str, reset_link: str) -> None:
    """Send password-reset link email."""
    html = f"""
    <div style="font-family:DM Sans,Arial,sans-serif;max-width:480px;margin:auto;
                padding:0;border-radius:14px;overflow:hidden;
                box-shadow:0 4px 24px rgba(0,0,0,.08);">
      <div style="background:linear-gradient(135deg,#1a2e6b,#1e4fd8);
                  padding:1.8rem 2rem;text-align:center;">
        <div style="font-size:2.5rem;">🔐</div>
        <h1 style="color:#fff;font-size:1.2rem;margin:.5rem 0 .25rem;
                   font-family:Georgia,serif;">Password Reset Request</h1>
      </div>
      <div style="background:#fff;padding:1.8rem 2rem;">
        <p style="color:#475569;">
          Hi <strong>{name}</strong>, we received a request to reset your
          CivicConnect password.
        </p>
        <div style="text-align:center;margin:1.5rem 0;">
          <a href="{reset_link}"
             style="background:#4f46e5;color:#fff;padding:.75rem 2rem;
                    border-radius:10px;text-decoration:none;font-weight:700;
                    font-size:.95rem;display:inline-block;">
            Reset My Password
          </a>
        </div>
        <p style="color:#64748b;font-size:.82rem;">
          This link expires in <strong>30 minutes</strong>.
          If you didn't request this, ignore this email.
        </p>
      </div>
    </div>"""
    _brevo_send(to_email, "Reset your CivicConnect password", html)

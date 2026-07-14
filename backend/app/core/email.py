"""
Email service — async SMTP via aiosmtplib.

Usage:
    await send_approval_email(
        to_email="operator@example.com",
        full_name="Capt. Arjun Singh",
        username="arjun_s",
        temp_password="Xk9@mNpQ",
        role="flight_controller",
    )

If SMTP_ENABLED=false (or SMTP_PASSWORD is empty) the call is a no-op and
logs a warning — the accept endpoint never fails because email is unavailable.
"""
import asyncio
import textwrap
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
import structlog

from app.config import get_settings

log = structlog.get_logger()


def _build_message(
    to_email: str,
    full_name: str,
    username: str,
    temp_password: str,
    role: str,
) -> MIMEMultipart:
    cfg = get_settings()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "DroneArjuna GCS — Account Approved"
    msg["From"] = cfg.smtp_from
    msg["To"] = to_email

    plain = textwrap.dedent(f"""\
        DroneArjuna GCS — Account Approved
        ===================================

        Hello {full_name},

        Your access request has been reviewed and approved by the system
        administrator. Your account details are below.

        Username   : {username}
        Password   : {temp_password}
        Role       : {role}
        Login URL  : http://localhost:3000

        This is a temporary password. You will be prompted to change it
        on your first login.

        If you did not request this account, contact your system administrator
        immediately.

        — DroneArjuna GCS Operations
    """)

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{font-family:-apple-system,Segoe UI,sans-serif;background:#f1f5f9;margin:0;padding:32px 16px}}
  .card{{background:#fff;border-radius:6px;max-width:520px;margin:0 auto;overflow:hidden;
         box-shadow:0 1px 4px rgba(0,0,0,.1)}}
  .header{{background:#0f1620;padding:24px 32px;display:flex;align-items:center;gap:12px}}
  .header-title{{color:#fff;font-size:18px;font-weight:700;letter-spacing:-.01em}}
  .header-sub{{color:#8aaac8;font-size:12px;margin-top:2px}}
  .body{{padding:32px}}
  .body p{{color:#334155;font-size:14px;line-height:1.6;margin:0 0 16px}}
  .creds{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:4px;
          padding:16px 20px;margin:20px 0}}
  .creds table{{width:100%;border-collapse:collapse}}
  .creds td{{padding:5px 0;font-size:14px;color:#334155}}
  .creds td:first-child{{width:110px;color:#64748b;font-size:12px;
                         font-weight:600;text-transform:uppercase;letter-spacing:.06em}}
  .creds code{{font-family:Courier New,monospace;background:#e2e8f0;
               padding:2px 6px;border-radius:3px;font-size:13px;color:#0f172a}}
  .badge{{display:inline-block;background:#dbeafe;color:#1d4ed8;border-radius:3px;
          font-size:11px;font-weight:600;padding:2px 8px;letter-spacing:.04em;
          text-transform:uppercase}}
  .warn{{background:#fef9c3;border-left:3px solid #ca8a04;padding:10px 14px;
         border-radius:0 3px 3px 0;font-size:13px;color:#78350f;margin:20px 0}}
  .btn{{display:inline-block;background:#1d4ed8;color:#fff !important;text-decoration:none;
        font-size:14px;font-weight:600;padding:12px 28px;border-radius:6px}}
  .footer{{background:#f8fafc;border-top:1px solid #e2e8f0;padding:16px 32px;
           font-size:11px;color:#94a3b8}}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <div>
      <div class="header-title">DroneArjuna GCS</div>
      <div class="header-sub">Ground Control System — ACS Technologies Limited</div>
    </div>
  </div>
  <div class="body">
    <p>Hello <strong>{full_name}</strong>,</p>
    <p>Your access request has been reviewed and <strong>approved</strong> by the
    system administrator. Your login credentials are below.</p>
    <div class="creds">
      <table>
        <tr><td>Username</td><td><code>{username}</code></td></tr>
        <tr><td>Password</td><td><code>{temp_password}</code></td></tr>
        <tr><td>Role</td><td><span class="badge">{role}</span></td></tr>
      </table>
    </div>
    <div class="warn">
      This is a <strong>temporary password</strong>. You will be prompted to
      set a permanent password on your first login.
    </div>
    <div style="text-align:center;margin:24px 0">
      <a href="http://localhost:3000" class="btn">Sign In to DroneArjuna →</a>
    </div>
    <p>If you did not request this account, contact your system administrator
    immediately.</p>
  </div>
  <div class="footer">
    DroneArjuna GCS — RESTRICTED / CONFIDENTIAL &nbsp;|&nbsp;
    ACS Technologies Limited
  </div>
</div>
</body>
</html>"""

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    return msg


async def send_approval_email(
    to_email: str,
    full_name: str,
    username: str,
    temp_password: str,
    role: str,
) -> None:
    """Send account-approved email. Silently skipped if SMTP is disabled."""
    cfg = get_settings()

    if not cfg.smtp_enabled:
        log.warning("approval_email_skipped", reason="SMTP_ENABLED=false", to=to_email)
        return

    msg = _build_message(to_email, full_name, username, temp_password, role)

    # Build kwargs — omit credentials when not set (Mailhog dev mode)
    send_kwargs: dict = {
        "hostname": cfg.smtp_host,
        "port": cfg.smtp_port,
    }
    if cfg.smtp_user and cfg.smtp_password:
        send_kwargs["username"] = cfg.smtp_user
        send_kwargs["password"] = cfg.smtp_password
        send_kwargs["start_tls"] = True   # required for Gmail / real SMTP

    try:
        await aiosmtplib.send(msg, **send_kwargs)
        log.info("approval_email_sent", to=to_email, username=username)
    except Exception as exc:
        # Email failure must never block the approve workflow
        log.error("approval_email_failed", to=to_email, error=str(exc))

"""Gmail SMTP email delivery for verification codes, email links, and password resets."""

import asyncio
import json
import logging
import smtplib
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.settings import Settings

logger = logging.getLogger("auth_svc.email")

_BREVO_EMAIL_API_URL = "https://api.brevo.com/v3/smtp/email"

_OTP_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
  <head><meta charset="utf-8" /></head>
  <body style="margin:0;padding:32px 16px;background-color:#0b0f19;\
font-family:sans-serif;color:#f1f5f9;">
    <div style="max-width:440px;margin:0 auto;background:#131b2e;\
border:1px solid #1e293b;border-radius:16px;padding:28px;text-align:center;">
      <h2 style="color:#ff8a5c;margin:0 0 12px;font-size:22px;">ZeoAuction</h2>
      <p style="color:#94a3b8;font-size:14px;margin:0 0 20px;">
        Your login verification code (valid for 10 minutes):
      </p>
      <div style="background:#1a243a;padding:16px;border-radius:12px;\
font-size:32px;font-weight:700;letter-spacing:6px;color:#ffd166;font-family:monospace;">
        {otp_code}
      </div>
      <p style="color:#64748b;font-size:12px;margin:20px 0 0;">
        Never share this code. If you did not request this, please ignore.
      </p>
    </div>
  </body>
</html>
"""

_VERIFY_EMAIL_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
  <head><meta charset="utf-8" /></head>
  <body style="margin:0;padding:32px 16px;background-color:#0b0f19;\
font-family:sans-serif;color:#f1f5f9;">
    <div style="max-width:460px;margin:0 auto;background:#131b2e;\
border:1px solid #1e293b;border-radius:16px;padding:32px;text-align:center;">
      <h2 style="color:#ff8a5c;margin:0 0 12px;font-size:24px;">ZeoAuction</h2>
      <h3 style="color:#ffffff;margin:0 0 16px;font-size:18px;">Verify Your Email Address</h3>
      <p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 24px;">
        Welcome to ZeoAuction! Please confirm your email address by clicking the button below.
        This link will expire in 24 hours.
      </p>
      <div style="margin:28px 0;">
        <a href="{verify_url}" style="background-color:#ff8a5c;color:#0b0f19;\
text-decoration:none;padding:12px 28px;border-radius:9999px;font-weight:700;\
font-size:15px;display:inline-block;box-shadow:0 4px 14px rgba(255,138,92,0.4);">
          Verify Email Address
        </a>
      </div>
      <p style="color:#64748b;font-size:12px;line-height:1.5;margin:24px 0 0;word-break:break-all;">
        If the button doesn't work, copy and paste this link into your browser:<br />
        <a href="{verify_url}" style="color:#ffd166;">{verify_url}</a>
      </p>
    </div>
  </body>
</html>
"""

_RESET_PASSWORD_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
  <head><meta charset="utf-8" /></head>
  <body style="margin:0;padding:32px 16px;background-color:#0b0f19;\
font-family:sans-serif;color:#f1f5f9;">
    <div style="max-width:460px;margin:0 auto;background:#131b2e;\
border:1px solid #1e293b;border-radius:16px;padding:32px;text-align:center;">
      <h2 style="color:#ff8a5c;margin:0 0 12px;font-size:24px;">ZeoAuction</h2>
      <h3 style="color:#ffffff;margin:0 0 16px;font-size:18px;">Reset Your Password</h3>
      <p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 24px;">
        We received a request to reset your password. Click below to choose a new password.
        This link is valid for 1 hour.
      </p>
      <div style="margin:28px 0;">
        <a href="{reset_url}" style="background-color:#ff8a5c;color:#0b0f19;\
text-decoration:none;padding:12px 28px;border-radius:9999px;font-weight:700;\
font-size:15px;display:inline-block;box-shadow:0 4px 14px rgba(255,138,92,0.4);">
          Reset Password
        </a>
      </div>
      <p style="color:#64748b;font-size:12px;line-height:1.5;margin:24px 0 0;word-break:break-all;">
        If you didn't request a password reset, you can safely ignore this email.<br /><br />
        Direct link: <a href="{reset_url}" style="color:#ffd166;">{reset_url}</a>
      </p>
    </div>
  </body>
</html>
"""  # noqa: S105


def _send_brevo_email_sync(
    to_email: str, subject: str, text_content: str, html_content: str, settings: Settings
) -> bool:
    """Deliver one transactional email through Brevo's HTTPS API."""
    api_key = (settings.brevo_api_key or "").strip()
    sender_email = (settings.brevo_sender_email or settings.gmail_user or "").strip()
    sender_name = (settings.brevo_sender_name or "ZeoAuction").strip()

    if not api_key or not sender_email:
        logger.warning(
            "[AUTH-EMAIL] Missing Brevo configuration (API_KEY=%s, SENDER_EMAIL='%s'). "
            "Email to <%s> NOT sent.",
            bool(api_key),
            sender_email,
            to_email,
        )
        return False

    payload = json.dumps(
        {
            "sender": {"name": sender_name, "email": sender_email},
            "to": [{"email": to_email}],
            "subject": subject,
            "textContent": text_content,
            "htmlContent": html_content,
        }
    ).encode("utf-8")
    request = Request(
        _BREVO_EMAIL_API_URL,
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "api-key": api_key,
        },
        method="POST",
    )

    logger.info("[AUTH-EMAIL] Sending '%s' to <%s> through Brevo HTTPS API", subject, to_email)
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed trusted HTTPS URL
            status = response.status
        if 200 <= status < 300:
            logger.info("[AUTH-EMAIL] Brevo accepted email for <%s>", to_email)
            return True
        logger.error("[AUTH-EMAIL] Brevo returned unexpected HTTP status %s", status)
    except HTTPError as exc:
        # Brevo's JSON error is safe and useful for diagnosing an unverified sender or bad key.
        response_body = exc.read().decode("utf-8", errors="replace")[:500]
        logger.error("[AUTH-EMAIL] Brevo rejected email (HTTP %s): %s", exc.code, response_body)
    except URLError as exc:
        logger.error("[AUTH-EMAIL] Could not connect to Brevo API: %s", exc.reason)
    except Exception as exc:
        logger.exception("[AUTH-EMAIL] Unexpected Brevo delivery error: %s", exc)
    return False


def _send_smtp_email_sync(
    to_email: str, subject: str, text_content: str, html_content: str, settings: Settings
) -> bool:
    """Legacy Gmail SMTP fallback, retained for local development."""
    username = (settings.gmail_user or "").strip()
    # Google App Passwords often contain spaces (e.g. 'xxxx yyyy zzzz wwww')
    password = (settings.gmail_password or "").replace(" ", "").strip()
    if not username or not password:
        logger.warning(
            "[AUTH-EMAIL] Missing Gmail credentials (USER='%s', PW=%s). Email to <%s> NOT sent.",
            username,
            bool(password),
            to_email,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"ZeoAuction <{username}>"
    msg["To"] = to_email
    msg.set_content(text_content)
    msg.add_alternative(html_content, subtype="html")

    logger.info(
        "[AUTH-EMAIL] Initiating SMTP connection to %s:%s (TLS=%s) to send '%s' to <%s>",
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_use_tls,
        subject,
        to_email,
    )

    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                logger.info("[AUTH-EMAIL] Authenticating as <%s> via SSL...", username)
                server.login(username, password)
                logger.info("[AUTH-EMAIL] SMTP authentication successful. Dispatching message...")
                server.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                logger.info("[AUTH-EMAIL] Authenticating as <%s> via STARTTLS...", username)
                server.login(username, password)
                logger.info("[AUTH-EMAIL] SMTP authentication successful. Dispatching message...")
                server.send_message(msg)

        logger.info(
            "[AUTH-EMAIL] SUCCESS: Email successfully delivered to SMTP server for <%s>",
            to_email,
        )
        return True
    except smtplib.SMTPAuthenticationError as exc:
        logger.error(
            "[AUTH-EMAIL] SMTP Authentication Failed for user <%s>: %s",
            username,
            exc,
        )
        return False
    except smtplib.SMTPException as exc:
        logger.error(
            "[AUTH-EMAIL] SMTP Protocol Error while sending to <%s>: %s",
            to_email,
            exc,
        )
        return False
    except Exception as exc:
        logger.exception(
            "[AUTH-EMAIL] Unexpected error delivering email to <%s>: %s",
            to_email,
            exc,
        )
        return False


def _send_email_sync(
    to_email: str, subject: str, text_content: str, html_content: str, settings: Settings
) -> bool:
    """Prefer Brevo on Render; fall back to Gmail SMTP for existing local setups."""
    if settings.brevo_api_key:
        return _send_brevo_email_sync(
            to_email, subject, text_content, html_content, settings
        )
    return _send_smtp_email_sync(to_email, subject, text_content, html_content, settings)


async def send_otp_email(to_email: str, otp_code: str, settings: Settings) -> bool:
    """Send a verification OTP through the configured transactional email provider."""
    logger.info("[AUTH-EMAIL] Queuing OTP email for <%s>", to_email)
    try:
        sent = await asyncio.to_thread(
            _send_email_sync,
            to_email,
            f"Your ZeoAuction Verification Code: {otp_code}",
            f"Your login code is: {otp_code} (expires in 10 minutes).",
            _OTP_HTML_TEMPLATE.format(otp_code=otp_code),
            settings,
        )
        if sent:
            logger.info("[AUTH-EMAIL] Successfully sent OTP email to <%s>", to_email)
        else:
            logger.warning("[AUTH-EMAIL] Failed to send OTP email to <%s>", to_email)
        return sent
    except Exception as exc:
        logger.error("[AUTH-EMAIL] Exception in send_otp_email for <%s>: %s", to_email, exc)
        return False


async def send_verification_link_email(
    to_email: str, verify_url: str, settings: Settings
) -> bool:
    """Send an account email verification link."""
    logger.info("[AUTH-EMAIL] Queuing account verification email for <%s>", to_email)
    try:
        sent = await asyncio.to_thread(
            _send_email_sync,
            to_email,
            "Verify your ZeoAuction email address",
            f"Welcome to ZeoAuction! Please verify your email by opening:\n{verify_url}\n",
            _VERIFY_EMAIL_HTML_TEMPLATE.format(verify_url=verify_url),
            settings,
        )
        if sent:
            logger.info("[AUTH-EMAIL] Successfully sent verification email to <%s>", to_email)
        else:
            logger.warning("[AUTH-EMAIL] Failed to send verification email to <%s>", to_email)
        return sent
    except Exception as exc:
        logger.error(
            "[AUTH-EMAIL] Exception in send_verification_link_email for <%s>: %s",
            to_email,
            exc,
        )
        return False


async def send_password_reset_link_email(
    to_email: str, reset_url: str, settings: Settings
) -> bool:
    """Send a password reset link."""
    logger.info("[AUTH-EMAIL] Queuing password reset email for <%s>", to_email)
    try:
        sent = await asyncio.to_thread(
            _send_email_sync,
            to_email,
            "Reset your ZeoAuction password",
            f"To reset your ZeoAuction password, open this link:\n{reset_url}\n",
            _RESET_PASSWORD_HTML_TEMPLATE.format(reset_url=reset_url),
            settings,
        )
        if sent:
            logger.info("[AUTH-EMAIL] Successfully sent password reset email to <%s>", to_email)
        else:
            logger.warning("[AUTH-EMAIL] Failed to send password reset email to <%s>", to_email)
        return sent
    except Exception as exc:
        logger.error(
            "[AUTH-EMAIL] Exception in send_password_reset_link_email for <%s>: %s",
            to_email,
            exc,
        )
        return False

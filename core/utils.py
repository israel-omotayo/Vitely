import logging
import threading
import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


def is_json_request(request):
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def _send_via_resend(to_email: str, subject: str, html_content: str) -> None:
    api_key = getattr(settings, "RESEND_API_KEY", "")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not set.")

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": settings.DEFAULT_FROM_EMAIL,
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        },
        timeout=10,
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Resend API error {response.status_code}: {response.text[:200]}"
        )


def _send_via_django(to_email: str, subject: str, html_content: str) -> None:
    msg = EmailMultiAlternatives(
        subject=subject,
        body="Please view this email in an HTML-compatible client.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send(fail_silently=False)


def send_email(to_email: str, subject: str, html_content: str) -> None:
    try:
        if getattr(settings, "RESEND_API_KEY", ""):
            _send_via_resend(to_email, subject, html_content)
        else:
            _send_via_django(to_email, subject, html_content)
        logger.info("Email sent to %s (subject=%s)", to_email, subject)
    except Exception as e:
        logger.exception("Email failed to %s: %s", to_email, e)
        raise


def send_email_async(to_email: str, subject: str, html_content: str, context: str = "") -> None:
    if getattr(settings, "EMAIL_BACKEND", "") == "django.core.mail.backends.console.EmailBackend":
        send_email(to_email, subject, html_content)
        return

    def _send():
        try:
            send_email(to_email, subject, html_content)
        except Exception as e:
            logger.error(
                "Async email delivery failed to %s (context=%s): %s",
                to_email, context, e,
            )

    thread = threading.Thread(target=_send, daemon=True, name=f"email-{context}")
    thread.start()


def build_vitely_email(heading, message, action_content,
        notice="If you didn't request this, you can safely ignore this email."):
    """
    Wraps content in Vitely's branded HTML email template.
    action_content: a <a> button tag, a code box div, or any HTML snippet.
    """
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <style>
        body {{ margin:0; padding:0; background:#FAF7F4; font-family:'Helvetica',Arial,sans-serif; color:#2C2420; }}
        .wrapper {{ max-width:560px; margin:0 auto; padding:2rem 1rem; }}
        .logo {{ font-size:1.2rem; font-weight:700; color:#C17D5A; letter-spacing:-0.02em; margin-bottom:0.25rem; }}
        .card {{ background:#fff; border-radius:14px; border:1px solid #EDE8E2; overflow:hidden; margin-top:1.25rem; }}
        .card-body {{ padding:2rem 2rem 1.75rem; }}
        h1 {{ margin:0 0 0.5rem; font-size:1.2rem; font-weight:600; color:#2C2420; }}
        p {{ margin:0 0 1rem; font-size:0.9rem; line-height:1.6; color:#9C8880; }}
        .action-area {{ margin:1.5rem 0; text-align:center; }}
        .btn {{
          display:inline-block; background:#C17D5A; color:#fff !important;
          text-decoration:none; padding:0.75rem 2rem; border-radius:8px;
          font-size:0.9rem; font-weight:600;
        }}
        .code-box {{
          background:#FAF7F4; border:1px solid #EDE8E2; border-radius:8px;
          padding:1rem; font-size:1.75rem; font-weight:bold; letter-spacing:4px;
          color:#C17D5A; font-family:monospace; display:inline-block;
        }}
        .divider {{ border:none; border-top:1px solid #EDE8E2; margin:1.5rem 0; }}
        .notice {{ font-size:0.8rem; color:#9C8880; line-height:1.5; margin-top:1rem; }}
        .footer {{ font-size:0.75rem; color:#9C8880; text-align:center; line-height:1.6; margin-top:1.5rem; }}
      </style>
    </head>
    <body>
      <div class="wrapper">
        <div class="logo">Vitely</div>
        <div class="card">
          <div class="card-body">
            <h1>{heading}</h1>
            <p>{message}</p>
            <div class="action-area">{action_content}</div>
            <hr class="divider">
            <p class="notice">{notice}</p>
          </div>
        </div>
        <div class="footer">
          <p>© Vitely · Book your wellbeing<br>The Vitely Team</p>
        </div>
      </div>
    </body>
    </html>
    """
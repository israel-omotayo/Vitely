"""
All Vitely transactional emails. Each function builds the HTML
via core/utils.build_vitely_email() then fires send_email_async().
"""

from django.conf import settings
from django.urls import reverse

from core.utils import send_email_async, build_vitely_email
from .models import Appointment
from dashboard.models import StaffInvite

# Email verification (slot hold)

def send_verification_email(appointment: Appointment, request=None) -> None:
    """
    Sent immediately after booking submission.
    Customer must click to confirm — slot is held for 30 min.
    """
    verify_path = reverse(
        "bookings:verify_booking",
        kwargs={"token": str(appointment.confirmation_token)},
    )
    verify_url = _absolute_url(verify_path, request)

    html = build_vitely_email(
        heading="Confirm your booking",
        message=(
            f"Hi {appointment.customer_name}, you're almost done! "
            f"Click the button below to confirm your <strong>{appointment.service.name}</strong> "
            f"appointment on <strong>{appointment.start_datetime:%A, %d %B %Y at %H:%M}</strong>. "
            "This link expires in 30 minutes."
        ),
        action_content=f'<a href="{verify_url}" class="btn">Confirm my booking</a>',
        notice="If you didn't request this booking, you can safely ignore this email.",
    )

    send_email_async(
        to_email=appointment.customer_email,
        subject="Vitely · Confirm your booking",
        html_content=html,
        context=f"verify-booking-{appointment.id}",
    )


# Booking confirmed → customer

def send_confirmation_email(appointment: Appointment, request=None) -> None:
    """
    Sent after the customer clicks the verify link.
    Includes a direct booking link and a cancel link.
    """
    booking_path = reverse(
        "bookings:booking_detail",
        kwargs={"token": str(appointment.confirmation_token)},
    )
    cancel_path = reverse(
        "bookings:cancel_booking",
        kwargs={"token": str(appointment.confirmation_token)},
    )
    booking_url = _absolute_url(booking_path, request)
    cancel_url = _absolute_url(cancel_path, request)

    details_html = f"""
    <div style="background:#FAF7F4;border:1px solid #EDE8E2;border-radius:8px;padding:1rem;margin:1rem 0;font-size:0.85rem;color:#2C2420;">
      <strong>Service:</strong> {appointment.service.name}<br>
      <strong>Date:</strong> {appointment.start_datetime:%A, %d %B %Y}<br>
      <strong>Time:</strong> {appointment.start_datetime:%H:%M} – {appointment.end_datetime:%H:%M}<br>
      <strong>Duration:</strong> {appointment.service.duration_minutes} minutes
    </div>
    <a href="{booking_url}" class="btn">View booking</a>
    <p style="margin-top:1rem;font-size:0.8rem;color:#9C8880;">
      Need to cancel? You can do so up to {appointment.service.business.cancellation_notice_hours} hours before your appointment.
      <a href="{cancel_url}" style="color:#B85C5C;">Cancel booking</a>
    </p>
    """

    html = build_vitely_email(
        heading="Your booking is confirmed ✓",
        message=(
            f"Great news, {appointment.customer_name}! Your <strong>{appointment.service.name}</strong> "
            f"appointment is confirmed."
        ),
        action_content=details_html,
        notice="Keep this email — it contains your booking link.",
    )

    send_email_async(
        to_email=appointment.customer_email,
        subject=f"Vitely · Booking confirmed — {appointment.start_datetime:%d %b %Y at %H:%M}",
        html_content=html,
        context=f"confirmed-{appointment.id}",
    )


# New booking alert → admin + all staff

def send_new_booking_alert(appointment: Appointment, request=None) -> None:
    """Notifies the owner and all staff of a new confirmed booking."""
    from django.contrib.auth.models import User

    admin_path = reverse("dashboard:appointment_detail", kwargs={"pk": appointment.id})
    admin_url = _absolute_url(admin_path, request)

    html = build_vitely_email(
        heading="New booking received",
        message=(
            f"<strong>{appointment.customer_name}</strong> has booked "
            f"<strong>{appointment.service.name}</strong> on "
            f"<strong>{appointment.start_datetime:%A, %d %B %Y at %H:%M}</strong>."
            f"<br><br>Email: {appointment.customer_email}"
            + (f"<br>Phone: {appointment.customer_phone}" if appointment.customer_phone else "")
            + (f"<br>Notes: {appointment.notes}" if appointment.notes else "")
        ),
        action_content=f'<a href="{admin_url}" class="btn">View in dashboard</a>',
        notice="",
    )

    # Gather owner + staff emails
    staff_users = User.objects.filter(
        userprofile__role__in=["owner", "staff"],
        is_active=True,
    ).values_list("email", flat=True)

    for email in staff_users:
        send_email_async(
            to_email=email,
            subject=f"Vitely · New booking — {appointment.customer_name}",
            html_content=html,
            context=f"alert-{appointment.id}",
        )


# Booking cancelled → customer

def send_cancellation_email(appointment: Appointment, request=None) -> None:
    rebook_path = reverse("bookings:services")
    rebook_url = _absolute_url(rebook_path, request)

    html = build_vitely_email(
        heading="Your booking has been cancelled",
        message=(
            f"Hi {appointment.customer_name}, your <strong>{appointment.service.name}</strong> "
            f"appointment on <strong>{appointment.start_datetime:%A, %d %B %Y at %H:%M}</strong> "
            "has been cancelled."
        ),
        action_content=f'<a href="{rebook_url}" class="btn">Book again</a>',
        notice="If you didn't request this cancellation, please contact us.",
    )

    send_email_async(
        to_email=appointment.customer_email,
        subject="Vitely · Booking cancelled",
        html_content=html,
        context=f"cancelled-{appointment.id}",
    )


# 24hr reminder → customer

def send_reminder_email(appointment: Appointment, request=None) -> None:
    booking_path = reverse(
        "bookings:booking_detail",
        kwargs={"token": str(appointment.confirmation_token)},
    )
    booking_url = _absolute_url(booking_path, request)
    cancel_path = reverse(
        "bookings:cancel_booking",
        kwargs={"token": str(appointment.confirmation_token)},
    )
    cancel_url = _absolute_url(cancel_path, request)

    html = build_vitely_email(
        heading="Your appointment is tomorrow",
        message=(
            f"Hi {appointment.customer_name}, a quick reminder that your "
            f"<strong>{appointment.service.name}</strong> appointment is tomorrow, "
            f"<strong>{appointment.start_datetime:%A, %d %B at %H:%M}</strong>."
        ),
        action_content=(
            f'<a href="{booking_url}" class="btn">View booking</a>'
            f'<p style="margin-top:0.75rem;font-size:0.8rem;color:#9C8880;">'
            f'Need to cancel? <a href="{cancel_url}" style="color:#B85C5C;">Cancel booking</a></p>'
        ),
        notice="See you soon — The Vitely Team.",
    )

    send_email_async(
        to_email=appointment.customer_email,
        subject=f"Vitely · Reminder — {appointment.service.name} tomorrow at {appointment.start_datetime:%H:%M}",
        html_content=html,
        context=f"reminder-{appointment.id}",
    )


# Staff invite email

def send_staff_invite_email(invite: StaffInvite, business_name: str, request=None) -> None:
    accept_path = reverse("accounts:invite_accept", kwargs={"token": str(invite.token)})
    accept_url = _absolute_url(accept_path, request)

    html = build_vitely_email(
        heading=f"You're invited to join {business_name} on Vitely",
        message=(
            f"{invite.invited_by.get_full_name() or invite.invited_by.username} has invited you "
            f"to join the <strong>{business_name}</strong> team on Vitely as a staff member. "
            "Click below to accept — this link expires in 7 days."
        ),
        action_content=f'<a href="{accept_url}" class="btn">Accept invitation</a>',
        notice="If you weren't expecting this, you can safely ignore it.",
    )

    send_email_async(
        to_email=invite.email,
        subject=f"Vitely · You've been invited to join {business_name}",
        html_content=html,
        context=f"invite-{invite.id}",
    )


# Magic link → customer lookup

def send_magic_link_email(email: str, lookup_token: str, request=None) -> None:
    """
    Sent when a customer requests their booking list.
    Token is the lookup_token of their most recent booking.
    """
    lookup_path = reverse("bookings:booking_lookup", kwargs={"token": lookup_token})
    lookup_url = _absolute_url(lookup_path, request)

    html = build_vitely_email(
        heading="Your booking history",
        message=(
            "You requested a link to view your bookings. "
            "Click below — the link is valid for 24 hours."
        ),
        action_content=f'<a href="{lookup_url}" class="btn">View my bookings</a>',
        notice="If you didn't request this, you can safely ignore this email.",
    )

    send_email_async(
        to_email=email,
        subject="Vitely · Your booking link",
        html_content=html,
        context="magic-link",
    )


# Internal helper

def _absolute_url(path: str, request=None) -> str:
    """Builds a full URL from a path. Uses request if available, falls back to settings."""
    if request:
        return request.build_absolute_uri(path)
    base = getattr(settings, "BASE_FRONTEND_URL", "http://localhost:8000").rstrip("/")
    if not base.startswith("http"):
        base = f"https://{base}"
    return f"{base}{path}"
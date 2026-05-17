"""
All business logic for the admin dashboard.
Views are thin — they build a DTO and call a function here.
Nothing in this file imports from views.py.

ServiceError is imported from bookings.services — one exception class
throughout the whole stack so views only need to catch one type.
"""

import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from bookings.models import Appointment
from bookings.services import ServiceError # single exception class
from core.utils import build_vitely_email, send_email_async
from accounts.models import UserProfile

from .models import (
    BusinessProfile, Service, WeeklyAvailability,
    BlockedTime, StaffInvite,
)
from .schemas import (
    StaffInviteDTO, AppointmentStatusUpdateDTO,
    ServiceDTO, AvailabilityDTO, BlockedTimeDTO, AdminBookingDTO,
)

User = get_user_model()
logger = logging.getLogger(__name__)

INVITE_EXPIRY_HOURS = 48


# DASHBOARD STATS

def get_today_appointments(business: BusinessProfile) -> list:
    today = timezone.localdate()
    return list(
        Appointment.objects.select_related("service")
        .filter(service__business=business, start_datetime__date=today)
        .exclude(status=Appointment.Status.CANCELLED)
        .order_by("start_datetime")
    )


def get_dashboard_stats(business: BusinessProfile) -> dict:
    """
    Stats for the dashboard home. Revenue keys are always returned —
    the template gates visibility by role so staff never see them.
    """
    from django.db.models import Sum

    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    base_qs = Appointment.objects.filter(service__business=business)
    active = base_qs.exclude(status=Appointment.Status.CANCELLED)

    def revenue(qs):
        result = qs.filter(
            status__in=[Appointment.Status.COMPLETED]
        ).aggregate(total=Sum("service__price"))
        return result["total"] or 0

    return {
        "today_count": active.filter(start_datetime__date=today).count(),
        "week_count": active.filter(start_datetime__date__gte=week_start).count(),
        "week_revenue": revenue(base_qs.filter(start_datetime__date__gte=week_start)),
        "month_revenue": revenue(base_qs.filter(start_datetime__date__gte=month_start)),
        "today_appointments": get_today_appointments(business),
    }


# APPOINTMENTS 

def get_filtered_appointments(
    business: BusinessProfile,
    status: str = "",
    service_slug: str = "",
    search: str = "",
    date_str: str = "",
):
    """
    Returns a filtered queryset — NOT a list — so the view can paginate it.

    Returns the queryset directly.
    """
    qs = Appointment.objects.select_related("service").filter(
        service__business=business
    )
    if status:
        qs = qs.filter(status=status)
    if service_slug:
        qs = qs.filter(service__slug=service_slug)
    from django.db.models import Q

    if search:
        qs = qs.filter(
            Q(customer_name__icontains=search) |
            Q(customer_email__icontains=search)
        )
    if date_str:
        qs = qs.filter(start_datetime__date=date_str)

    return qs.order_by("-start_datetime")


@transaction.atomic
def admin_update_appointment(dto: AppointmentStatusUpdateDTO) -> Appointment:
    """
    Updates appointment status. Validates the new status is a legal choice.
    Raises ServiceError for invalid status values.
    """
    valid = {s.value for s in Appointment.Status}
    if dto.new_status not in valid:
        raise ServiceError(f"'{dto.new_status}' is not a valid status.")

    appt = Appointment.objects.select_related("service").get(id=dto.appointment_id)
    appt.status = dto.new_status
    appt.save(update_fields=["status"])

    logger.info("Appointment %s → %s", dto.appointment_id, dto.new_status)
    return appt


@transaction.atomic
def create_admin_booking(dto: AdminBookingDTO) -> Appointment:
    """
    Creates a booking on behalf of a customer from the dashboard.
    Skips email verification — admin bookings are confirmed immediately.
    Still re-checks slot availability inside the transaction.
    """
    from bookings.services import create_booking, get_available_slots
    from bookings.schemas import CreateBookingDTO

    service = Service.objects.select_related("business").get(id=dto.service_id)
    available = get_available_slots(service, dto.start_datetime.date())
    if dto.start_datetime not in available:
        raise ServiceError("That slot is no longer available. Please choose another time.")

    booking_dto = CreateBookingDTO(
        service_id=dto.service_id,
        start_datetime=dto.start_datetime,
        customer_name=dto.customer_name,
        customer_email=dto.customer_email,
        customer_phone=dto.customer_phone,
        notes=dto.notes,
    )
    appointment = create_booking(booking_dto)

    # Bypass the email verification step — admin confirms directly
    appointment.email_verified = True
    appointment.status = Appointment.Status.CONFIRMED
    appointment.save(update_fields=["email_verified", "status"])

    logger.info(
        "Admin booking created: %s for %s @ %s",
        service.name, dto.customer_email, dto.start_datetime,
    )
    return appointment


# SERVICES CRUD 

@transaction.atomic
def create_service(dto: ServiceDTO, business: BusinessProfile) -> Service:
    svc = Service.objects.create(
        business=business,
        name=dto.name,
        description=dto.description,
        duration_minutes=dto.duration_minutes,
        price=dto.price,
        capacity=dto.capacity,
        color=dto.color,
        is_active=dto.is_active,
    )
    logger.info("Service '%s' created (id=%s)", svc.name, svc.id)
    return svc


@transaction.atomic
def update_service(dto: ServiceDTO, business: BusinessProfile) -> Service:
    svc = Service.objects.get(pk=dto.pk, business=business)
    svc.name = dto.name
    svc.description = dto.description
    svc.duration_minutes = dto.duration_minutes
    svc.price = dto.price
    svc.capacity = dto.capacity
    svc.color = dto.color
    svc.is_active = dto.is_active
    svc.save()
    logger.info("Service '%s' updated (id=%s)", svc.name, svc.id)
    return svc


@transaction.atomic
def toggle_service(pk: int, business: BusinessProfile) -> Service:
    svc = Service.objects.get(pk=pk, business=business)
    svc.is_active = not svc.is_active
    svc.save(update_fields=["is_active"])
    logger.info("Service '%s' toggled → %s", svc.name, svc.is_active)
    return svc


# AVAILABILITY

@transaction.atomic
def upsert_availability(dto: AvailabilityDTO, business: BusinessProfile) -> WeeklyAvailability:
    """
    Creates or updates the schedule row for a given day.
    One row per day per business — unique_together enforces this at DB level.
    """
    avail, _ = WeeklyAvailability.objects.update_or_create(
        business=business,
        day_of_week=dto.day_of_week,
        defaults={
            "start_time": dto.start_time,
            "end_time": dto.end_time,
            "is_active": dto.is_active,
        },
    )
    logger.info(
        "Availability updated: %s %s–%s (active=%s)",
        avail.get_day_of_week_display(), dto.start_time, dto.end_time, dto.is_active,
    )
    return avail


# BLOCKED TIMES

@transaction.atomic
def add_blocked_time(dto: BlockedTimeDTO, business: BusinessProfile) -> BlockedTime:
    bt = BlockedTime.objects.create(
        business=business,
        start_datetime=dto.start_datetime,
        end_datetime=dto.end_datetime,
        reason=dto.reason,
    )
    logger.info("Blocked time added: %s → %s", dto.start_datetime, dto.end_datetime)
    return bt


@transaction.atomic
def delete_blocked_time(pk: int, business: BusinessProfile) -> None:
    bt = BlockedTime.objects.get(pk=pk, business=business)
    bt.delete()
    logger.info("Blocked time deleted: id=%s", pk)


# STAFF INVITE

@transaction.atomic
def send_staff_invite(dto: StaffInviteDTO, site_url: str) -> StaffInvite:
    """
    Deletes any previous pending invite for this email, creates a fresh one,
    and sends the invite email. Raises ServiceError if the email is already
    an active account.
    """
    if User.objects.filter(email__iexact=dto.email, is_active=True).exists():
        raise ServiceError("An account with this email already exists.")

    StaffInvite.objects.filter(email__iexact=dto.email, accepted=False).delete()

    invite = StaffInvite.objects.create(
        email=dto.email,
        invited_by_id=dto.invited_by_id,
        expires_at=timezone.now() + timedelta(hours=INVITE_EXPIRY_HOURS),
    )

    invite_url = f"{site_url}/accounts/invite/{invite.token}/"

    html = build_vitely_email(
        heading="You've been invited to Vitely",
        message=(
            "You've been invited to manage bookings as a staff member. "
            f"Click below to set up your account — this link expires in {INVITE_EXPIRY_HOURS} hours."
        ),
        action_content=f'<a href="{invite_url}" class="btn">Accept invitation</a>',
        notice="If you weren't expecting this, you can safely ignore it.",
    )

    send_email_async(
        to_email=dto.email,
        subject="You've been invited to manage Vitely bookings",
        html_content=html,
        context=f"staff-invite-{invite.id}",
    )

    logger.info("Staff invite sent to %s by user_id=%s", dto.email, dto.invited_by_id)
    return invite



# REVOKE STAFF

@transaction.atomic
def revoke_staff_access(staff_user_id: int, requesting_user) -> None:
    """
    Deactivates a staff account. Sets is_active=False — does not delete,
    so the audit trail of their appointments is preserved.
    Only the owner can call this.
    """
    try:
        if requesting_user.userprofile.role != "owner":
            raise ServiceError("Only the owner can revoke staff access.")
    except UserProfile.DoesNotExist:
        raise ServiceError("Your account profile was not found.")

    try:
        staff_user = User.objects.get(pk=staff_user_id)
        staff_profile = staff_user.userprofile
    except (User.DoesNotExist, UserProfile.DoesNotExist):
        raise ServiceError("Staff member not found.")

    if staff_profile.role != "staff":
        raise ServiceError("This account is not a staff member.")

    staff_user.is_active = False
    staff_user.save(update_fields=["is_active"])

    logger.info(
        "Staff access revoked: user_id=%s by owner user_id=%s",
        staff_user_id, requesting_user.id,
    )
import logging
from datetime import datetime, timedelta, date as date_type, time as time_type

from django.db import transaction
from django.utils import timezone
from django.core.cache import cache

from dashboard.models import Service, WeeklyAvailability, BlockedTime
from .models import Appointment
from .schemas import CreateBookingDTO

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    """Raised for expected, user-facing errors. Views catch this and
    show the message to the user."""
    pass


#  HELPERS 

def _combine(d: date_type, t: time_type) -> datetime:
    """Merge a date and time into a timezone-aware datetime."""
    return timezone.make_aware(datetime.combine(d, t))


def _overlaps_blocked(slot_start: datetime, slot_end: datetime, blocked_qs) -> bool:
    """True if the slot overlaps any blocked period."""
    for block in blocked_qs:
        if slot_start < block.end_datetime and slot_end > block.start_datetime:
            return True
    return False


def _overlaps_daily_break(slot_start: datetime, slot_end: datetime, business) -> bool:
    """True if the slot overlaps the business's recurring daily break."""
    if not business.break_start_time or not business.break_end_time:
        return False
    break_start = _combine(slot_start.date(), business.break_start_time)
    break_end = _combine(slot_start.date(), business.break_end_time)
    return slot_start < break_end and slot_end > break_start


def _slot_is_available(slot_start: datetime, slot_end: datetime, booked_qs) -> bool:
    """
    True when no active booking overlaps this service slot.
    A slot is single-use: once booked or held, it is no longer available.
    """
    return not any(
        appt.start_datetime < slot_end
        and appt.end_datetime > slot_start
        and appt.status != Appointment.Status.CANCELLED
        for appt in booked_qs
    )


def _invalidate_slot_cache(service: Service, dt: datetime):
    """
    Invalidate cached slots and dates when bookings change.
    Called after create/cancel/confirm to ensure fresh availability.
    """
    target_date = dt.date() if isinstance(dt, datetime) else dt
    cache.delete(f"available_slots:{service.id}:{target_date}")
    cache.delete(f"available_dates:{service.id}:{target_date.year}:{target_date.month}")


#  SLOT ALGORITHM 

def get_available_slots(service: Service, target_date: date_type) -> list:
    """
    Returns all available datetime slots for a service on a given date.

    Caching — cached per (service, date) for 60 seconds.
    Short TTL so new bookings appear quickly without stale data.
    Cache is on the public read path only — dashboard always queries fresh.
    Invalidated immediately when a booking is created or cancelled.
    """
    cache_key = f"available_slots:{service.id}:{target_date}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    slots = _compute_available_slots(service, target_date)
    cache.set(cache_key, slots, timeout=60)
    return slots


def _compute_available_slots(service: Service, target_date: date_type) -> list:
    """
    Raw slot computation — no caching. Called by get_available_slots()
    and also directly by the dashboard (which always needs fresh data).
    """
    avail = WeeklyAvailability.objects.filter(
        business=service.business,
        day_of_week=target_date.weekday(),
        is_active=True,
    ).first()

    if not avail:
        return []

    min_bookable = timezone.now() + timedelta(minutes=service.business.booking_lead_time)
    window_start = _combine(target_date, avail.start_time)
    window_end = _combine(target_date, avail.end_time)
    step = timedelta(minutes=service.duration_minutes)

    blocked = BlockedTime.objects.filter(
        business=service.business,
        start_datetime__lt=window_end,
        end_datetime__gt=window_start,
    )

    booked = list(
        Appointment.objects.filter(
            service=service,
            start_datetime__date=target_date,
        ).exclude(status=Appointment.Status.CANCELLED)
    )

    slots = []
    cursor = window_start
    while cursor + step <= window_end:
        slot_end = cursor + step
        if cursor < min_bookable:
            cursor += step
            continue
        if _overlaps_blocked(cursor, slot_end, blocked):
            cursor += step
            continue
        if _overlaps_daily_break(cursor, slot_end, service.business):
            cursor += step
            continue
        if _slot_is_available(cursor, slot_end, booked):
            slots.append(cursor)
        cursor += step

    return slots

# CALENDAR HIGHLIGHTING

def get_available_dates(service: Service, year: int, month: int) -> list[date_type]:
    """
    Returns all dates in the given month that have at least one available slot.
    Used to highlight bookable days on the calendar widget.

    Pre-fetches WeeklyAvailability, Appointments, and BlockedTimes
    once for the whole month instead of once per day.

    Caching — result is cached per (service, year, month) for 5 minutes.
    Cache is invalidated when bookings change within that month.
    """
    import calendar as cal_module

    cache_key = f"available_dates:{service.id}:{year}:{month}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    _, days_in_month = cal_module.monthrange(year, month)
    today = timezone.localdate()

    month_start = date_type(year, month, 1)
    month_end = date_type(year, month, days_in_month)

    # Single query for weekly availability
    availability_map = {
        a.day_of_week: a
        for a in WeeklyAvailability.objects.filter(
            business=service.business,
            is_active=True,
        )
    }

    # Single query for all appointments in the month
    booked_by_date: dict[date_type, list] = {}
    for appt in Appointment.objects.filter(
        service=service,
        start_datetime__date__gte=month_start,
        start_datetime__date__lte=month_end,
    ).exclude(status=Appointment.Status.CANCELLED):
        d = appt.start_datetime.date()
        booked_by_date.setdefault(d, []).append(appt)

    # Single query for all blocked times overlapping the month
    blocked = list(
        BlockedTime.objects.filter(
            business=service.business,
            start_datetime__date__lte=month_end,
            end_datetime__date__gte=month_start,
        )
    )

    min_bookable = timezone.now() + timedelta(minutes=service.business.booking_lead_time)
    step = timedelta(minutes=service.duration_minutes)

    available = []
    for day in range(1, days_in_month + 1):
        d = date_type(year, month, day)
        if d < today:
            continue

        avail = availability_map.get(d.weekday())
        if not avail:
            continue

        window_start = _combine(d, avail.start_time)
        window_end = _combine(d, avail.end_time)

        booked = booked_by_date.get(d, [])

        cursor = window_start
        found = False
        while cursor + step <= window_end:
            slot_end = cursor + step
            if cursor < min_bookable:
                cursor += step
                continue
            if _overlaps_blocked(cursor, slot_end, blocked):
                cursor += step
                continue
            if _overlaps_daily_break(cursor, slot_end, service.business):
                cursor += step
                continue
            if _slot_is_available(cursor, slot_end, booked):
                found = True
                break
            cursor += step

        if found:
            available.append(d)

    cache.set(cache_key, available, timeout=300)  # 5 min TTL
    return available


#  BOOKING LIFECYCLE 

@transaction.atomic
def create_booking(dto: CreateBookingDTO) -> Appointment:
    """
    Creates a pending appointment — slot is held but not confirmed until
    the customer verifies their email address.

    Locks the service row and re-checks availability inside the transaction
    so simultaneous submissions cannot take the same service slot.
    Raises ServiceError if the slot is gone.
    
    Invalidates slot cache after creating booking.
    """
    service = (
        Service.objects
        .select_for_update()
        .select_related("business")
        .get(id=dto.service_id)
    )
    end_dt = dto.start_datetime + timedelta(minutes=service.duration_minutes)

    available = _compute_available_slots(service, dto.start_datetime.date())  # Skip cache for atomicity
    if dto.start_datetime not in available:
        raise ServiceError("Sorry, that slot is no longer available. Please choose another time.")

    appointment = Appointment.objects.create(
        service=service,
        customer_name=dto.customer_name,
        customer_email=dto.customer_email,
        customer_phone=dto.customer_phone,
        notes=dto.notes,
        start_datetime=dto.start_datetime,
        end_datetime=end_dt,
        status=Appointment.Status.PENDING,
        email_verified=False,
    )

    logger.info(
        "Booking created: %s for %s @ %s (id=%s)",
        service.name, dto.customer_email, dto.start_datetime, appointment.id,
    )
    
    _invalidate_slot_cache(service, dto.start_datetime)
    return appointment


def confirm_booking(confirmation_token: str) -> Appointment:
    """
    Called when the customer clicks the email verify link.
    Marks email_verified=True and status=CONFIRMED.

    Idempotent — returns the appointment unchanged if already confirmed.
    Raises ServiceError if the token is invalid or the verification window expired.
    """
    try:
        appt = Appointment.objects.select_related(
            "service__business"
        ).get(confirmation_token=confirmation_token)
    except Appointment.DoesNotExist:
        raise ServiceError("Booking not found. The link may be invalid.")

    if appt.email_verified:
        return appt  # Already confirmed — idempotent

    if appt.is_expired:
        # Save cancellation in its own standalone update BEFORE raising —
        # if this were inside @transaction.atomic, the save would roll back
        # when the exception propagates, leaving a zombie pending booking.
        Appointment.objects.filter(pk=appt.pk).update(
            status=Appointment.Status.CANCELLED
        )
        logger.info("Expired booking cancelled: id=%s", appt.id)
        raise ServiceError("This verification link has expired. Please book again.")

    # Only the confirmation path needs to be atomic
    with transaction.atomic():
        appt.email_verified = True
        appt.status = Appointment.Status.CONFIRMED
        appt.save(update_fields=["email_verified", "status"])

    logger.info("Booking confirmed: id=%s, customer=%s", appt.id, appt.customer_email)
    return appt

@transaction.atomic
def cancel_booking(confirmation_token: str) -> Appointment:
    """
    Customer-initiated cancellation via their unique confirmation link.
    Enforces the business's cancellation notice window.

    Idempotent — returns the appointment unchanged if already cancelled.
    Raises ServiceError if cancellation is within the notice window.
    
    Invalidates slot cache after cancelling.
    """
    try:
        appt = Appointment.objects.select_related(
            "service__business"
        ).get(confirmation_token=confirmation_token)
    except Appointment.DoesNotExist:
        raise ServiceError("Booking not found.")

    if appt.status == Appointment.Status.CANCELLED:
        return appt  # Already cancelled — idempotent

    if not appt.can_cancel:
        notice = appt.service.business.cancellation_notice_hours
        raise ServiceError(
            f"Cancellations require at least {notice} hours notice. "
            "Please contact us directly if you need to cancel."
        )

    appt.status = Appointment.Status.CANCELLED
    appt.save(update_fields=["status"])

    logger.info("Booking cancelled by customer: id=%s", appt.id)
    
    _invalidate_slot_cache(appt.service, appt.start_datetime)
    return appt


#  CUSTOMER BOOKING LOOKUP 

def get_bookings_by_email(email: str) -> list[Appointment]:
    """
    Returns all non-cancelled appointments for an email address,
    ordered by most recent first. Used by simple list views.
    
    For paginated views, use get_bookings_by_email_qs() instead.
    """
    return list(
        get_bookings_by_email_qs(email)
    )


def get_bookings_by_email_qs(email: str):
    """
    Returns a QuerySet for pagination support.
    
    Use this in views that need to paginate customer bookings:
        qs = get_bookings_by_email_qs(email)
        paginator = Paginator(qs, 10)
        page = paginator.get_page(request.GET.get('page'))
    """
    return (
        Appointment.objects
        .select_related("service__business")
        .filter(customer_email__iexact=email)
        .exclude(status=Appointment.Status.CANCELLED)
        .order_by("-start_datetime")
    )


def get_booking_by_lookup_token(token: str) -> Appointment:
    """
    Fetches a booking by its magic-link lookup token.
    Raises ServiceError if not found — the view shows an error and redirects.
    """
    try:
        return Appointment.objects.select_related(
            "service__business"
        ).get(lookup_token=token)
    except Appointment.DoesNotExist:
        raise ServiceError("Invalid or expired booking link.")


#  EXPIRED BOOKING CLEANUP 

def expire_unverified_bookings() -> int:
    """
    Cancels pending bookings whose email verification window has lapsed.
    Uses bulk_update for efficiency — one query regardless of count.
    Cache invalidation is skipped here intentionally: expired slots
    were already invisible (pending = not confirmed), so no customer
    would have seen them as available. The 60s slot cache TTL handles
    the rest naturally.
    """
    expired_qs = Appointment.objects.filter(
        status=Appointment.Status.PENDING,
        email_verified=False,
        token_expires_at__lt=timezone.now(),
    )

    count = expired_qs.update(status=Appointment.Status.CANCELLED)

    if count:
        logger.info("Expired %d unverified booking(s).", count)
    return count

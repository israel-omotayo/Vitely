"""
bookings/views.py — public customer-facing views only.
All admin/dashboard views live in dashboard/views.py.
"""

import logging
from datetime import datetime

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from core.ratelimit import check_ratelimit, RateLimitError
from dashboard.models import BusinessProfile, Service
from .emails import (
    send_cancellation_email,
    send_confirmation_email,
    send_magic_link_email,
    send_new_booking_alert,
    send_verification_email,
)
from .forms import BookingForm, EmailLookupForm
from .models import Appointment
from . import services, schemas

logger = logging.getLogger(__name__)


#  HELPERS 

def _get_business():
    return BusinessProfile.objects.select_related("owner").first()


def _get_client_ip(request):
    """
    Returns the client's real IP address.
    In production behind a proxy (Render, Railway), reads X-Forwarded-For.
    In dev, reads REMOTE_ADDR directly.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


# HOME

def home(request):
    """
    Public landing page — /
    Redirects to /setup/ if no BusinessProfile exists yet (first deploy).
    """
    business = _get_business()
    if not business:
        return redirect("accounts:setup")

    services_qs = Service.objects.filter(business=business, is_active=True).order_by("name")[:3]
    return render(request, "bookings/home.html", {
        "business": business,
        "services": services_qs,
        'is_home': True,
    })


# SERVICES

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

PAGE_SIZE = 12

def services_view(request):
    """Service grid — /services/
    Shows all active services for the business. Each links to its booking page.
    """
    business = _get_business()
    services_qs = (
        Service.objects.filter(business=business, is_active=True).order_by("name")
        if business else Service.objects.none()
    )

    paginator = Paginator(services_qs, PAGE_SIZE)

    try:
        page = paginator.page(request.GET.get("page", 1))
    except (PageNotAnInteger, EmptyPage):
        page = paginator.page(1)

    return render(request, "bookings/services.html", {
        "services": page,
        "page_obj": page,
        "paginator": paginator,
        "business": business,
    })

# BOOK — calendar + slot picker

def book_service(request, slug):
    """
    Booking page for a specific service — /book/<slug>/
    Renders the month calendar with available dates highlighted.
    Year/month are read from GET params so the customer can paginate months.
    """
    import calendar as cal_module

    business = _get_business()
    service = get_object_or_404(Service, slug=slug, business=business, is_active=True)

    today = timezone.localdate()
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))

    MAX_MONTHS_AHEAD = 3 

    max_month = today.month + MAX_MONTHS_AHEAD
    max_year = today.year + (max_month - 1) // 12
    max_month = ((max_month - 1) % 12) + 1

    # Clamp: never before this month, never beyond the ceiling
    if (year, month) < (today.year, today.month):
        year, month = today.year, today.month
    elif (year, month) > (max_year, max_month):
        year, month = max_year, max_month

    available_dates = services.get_available_dates(service, year, month)

    cal = cal_module.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)

    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    prev_year, prev_month = (year - 1, 12) if month == 1  else (year, month - 1)
    can_go_prev = (prev_year, prev_month) >= (today.year, today.month)
    can_go_next = (next_year, next_month) <= (max_year, max_month) 

    return render(request, "bookings/book.html", {
        "service": service,
        "business": business,
        "weeks": weeks,
        "available_dates": available_dates,
        "year": year,
        "month": month,
        "month_name": cal_module.month_name[month],
        "today": today,
        "next_year": next_year,
        "next_month": next_month,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "can_go_prev": can_go_prev,
        "can_go_next": can_go_next, 
        "form": BookingForm(),
    })


# HTMX — slot pills

def htmx_slots(request, slug, date):
    """
    HTMX endpoint — returns slot pill partial for a given date — /book/<slug>/slots/<date>/
    Called when the customer taps a day on the calendar.
    """
    business = _get_business()
    service = get_object_or_404(Service, slug=slug, business=business, is_active=True)

    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return HttpResponse('<p class="text-sm text-danger">Invalid date.</p>')

    slots = services.get_available_slots(service, target_date)
    return render(request, "bookings/partials/slot_pills.html", {
        "slots": slots,
        "service": service,
        "date": target_date,
    })


# HTMX — inline booking form

def htmx_booking_form(request):
    """
    HTMX endpoint — returns the booking form partial for a chosen slot.
    Called when the customer taps a slot pill.
    start and service_id come from query params set by the slot pill template.
    """
    start_dt_str = request.GET.get("start")
    service_id = request.GET.get("service_id")

    if not start_dt_str or not service_id:
        logger.warning(f"Missing params: start={start_dt_str}, service_id={service_id}")
        return HttpResponse("")

    try:
        # Try parsing with timezone info first (ISO format)
        try:
            start_dt = datetime.fromisoformat(start_dt_str)
        except ValueError:
            # Fallback: parse naive datetime and make it timezone-aware
            start_dt = datetime.strptime(start_dt_str, "%Y-%m-%d %H:%M:%S")
            start_dt = timezone.make_aware(start_dt)
        
        service = Service.objects.get(id=service_id)
    except ValueError as e:
        logger.error(f"Failed to parse datetime: {start_dt_str} — {e}")
        return HttpResponse(
            '<p class="text-sm text-danger">Invalid booking time. Please try again.</p>',
            status=400
        )
    except Service.DoesNotExist:
        logger.error(f"Service not found: {service_id}")
        return HttpResponse(
            '<p class="text-sm text-danger">Service not found. Please try again.</p>',
            status=404
        )

    form = BookingForm(initial={"start_datetime": start_dt, "service_id": service_id})
    return render(request, "bookings/partials/booking_form.html", {
        "form": form,
        "service": service,
        "start_dt": start_dt,
    })


# BOOKING SUBMISSION

@require_POST
def confirm_booking_view(request, slug):
    """
    Handles the booking form POST — /book/<slug>/confirm/
    Rate limited email (10/day) to prevent abuse.

    On success: creates a PENDING appointment and sends a verification email.
    HTMX requests get partial responses; full-page requests get redirects.
    """
    business = _get_business()
    service = get_object_or_404(Service, slug=slug, business=business, is_active=True)

    form = BookingForm(request.POST)
    if not form.is_valid():
        if request.headers.get("HX-Request"):
            return render(request, "bookings/partials/booking_form.html", {
                "form": form, "service": service,
                "start_dt": form.data.get("start_datetime"),
            })
        messages.error(request, "Please correct the errors below.")
        return redirect("bookings:book_service", slug=slug)

    # Email rate limit — prevents one email from bulk-booking across IPs
    email = form.cleaned_data["customer_email"]
    try:
        check_ratelimit(f"book:email:{email}", limit=10, period=86400)
    except RateLimitError:
        if request.headers.get("HX-Request"):
            return HttpResponse(
                '<p class="text-sm font-medium text-danger">Maximum daily bookings reached for this email.</p>',
                status=429,
            )
        messages.error(request, "You've reached the daily booking limit for this email.")
        return redirect("bookings:book_service", slug=slug)

    try:
        dto = schemas.CreateBookingDTO(
            service_id=form.cleaned_data["service_id"],
            start_datetime=form.cleaned_data["start_datetime"],
            customer_name=form.cleaned_data["customer_name"],
            customer_email=email,
            customer_phone=form.cleaned_data.get("customer_phone", ""),
            notes=form.cleaned_data.get("notes", ""),
        )
        appointment = services.create_booking(dto)
        send_verification_email(appointment, request=request)

    except services.ServiceError as e:
        if request.headers.get("HX-Request"):
            return HttpResponse(
                f'<p class="text-sm font-medium text-danger">{e}</p>', status=400
            )
        messages.error(request, str(e))
        return redirect("bookings:book_service", slug=slug)

    if request.headers.get("HX-Request"):
        return render(request, "bookings/partials/booking_confirmation.html", {"email": email})

    return render(request, "bookings/booking_confirm.html", {"email": email})


# EMAIL VERIFICATION

def verify_booking(request, token):
    """
    Confirms a booking when the customer clicks the verification link — /verify/<token>/
    Sends the confirmation email and business alert on success.
    Redirects to booking detail so the customer can see their confirmed booking.
    """
    try:
        appointment = services.confirm_booking(str(token))
        send_confirmation_email(appointment, request=request)
        send_new_booking_alert(appointment, request=request)
    except services.ServiceError as e:
        messages.error(request, str(e))
        return redirect("bookings:services")

    return redirect("bookings:booking_detail", token=appointment.confirmation_token)


# BOOKING DETAIL

def booking_detail(request, token):
    """Booking confirmation page — /booking/<token>/"""
    appointment = get_object_or_404(
        Appointment.objects.select_related("service__business"),
        confirmation_token=token)
    return render(request, "bookings/booking_confirmation.html", {
        "appointment": appointment,
    })


# CUSTOMER CANCELLATION

@require_POST
def cancel_booking_view(request, token):
    """
    Customer cancels their own booking — POST /booking/<token>/cancel/
    The service enforces the cancellation notice window.
    Sends a cancellation email if successful.
    """
    try:
        appointment = services.cancel_booking(str(token))
        send_cancellation_email(appointment, request=request)
        messages.success(request, "Your booking has been cancelled.")
    except services.ServiceError as e:
        messages.error(request, str(e))

    return redirect("bookings:booking_detail", token=token)


# MY BOOKINGS — email lookup

@require_http_methods(["GET", "POST"])
def my_bookings(request):
    """
    Magic link lookup — /my-bookings/
    Customer enters their email; if bookings exist we send a link to view them.
    Always shows "check your inbox" regardless of whether the email was found —
    never reveal whether an email has bookings.
    Rate limited to 5 lookup attempts per IP per 10 minutes.
    """
    if request.method == "GET":
        return render(request, "bookings/my_bookings.html", {"form": EmailLookupForm()})

    form = EmailLookupForm(request.POST)
    if not form.is_valid():
        return render(request, "bookings/my_bookings.html", {"form": form})

    client_ip = _get_client_ip(request)
    try:
        check_ratelimit(f"lookup:ip:{client_ip}", limit=5, period=600)
    except RateLimitError:
        messages.error(request, "Too many lookup attempts. Please wait a few minutes.")
        return render(request, "bookings/my_bookings.html", {"form": form})

    dto = schemas.EmailLookupDTO(email=form.cleaned_data["email"])
    bookings = services.get_bookings_by_email(dto.email)
    if bookings:
        send_magic_link_email(dto.email, str(bookings[0].lookup_token), request=request)

    # Always show the same success message — silent no-op if email not found
    messages.success(
        request,
        "If bookings exist for that email, you'll receive a link to view them.",
    )
    return render(request, "bookings/my_bookings.html", {"form": EmailLookupForm()})


# BOOKING LOOKUP — magic link landing

BOOKINGS_PER_PAGE = 10

def booking_lookup(request, token):
    """
    Landing page for the magic link sent by my_bookings — /my-bookings/<token>/
    Fetches all bookings for the email on that anchor appointment, paginated.
    """
    try:
        anchor = services.get_booking_by_lookup_token(str(token))
    except services.ServiceError:
        messages.error(request, "This link is invalid or has expired.")
        return redirect("bookings:my_bookings")

    all_bookings_qs = Appointment.objects.filter(
        customer_email__iexact=anchor.customer_email
    ).select_related("service").order_by("-start_datetime")

    paginator = Paginator(all_bookings_qs, BOOKINGS_PER_PAGE)
    page_number = request.GET.get("page")
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    return render(request, "bookings/my_bookings.html", {
        "page_obj": page_obj,
        "appointments": page_obj.object_list,
        "customer_email": anchor.customer_email,
        "show_bookings": True,
    })

# CRON VIEWS
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

@csrf_exempt
@require_POST
def cron_expire_bookings(request):
    if request.headers.get("X-Cron-Secret") != settings.CRON_SECRET:
        return HttpResponse("Forbidden", status=403)
    from bookings.management.commands.expire_bookings import Command
    Command().handle()
    return HttpResponse("OK")

@csrf_exempt
@require_POST
def cron_send_reminders(request):
    if request.headers.get("X-Cron-Secret") != settings.CRON_SECRET:
        return HttpResponse("Forbidden", status=403)
    from bookings.management.commands.send_reminders import Command
    Command().handle()
    return HttpResponse("OK")

def privacy(request):
    return render(request, "privacy.html")

def terms(request):
    return render(request, "terms.html")
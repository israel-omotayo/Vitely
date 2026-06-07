"""

All views for the admin dashboard — owner and staff.
Mounted at /dashboard/ in vitely/urls.py.
Templates live in templates/dashboard/.

Pattern (same as accounts/views.py):
    1. Validate with a form
    2. Build a DTO from form.cleaned_data
    3. Call a service function
    4. Redirect or render
Views never touch the DB directly.
"""

import json
import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from bookings.models import Appointment
from bookings.services import ServiceError
from bookings.emails import send_cancellation_email

from .decorators import owner_required, staff_required
from .forms import (
    StaffInviteForm,
    ServiceForm,
    WeeklyAvailabilityForm,
    DailyBreakForm,
    BlockedTimeForm,
    AdminBookingForm,
    AppointmentFilterForm,
)
from .models import BusinessProfile, Service, WeeklyAvailability, BlockedTime, StaffInvite
from . import schemas, services
from django.db import models
from datetime import date as date_type


User = get_user_model()
logger = logging.getLogger(__name__)


def _get_business() -> BusinessProfile | None:
    return BusinessProfile.objects.select_related("owner").first()


#  HOME 

@staff_required
def home(request):
    business = _get_business()
    stats = services.get_dashboard_stats(business) if business else {}
    return render(request, "dashboard/home.html", {
        "stats": stats,
        "business": business,
    })

#  CALENDAR 

@staff_required
def calendar(request):
    business = _get_business()

    from django.utils import timezone
    from datetime import timedelta
    now = timezone.now()
    window_start = now - timedelta(days=365)
    window_end = now + timedelta(days=365)

    appts = Appointment.objects.select_related("service", "practitioner").filter(
        service__business=business,
        start_datetime__gte=window_start,
        start_datetime__lte=window_end,
    ).exclude(status=Appointment.Status.CANCELLED)


    events = [
        {
            "id": appt.id,
            "title": f"{appt.customer_name} — {appt.service.name}" + (
                f" with {appt.practitioner.get_full_name() or appt.practitioner.email or appt.practitioner.username}"
                if appt.practitioner_id else ""
            ),
            "start": appt.start_datetime.isoformat(),
            "end": appt.end_datetime.isoformat(),
            "color": appt.service.color,
            "url": f"/dashboard/appointments/{appt.id}/",
        }
        for appt in appts
    ]

    return render(request, "dashboard/calendar.html", {
        "events_json": json.dumps(events),
        "business": business,
        "window_start": window_start.date().isoformat(),
        "window_end": window_end.date().isoformat(), 
    })



#  APPOINTMENTS 

APPOINTMENTS_PER_PAGE = 10
BLOCKED_TIMES_PER_PAGE = 10

@staff_required
def appointments(request):
    business = _get_business()

    filter_form = AppointmentFilterForm(
        data=request.GET or None,
        status_choices=Appointment.Status.choices,
        service_choices=[
            (s.slug, s.name)
            for s in Service.objects.filter(business=business, is_active=True)
        ],
    )

    dto = schemas.AppointmentFilterDTO(
        status=request.GET.get("status", ""),
        service_slug=request.GET.get("service", ""),
        search=request.GET.get("q", ""),
        date_str=request.GET.get("date", ""),
    )

    # get_filtered_appointments now returns a queryset — safe to paginate
    appts_qs = services.get_filtered_appointments(
        business,
        status=dto.status,
        service_slug=dto.service_slug,
        search=dto.search,
        date_str=dto.date_str,
    )

    paginator = Paginator(appts_qs, APPOINTMENTS_PER_PAGE)
    page_number = request.GET.get("page")
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # Preserve active filters in pagination links
    query_params = request.GET.copy()
    query_params.pop("page", None)
    filter_querystring = query_params.urlencode()

    return render(request, "dashboard/appointments.html", {
        "page_obj": page_obj,
        "paginator": paginator,
        "filter_form": filter_form,
        "filter_querystring": filter_querystring,
        "total_count": paginator.count,
        "dto": dto,
    })


@staff_required
def appointment_detail(request, pk):
    business = _get_business()
    appt = get_object_or_404(Appointment, pk=pk, service__business=business)
    return render(request, "dashboard/appointment_detail.html", {
        "appointment": appt,
        "status_choices": Appointment.Status.choices,
    })


@staff_required
@require_POST
def update_appointment(request, pk):
    business = _get_business()
    get_object_or_404(Appointment, pk=pk, service__business=business)  # 404 guard

    try:
        dto  = schemas.AppointmentStatusUpdateDTO(
            appointment_id=pk,
            new_status=request.POST.get("status", ""),
        )
        appt = services.admin_update_appointment(dto)

        if dto.new_status == Appointment.Status.CANCELLED:
            send_cancellation_email(appt, request=request)
        messages.success(request, f"Marked as {appt.get_status_display()}.")

    except (ServiceError, ValueError) as e:
        messages.error(request, str(e))

    return redirect("dashboard:appointment_detail", pk=pk)


#  NEW BOOKING (admin creates on behalf of customer) 

@staff_required
def new_booking(request):
    business = _get_business()
    services_qs = Service.objects.filter(business=business, is_active=True)
    practitioners_qs = services.get_practitioners()

    if request.method == "POST":
        form = AdminBookingForm(request.POST, services_qs=services_qs, practitioners_qs=practitioners_qs)
        if form.is_valid():
            try:
                dto = schemas.AdminBookingDTO(
                    service_id=form.cleaned_data["service_id"],
                    start_datetime=form.cleaned_data["start_datetime"],
                    customer_name=form.cleaned_data["customer_name"],
                    customer_email=form.cleaned_data["customer_email"],
                    customer_phone=form.cleaned_data.get("customer_phone", ""),
                    notes=form.cleaned_data.get("notes", ""),
                    practitioner_id=form.cleaned_data.get("practitioner_id"),
                )
                appt = services.create_admin_booking(dto)
                messages.success(request, f"Booking created for {appt.customer_name}.")
                return redirect("dashboard:appointment_detail", pk=appt.id)
            except (ServiceError, ValueError) as e:
                messages.error(request, str(e))
    else:
        form = AdminBookingForm(services_qs=services_qs, practitioners_qs=practitioners_qs)

    return render(request, "dashboard/new_booking.html", {
        "form": form,
        "business": business,
    })


#  SERVICES 

@owner_required
def services_list(request):
    business = _get_business()
    return render(request, "dashboard/services.html", {
        "services": Service.objects.filter(business=business).prefetch_related("practitioners").order_by("name"),
        "form": ServiceForm(practitioners_qs=services.get_practitioners()),
    })


@owner_required
def service_create(request):
    business = _get_business()

    if request.method == "POST":
        practitioners_qs = services.get_practitioners()
        form = ServiceForm(request.POST, practitioners_qs=practitioners_qs)
        if form.is_valid():
            try:
                dto = schemas.ServiceDTO(
                    name=form.cleaned_data["name"],
                    description=form.cleaned_data.get("description", ""),
                    duration_minutes=form.cleaned_data["duration_minutes"],
                    price=float(form.cleaned_data["price"]),
                    color=form.cleaned_data["color"],
                    is_active=form.cleaned_data["is_active"],
                    practitioner_ids=[user.id for user in form.cleaned_data["practitioners"]],
                )
                svc = services.create_service(dto, business)
                messages.success(request, f"'{svc.name}' created.")
                return redirect("dashboard:services")
            except (ServiceError, ValueError) as e:
                messages.error(request, str(e))
    else:
        practitioners_qs = services.get_practitioners()
        form = ServiceForm(practitioners_qs=practitioners_qs)

    return render(request, "dashboard/services.html", {
        "form": form,
        "action": "create",
        "services": Service.objects.filter(business=business).prefetch_related("practitioners").order_by("name"),
    })


@owner_required
def service_edit(request, pk):
    business = _get_business()
    svc = get_object_or_404(Service, pk=pk, business=business)

    if request.method == "POST":
        practitioners_qs = services.get_practitioners()
        form = ServiceForm(request.POST, instance=svc, practitioners_qs=practitioners_qs)
        if form.is_valid():
            try:
                dto = schemas.ServiceDTO(
                    pk=pk,
                    name=form.cleaned_data["name"],
                    description=form.cleaned_data.get("description", ""),
                    duration_minutes=form.cleaned_data["duration_minutes"],
                    price=float(form.cleaned_data["price"]),
                    color=form.cleaned_data["color"],
                    is_active=form.cleaned_data["is_active"],
                    practitioner_ids=[user.id for user in form.cleaned_data["practitioners"]],
                )
                svc = services.update_service(dto, business)
                messages.success(request, f"'{svc.name}' updated.")
                return redirect("dashboard:services")
            except (ServiceError, ValueError) as e:
                messages.error(request, str(e))
    else:
        practitioners_qs = services.get_practitioners()
        form = ServiceForm(instance=svc, practitioners_qs=practitioners_qs)

    return render(request, "dashboard/services.html", {
        "form": form,
        "action": "edit",
        "editing": svc,
        "services": Service.objects.filter(business=business).prefetch_related("practitioners").order_by("name"),
    })


@owner_required
@require_POST
def service_toggle(request, pk):
    business = _get_business()
    try:
        svc = services.toggle_service(pk, business)
        state = "activated" if svc.is_active else "deactivated"
        messages.success(request, f"'{svc.name}' {state}.")
    except ServiceError as e:
        messages.error(request, str(e))
    return redirect("dashboard:services")


#  AVAILABILITY 

@owner_required
def availability(request):
    business = _get_business()
    schedule = WeeklyAvailability.objects.filter(business=business).order_by("day_of_week")

    if request.method == "POST":
        action = request.POST.get("action", "schedule")
        form = WeeklyAvailabilityForm(request.POST if action == "schedule" else None)
        daily_break_form = DailyBreakForm(
            request.POST if action == "daily_break" else None,
            instance=business,
        )

        if action == "daily_break" and daily_break_form.is_valid():
            try:
                dto = schemas.DailyBreakDTO(
                    start_time=daily_break_form.cleaned_data["break_start_time"],
                    end_time=daily_break_form.cleaned_data["break_end_time"],
                )
                services.update_daily_break(dto, business)
                messages.success(request, "Daily break updated.")
                return redirect("dashboard:availability")
            except (ServiceError, ValueError) as e:
                messages.error(request, str(e))

        elif action == "schedule" and form.is_valid():
            try:
                dto = schemas.AvailabilityDTO(
                    day_of_week=form.cleaned_data["day_of_week"],
                    start_time=form.cleaned_data["start_time"],
                    end_time=form.cleaned_data["end_time"],
                    is_active=form.cleaned_data["is_active"],
                )
                services.upsert_availability(dto, business)
                messages.success(request, "Schedule updated.")
                return redirect("dashboard:availability")
            except (ServiceError, ValueError) as e:
                messages.error(request, str(e))
    else:
        form = WeeklyAvailabilityForm()
        daily_break_form = DailyBreakForm(instance=business)

    return render(request, "dashboard/availability.html", {
        "schedule": schedule,
        "form": form,
        "daily_break_form": daily_break_form,
        "day_choices": WeeklyAvailability.DAY_CHOICES,
        "business": business,
    })


#  BLOCKED TIMES 

@owner_required
def blocked_times(request):
    business = _get_business()
    blocked_qs = BlockedTime.objects.select_related("practitioner").filter(business=business).order_by("start_datetime")

    paginator = Paginator(blocked_qs, BLOCKED_TIMES_PER_PAGE)
    page_number = request.GET.get("page")
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    blocked = list(page_obj.object_list)
    services.attach_block_conflicts(blocked, business)
    practitioners_qs = services.get_practitioners()

    if request.method == "POST":
        form = BlockedTimeForm(request.POST, practitioners_qs=practitioners_qs)
        if form.is_valid():
            try:
                dto = schemas.BlockedTimeDTO(
                    start_datetime=form.cleaned_data["start_datetime"],
                    end_datetime=form.cleaned_data["end_datetime"],
                    reason=form.cleaned_data.get("reason", ""),
                    practitioner_id=form.cleaned_data["practitioner"].id if form.cleaned_data.get("practitioner") else None,
                )
                services.add_blocked_time(dto, business)
                conflicts = services.get_block_conflicts(dto, business)
                conflict_count = conflicts.count()
                if conflict_count:
                    messages.warning(
                        request,
                        f"Blocked time added, but {conflict_count} existing booking(s) overlap. Review them below.",
                    )
                else:
                    messages.success(request, "Blocked time added.")
                return redirect("dashboard:blocked_times")
            except (ServiceError, ValueError) as e:
                messages.error(request, str(e))
    else:
        form = BlockedTimeForm(practitioners_qs=practitioners_qs)

    return render(request, "dashboard/blocked_times.html", {
        "blocked_times": blocked,
        "form": form,
        "page_obj": page_obj,
        "paginator": paginator,
        "total_count": paginator.count,
    })


@owner_required
@require_POST
def blocked_time_delete(request, pk):
    business = _get_business()
    try:
        services.delete_blocked_time(pk, business)
        messages.success(request, "Blocked time removed.")
    except ServiceError as e:
        messages.error(request, str(e))
    return redirect("dashboard:blocked_times")


#  STAFF 

@owner_required
def staff(request):
    if request.method == "POST":
        form = StaffInviteForm(request.POST)
        if form.is_valid():
            try:
                dto = schemas.StaffInviteDTO(
                    email=form.cleaned_data["email"],
                    invited_by_id=request.user.id,
                )
                site_url = request.build_absolute_uri("/").rstrip("/")
                services.send_staff_invite(dto, site_url)
                messages.success(request, f"Invite sent to {dto.email}.")
                return redirect("dashboard:staff")
            except (ServiceError, ValueError) as e:
                messages.error(request, str(e))
    else:
        form = StaffInviteForm()

    staff_users = User.objects.filter(
        userprofile__role="staff", is_active=True
    ).select_related("userprofile").order_by("email")
    pending_invites = StaffInvite.objects.filter(accepted=False).order_by("-created_at")

    return render(request, "dashboard/staff.html", {
        "form": form,
        "staff_users": staff_users,
        "pending_invites": pending_invites,
    })


@owner_required
@require_POST
def revoke_staff(request, pk):
    try:
        services.revoke_staff_access(pk, request.user)
        messages.success(request, "Staff access revoked.")
    except ServiceError as e:
        messages.error(request, str(e))
    return redirect("dashboard:staff")

from django.db.models.functions import TruncDate
from dateutil.relativedelta import relativedelta
import calendar as cal_module

@owner_required
def analytics(request):
    business = _get_business()

    # Month selector — defaults to current month
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year",  today.year))
        month = int(request.GET.get("month", today.month))
    except (ValueError, TypeError):
        year, month = today.year, today.month

    selected = date_type(year, month, 1)
    prev_month = selected - relativedelta(months=1)
    next_month = selected + relativedelta(months=1)
    can_go_next = selected < date_type(today.year, today.month, 1)

    _, days_in_selected = cal_module.monthrange(year, month)
    _, days_in_prev = cal_module.monthrange(prev_month.year, prev_month.month)

    def month_qs(y, m):
        return Appointment.objects.filter(
            service__business=business,
            start_datetime__year=y,
            start_datetime__month=m,
        )

    curr_qs = month_qs(year, month)
    prev_qs = month_qs(prev_month.year, prev_month.month)

    # KPI — total bookings (excluding cancelled)
    curr_bookings = curr_qs.exclude(status=Appointment.Status.CANCELLED).count()
    prev_bookings = prev_qs.exclude(status=Appointment.Status.CANCELLED).count()
    booking_change = _pct_change(prev_bookings, curr_bookings)

    # KPI — revenue (confirmed + completed only)
    from django.db.models import Sum
    def revenue(qs):
        r = qs.filter(
            status__in=[Appointment.Status.COMPLETED]
        ).aggregate(t=Sum("service__price"))["t"]
        return float(r or 0)

    curr_revenue = revenue(curr_qs)
    prev_revenue = revenue(prev_qs)
    revenue_change = _pct_change(prev_revenue, curr_revenue)

    # KPI — cancellation rate
    curr_total = curr_qs.count()
    curr_cancelled = curr_qs.filter(status=Appointment.Status.CANCELLED).count()
    cancel_rate = round((curr_cancelled / curr_total * 100), 1) if curr_total else 0

    # Frequency polygon data — bookings per day
    def daily_counts(qs, days_in_month):
        counts = {d: 0 for d in range(1, days_in_month + 1)}
        for row in (
            qs.exclude(status=Appointment.Status.CANCELLED)
            .annotate(day=TruncDate("start_datetime"))
            .values("day")
            .annotate(c=models.Count("id"))
        ):
            counts[row["day"].day] = row["c"]
        return list(counts.values())

    curr_daily = daily_counts(curr_qs, days_in_selected)
    prev_daily = daily_counts(prev_qs, days_in_prev)

    # Pad prev_daily to same length as curr_daily for chart alignment
    while len(prev_daily) < len(curr_daily):
        prev_daily.append(None)

    # Service breakdown
    service_stats = (
        curr_qs.exclude(status=Appointment.Status.CANCELLED)
        .values("service__name", "service__color")
        .annotate(
            count=models.Count("id"),
            revenue=Sum("service__price"),
        )
        .order_by("-count")
    )

    return render(request, "dashboard/analytics.html", {
        "selected": selected,
        "prev_month": prev_month,
        "next_month": next_month,
        "can_go_next": can_go_next,
        "curr_bookings": curr_bookings,
        "prev_bookings": prev_bookings,
        "booking_change": booking_change,
        "curr_revenue": curr_revenue,
        "prev_revenue": prev_revenue,
        "revenue_change": revenue_change,
        "cancel_rate": cancel_rate,
        "curr_daily": json.dumps(curr_daily),
        "prev_daily": json.dumps(prev_daily),
        "days_labels": json.dumps(list(range(1, days_in_selected + 1))),
        "curr_label": selected.strftime("%B %Y"),
        "prev_label": prev_month.strftime("%B %Y"),
        "service_stats": service_stats,
        "total_services": sum(s["count"] for s in service_stats),
    })


def _pct_change(prev, curr):
    if not prev:
        return None  # can't calculate — no previous data
    change = ((curr - prev) / prev) * 100
    return round(change, 1)

from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    # Home
    path("", views.home, name="home"),

    # Calendar
    path("calendar/", views.calendar, name="calendar"),

    # Appointments
    path("appointments/", views.appointments, name="appointments"),
    path("appointments/new/", views.new_booking, name="new_booking"),
    path("appointments/<int:pk>/", views.appointment_detail, name="appointment_detail"),
    path("appointments/<int:pk>/update/", views.update_appointment, name="update_appointment"),

    # Services
    path("services/", views.services_list, name="services"),
    path("services/create/", views.service_create, name="service_create"),
    path("services/<int:pk>/edit/", views.service_edit, name="service_edit"),
    path("services/<int:pk>/toggle/", views.service_toggle, name="service_toggle"),

    # Availability
    path("availability/", views.availability, name="availability"),

    # Blocked times
    path("blocked-times/", views.blocked_times, name="blocked_times"),
    path("blocked-times/<int:pk>/delete/", views.blocked_time_delete, name="blocked_time_delete"),

    # Staff
    path("staff/", views.staff, name="staff"),
    path("staff/invite/", views.staff, name="invite_staff"),
    path("staff/<int:pk>/revoke/", views.revoke_staff, name="revoke_staff"),

    # Analytics
    path("analytics/", views.analytics, name="analytics"),
]
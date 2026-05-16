from django.urls import path
from . import views

app_name = "bookings"

urlpatterns = [
    # Public pages
    path("", views.home, name="home"),
    path("book/", views.services_view, name="services"),
    path("book/<slug:slug>/", views.book_service, name="book_service"),
    path("my-bookings/", views.my_bookings, name="my_bookings"),
    path("my-bookings/<uuid:token>/", views.booking_lookup, name="booking_lookup"),

    # Booking lifecycle
    path("book/<slug:slug>/confirm/", views.confirm_booking_view, name="confirm_booking"),
    path("booking/verify/<uuid:token>/", views.verify_booking, name="verify_booking"),
    path("booking/<uuid:token>/", views.booking_detail, name="booking_detail"),
    path("booking/<uuid:token>/cancel/", views.cancel_booking_view, name="cancel_booking"),

    # HTMX endpoints
    path("htmx/slots/<slug:slug>/<str:date>/", views.htmx_slots, name="htmx_slots"),
    path("htmx/booking-form/", views.htmx_booking_form, name="htmx_booking_form"),

    # Cron endpoints (called by external scheduler, e.g. cron-job.org)
    path("cron/expire/", views.cron_expire_bookings, name="cron_expire"),
    path("cron/reminders/", views.cron_send_reminders, name="cron_reminders"),

    # Legal pages
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
]
from django.contrib import admin
from .models import Appointment

@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ["customer_name", "customer_email", "service", "start_datetime", "status", "email_verified"]
    list_filter = ["status", "service", "email_verified"]
    search_fields = ["customer_name", "customer_email"]


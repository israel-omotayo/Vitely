from django.contrib import admin
from .models import BusinessProfile, Service, WeeklyAvailability, BlockedTime, StaffInvite

# Register your models here.

@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "timezone", "booking_lead_time"]

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["name", "duration_minutes", "price", "is_active"]
    list_editable = ["is_active"]
    prepopulated_fields = {"slug": ("name",)}

@admin.register(WeeklyAvailability)
class WeeklyAvailabilityAdmin(admin.ModelAdmin):
    list_display = ["business", "day_of_week", "start_time", "end_time", "is_active"]

@admin.register(BlockedTime)
class BlockedTimeAdmin(admin.ModelAdmin):
    list_display = ["business", "start_datetime", "end_datetime", "reason"]

@admin.register(StaffInvite)
class StaffInviteAdmin(admin.ModelAdmin):
    list_display = ["email", "invited_by", "accepted", "expires_at"]

from django.db import models
from django.contrib.auth.models import User
import uuid
from django.utils.text import slugify

# Create your models here.

class BusinessProfile(models.Model):
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name="business")
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=100)
    description = models.TextField(blank=True)
    timezone = models.CharField(max_length=60, default="Africa/Lagos")
    booking_lead_time = models.IntegerField(default=60, help_text="Minutes before a slot can be booked")
    cancellation_notice_hours = models.IntegerField(default=24, help_text="Hours notice required to cancel")
    logo_url = models.URLField(max_length=500, blank=True, null=True)

    class Meta:
        verbose_name = "Business Profile"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Service(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="services")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    duration_minutes = models.IntegerField(default=60) 
    price = models.DecimalField(max_digits=10, decimal_places=2)
    capacity = models.IntegerField(default=1, help_text="Max concurrent bookings for this slot")
    color = models.CharField(max_length=7, default="#C17D5A", help_text="Hex colour for calendar display")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("business", "slug")
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.duration_minutes} min)"


class WeeklyAvailability(models.Model):
    DAY_CHOICES = [
        (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"),
        (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
    ]

    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="availability")
    day_of_week = models.IntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("business", "day_of_week")
        ordering = ["day_of_week"]
        verbose_name = "Weekly Availability"
        verbose_name_plural = "Weekly Availability"

    def __str__(self):
        return f"{self.get_day_of_week_display()} {self.start_time}–{self.end_time}"


class BlockedTime(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="blocked_times")
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["start_datetime"]

    def __str__(self):
        return f"Blocked: {self.start_datetime:%d %b %Y %H:%M} – {self.end_datetime:%H:%M} ({self.reason or 'No reason'})"

class StaffInvite(models.Model):
    """
    Represents a pending invitation for a staff member.

    Flow:
        1. Owner submits StaffInviteForm → send_staff_invite() creates this record
        2. Invite email sent with a link to /invite/<token>/
        3. Staff clicks link → accept_staff_invite() validates token,
           creates User + UserProfile(role='staff'), sets accepted=True

    Token is a UUID so it is unguessable and unique.
    expires_at is set to 48 hours from creation in services.py.
    Once accepted=True the token is permanently dead — cannot be reused.
    """

    email = models.EmailField()
    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sent_invites",
        # If the owner account is deleted, invites go with it
    )
    accepted = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Staff Invite"
        verbose_name_plural = "Staff Invites"
        ordering = ["-created_at"]

    def __str__(self):
        status = "accepted" if self.accepted else "pending"
        return f"Invite → {self.email} ({status})"

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone
        return timezone.now() > self.expires_at

    @property
    def is_valid(self) -> bool:
        """True only if not accepted AND not expired."""
        return not self.accepted and not self.is_expired
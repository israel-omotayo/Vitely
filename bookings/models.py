import uuid
from django.db import models
from django.utils import timezone
from datetime import timedelta
from dashboard.models import Service


class Appointment(models.Model):

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"
        NO_SHOW = "no_show", "No Show"

    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="appointments")

    # Customer details — guest booking, no account
    customer_name = models.CharField(max_length=200)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)

    # Timing
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()  # derived: start + service.duration_minutes

    # Status
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)

    # Tokens
    confirmation_token = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    lookup_token = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)

    # Email verification (slot hold)
    email_verified = models.BooleanField(default=False)
    token_expires_at = models.DateTimeField()  # 30 min after creation

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_datetime"]

    def save(self, *args, **kwargs):
        # Auto-set end_datetime from service duration
        if not self.end_datetime:
            self.end_datetime = self.start_datetime + timedelta(minutes=self.service.duration_minutes)
        # Auto-set token expiry if not set
        if not self.token_expires_at:
            self.token_expires_at = timezone.now() + timedelta(minutes=30)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return not self.email_verified and timezone.now() > self.token_expires_at

    @property
    def can_cancel(self):
        """Check if the customer is still within the cancellation notice window."""
        if self.status not in (self.Status.PENDING, self.Status.CONFIRMED):
            return False
        notice_hours = self.service.business.cancellation_notice_hours
        deadline = self.start_datetime - timedelta(hours=notice_hours)
        return timezone.now() < deadline

    def __str__(self):
        return f"{self.customer_name} — {self.service.name} @ {self.start_datetime:%d %b %Y %H:%M} [{self.status}]"


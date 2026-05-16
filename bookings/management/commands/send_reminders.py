"""
python manage.py send_reminders

Sends 24hr reminder emails to all confirmed appointments starting tomorrow.
Run daily via cron job feature.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from bookings.models import Appointment
from bookings.emails import send_reminder_email


class Command(BaseCommand):
    help = "Send 24-hour reminder emails for tomorrow's confirmed appointments."

    def handle(self, *args, **options):
        tomorrow = timezone.localdate() + timedelta(days=1)

        appointments = Appointment.objects.select_related(
            "service__business"
        ).filter(
            start_datetime__date=tomorrow,
            status=Appointment.Status.CONFIRMED,
            email_verified=True,
        )

        sent = 0
        for appt in appointments:
            send_reminder_email(appt)
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} reminder(s)."))
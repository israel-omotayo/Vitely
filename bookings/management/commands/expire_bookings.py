"""
python manage.py expire_bookings

Cancels unverified pending bookings whose 30-min hold window has passed.
Run every 5–10 minutes via cron.
"""

from django.core.management.base import BaseCommand
from bookings.services import expire_unverified_bookings


class Command(BaseCommand):
    help = "Cancel expired unverified pending bookings."

    def handle(self, *args, **options):
        count = expire_unverified_bookings()
        self.stdout.write(self.style.SUCCESS(f"Expired {count} booking(s)."))
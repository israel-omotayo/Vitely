import os
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Creates a superuser from env vars — safe to run on every deploy (idempotent)."

    def handle(self, *args, **kwargs):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        email    = os.getenv("SUPERUSER_EMAIL", "").strip()
        password = os.getenv("SUPERUSER_PASSWORD", "").strip()

        if not email or not password:
            self.stdout.write("SUPERUSER_EMAIL or SUPERUSER_PASSWORD not set — skipping.")
            return

        if User.objects.filter(username=email).exists():
            self.stdout.write(f"Superuser already exists ({email}) — skipping.")
            return

        User.objects.create_superuser(username=email, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Superuser created: {email}"))
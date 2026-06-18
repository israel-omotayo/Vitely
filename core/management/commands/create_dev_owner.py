from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = "Creates a dev owner for testing. DEBUG only."

    def handle(self, *args, **kwargs):
        if not settings.DEBUG:
            self.stderr.write("Not DEBUG. Refusing."); return

        from django.contrib.auth import get_user_model
        from dashboard.models import BusinessProfile
        User = get_user_model()
        EMAIL, PASS = "dev@vitely.local", "devpassword123"

        if not BusinessProfile.objects.exists():
            self.stderr.write("Run /accounts/setup/ first."); return

        if User.objects.filter(email=EMAIL).exists():
            self.stdout.write(f"✓  Already exists: {EMAIL} / {PASS}"); return

        user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASS, is_active=True)
        user.userprofile.role = "owner"
        user.userprofile.save(update_fields=["role"])
        self.stdout.write(self.style.SUCCESS(
            f"Dev owner ready!\n   Email: {EMAIL}\n   Pass:  {PASS}\n   Login: /accounts/login/"
        ))
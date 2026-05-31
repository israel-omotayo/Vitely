from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from bookings.models import Appointment
from dashboard.models import BusinessProfile, Service, WeeklyAvailability

User = get_user_model()


class DemoLoginTests(TestCase):
    def test_demo_login_seeds_owner_dashboard_data_and_sets_session_flag(self):
        response = self.client.post(reverse("accounts:demo_login"))

        self.assertRedirects(response, reverse("dashboard:home"))

        user = User.objects.get(email="demo@vitely.app")
        self.assertEqual(user.userprofile.role, "owner")
        self.assertFalse(user.has_usable_password())

        self.assertTrue(self.client.session["demo_mode"])
        self.assertEqual(BusinessProfile.objects.count(), 1)
        self.assertGreaterEqual(Service.objects.count(), 3)
        self.assertGreaterEqual(WeeklyAvailability.objects.count(), 6)
        self.assertGreaterEqual(Appointment.objects.count(), 3)

    def test_demo_login_is_post_only(self):
        response = self.client.get(reverse("accounts:demo_login"))

        self.assertEqual(response.status_code, 405)
        self.assertFalse(User.objects.filter(email="demo@vitely.app").exists())

    def test_demo_mode_blocks_dashboard_writes(self):
        self.client.post(reverse("accounts:demo_login"))
        service_count = Service.objects.count()

        response = self.client.post(
            reverse("dashboard:service_create"),
            {
                "name": "Demo Write Attempt",
                "description": "This should not be created in demo mode.",
                "duration_minutes": 30,
                "price": "50.00",
                "color": "#C17D5A",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("dashboard:home"))
        self.assertEqual(Service.objects.count(), service_count)
        self.assertFalse(Service.objects.filter(name="Demo Write Attempt").exists())

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from dashboard.models import BusinessProfile, BlockedTime, Service
from dashboard.schemas import BlockedTimeDTO
from dashboard.services import add_blocked_time

User = get_user_model()


class BlockedTimeNotificationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner@example.com",
            email="owner@example.com",
            password="testpass123",
        )
        self.owner.userprofile.role = "owner"
        self.owner.userprofile.save(update_fields=["role"])
        self.business = BusinessProfile.objects.create(
            owner=self.owner,
            name="Vitely Test",
            slug="vitely-test",
        )
        self.service = Service.objects.create(
            business=self.business,
            name="Consultation",
            slug="consultation",
            duration_minutes=60,
            price=50,
        )
        self.start = timezone.now() + timedelta(days=2)
        self.overlapping = Appointment.objects.create(
            service=self.service,
            customer_name="Ada",
            customer_email="ada@example.com",
            start_datetime=self.start,
            end_datetime=self.start + timedelta(hours=1),
            status=Appointment.Status.CONFIRMED,
            email_verified=True,
            token_expires_at=timezone.now() + timedelta(days=1),
        )
        self.unaffected = Appointment.objects.create(
            service=self.service,
            customer_name="Ben",
            customer_email="ben@example.com",
            start_datetime=self.start + timedelta(hours=3),
            end_datetime=self.start + timedelta(hours=4),
            status=Appointment.Status.CONFIRMED,
            email_verified=True,
            token_expires_at=timezone.now() + timedelta(days=1),
        )

    @patch("dashboard.services.send_blocked_time_conflict_email")
    def test_blocked_time_notifies_existing_overlapping_bookings(self, mock_send):
        dto = BlockedTimeDTO(
            start_datetime=self.start + timedelta(minutes=15),
            end_datetime=self.start + timedelta(minutes=45),
            reason="Training",
        )

        with self.captureOnCommitCallbacks(execute=True):
            add_blocked_time(dto, self.business)

        self.assertEqual(BlockedTime.objects.count(), 1)
        mock_send.assert_called_once_with(self.overlapping)

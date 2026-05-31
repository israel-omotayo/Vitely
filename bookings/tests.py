"""
Tests for the 5 highest-risk areas in Vitely:
  1. Slot generation — correct slots, blocked days, lead time, booked slots
  2. Double-booking prevention — atomic check inside create_booking
  3. Cache invalidation — slot cache cleared after create/cancel
  4. Cancellation notice window — ServiceError when too late to cancel
  5. Booking lifecycle — create → confirm → cancel flow

Run with:
    python manage.py test bookings --settings=vitely.settings.dev

All tests use Django's TestCase (wraps each test in a transaction that
rolls back after the test, so no test data bleeds into another test).
The test database is created fresh for the test run and destroyed after.
No fixtures needed — setUp() builds everything from scratch.
"""

from datetime import date, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Appointment
from bookings.schemas import CreateBookingDTO
from bookings.services import (
    ServiceError,
    _compute_available_slots,
    cancel_booking,
    confirm_booking,
    create_booking,
    expire_unverified_bookings,
    get_available_slots,
)
from dashboard.models import (
    BlockedTime,
    BusinessProfile,
    Service,
    WeeklyAvailability,
)

User = get_user_model()


# SHARED SETUP HELPERS

def make_business(booking_lead_time=0, cancellation_notice_hours=0):
    """Creates a minimal owner + business profile."""
    owner = User.objects.create_user(
        username="owner@vitely.test",
        email="owner@vitely.test",
        password="testpass123",
    )
    return BusinessProfile.objects.create(
        owner=owner,
        name="Test Spa",
        slug="test-spa",
        booking_lead_time=booking_lead_time,
        cancellation_notice_hours=cancellation_notice_hours,
    )


def make_service(business, duration_minutes=60, name="Massage"):
    return Service.objects.create(
        business=business,
        name=name,
        slug=name.lower().replace(" ", "-"),
        duration_minutes=duration_minutes,
        price=5000,
        is_active=True,
    )


def make_availability(business, day_of_week, start="09:00", end="17:00"):
    """day_of_week: 0=Monday … 6=Sunday"""
    h_s, m_s = map(int, start.split(":"))
    h_e, m_e = map(int, end.split(":"))
    return WeeklyAvailability.objects.create(
        business=business,
        day_of_week=day_of_week,
        start_time=time(h_s, m_s),
        end_time=time(h_e, m_e),
        is_active=True,
    )


def next_weekday(weekday: int) -> date:
    """Returns the next future date that falls on `weekday` (0=Mon, 6=Sun)."""
    today = timezone.localdate()
    days_ahead = (weekday - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


def make_dto(service, slot, name="Ada Obi", email="ada@test.com"):
    return CreateBookingDTO(
        service_id=service.id,
        start_datetime=slot,
        customer_name=name,
        customer_email=email,
        customer_phone="",
        notes="",
    )


# SLOT GENERATION

class SlotGenerationTests(TestCase):

    def setUp(self):
        self.business = make_business(booking_lead_time=0)
        self.service  = make_service(self.business, duration_minutes=60)
        # Monday availability: 09:00 – 12:00  →  3 slots: 09:00, 10:00, 11:00
        make_availability(self.business, day_of_week=0, start="09:00", end="12:00")
        self.monday = next_weekday(0)

    def test_correct_number_of_slots_generated(self):
        slots = _compute_available_slots(self.service, self.monday)
        # 09:00, 10:00, 11:00 — 3 slots in a 3-hour window with 60-min duration
        self.assertEqual(len(slots), 3)

    def test_slot_times_are_correct(self):
        slots = _compute_available_slots(self.service, self.monday)
        hours = [s.hour for s in slots]
        self.assertEqual(hours, [9, 10, 11])

    def test_no_slots_on_unavailable_day(self):
        # Tuesday has no availability
        tuesday = next_weekday(1)
        slots = _compute_available_slots(self.service, tuesday)
        self.assertEqual(slots, [])

    def test_no_slots_on_inactive_day(self):
        avail = WeeklyAvailability.objects.get(
            business=self.business, day_of_week=0
        )
        avail.is_active = False
        avail.save()
        slots = _compute_available_slots(self.service, self.monday)
        self.assertEqual(slots, [])

    def test_slots_respect_lead_time(self):
        """
        With a 24-hour lead time, no slots should be generated for today
        or any day within the next 24 hours.
        """
        self.business.booking_lead_time = 24 * 60  # 24 hours in minutes
        self.business.save()
        # next Monday is > 7 days away so lead time shouldn't affect it,
        # but tomorrow will be blocked if tomorrow is a Monday.
        # Test that a date within lead time returns empty slots.
        today = timezone.localdate()
        make_availability(self.business, day_of_week=today.weekday(),
                          start="09:00", end="17:00")
        slots = _compute_available_slots(self.service, today)
        # All slots are within the next 24 hours = within lead time = no slots
        self.assertEqual(slots, [])

    def test_slots_blocked_during_blocked_time(self):
        monday = self.monday
        window_start = timezone.make_aware(
            timezone.datetime(monday.year, monday.month, monday.day, 9, 0)
        )
        window_end = timezone.make_aware(
            timezone.datetime(monday.year, monday.month, monday.day, 11, 0)
        )
        BlockedTime.objects.create(
            business=self.business,
            start_datetime=window_start,
            end_datetime=window_end,
        )
        slots = _compute_available_slots(self.service, monday)
        # 09:00 and 10:00 are blocked; only 11:00 remains
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].hour, 11)

    def test_slots_blocked_during_daily_break(self):
        self.business.break_start_time = time(10, 0)
        self.business.break_end_time = time(11, 0)
        self.business.save()

        slots = _compute_available_slots(self.service, self.monday)
        hours = [s.hour for s in slots]

        self.assertEqual(hours, [9, 11])

    def test_30_min_service_generates_more_slots(self):
        svc = make_service(self.business, duration_minutes=30, name="Express")
        slots = _compute_available_slots(svc, self.monday)
        # 09:00–12:00 window with 30-min slots = 6 slots
        self.assertEqual(len(slots), 6)

    def test_booked_slots_are_not_shown(self):
        """A slot with an active booking should not appear in available slots."""
        slots = _compute_available_slots(self.service, self.monday)
        first_slot = slots[0]

        Appointment.objects.create(
            service=self.service,
            customer_name="Emeka Eze",
            customer_email="emeka@test.com",
            start_datetime=first_slot,
            end_datetime=first_slot + timedelta(hours=1),
            status=Appointment.Status.CONFIRMED,
            email_verified=True,
            token_expires_at=timezone.now() + timedelta(hours=1),
        )

        slots_after = _compute_available_slots(self.service, self.monday)
        self.assertNotIn(first_slot, slots_after)
        # Other slots should still be available
        self.assertEqual(len(slots_after), 2)

    def test_cancelled_booking_frees_slot(self):
        """A cancelled booking frees the slot back up."""
        slots = _compute_available_slots(self.service, self.monday)
        first_slot = slots[0]

        Appointment.objects.create(
            service=self.service,
            customer_name="Emeka Eze",
            customer_email="emeka@test.com",
            start_datetime=first_slot,
            end_datetime=first_slot + timedelta(hours=1),
            status=Appointment.Status.CANCELLED,   # ← cancelled
            email_verified=True,
            token_expires_at=timezone.now() + timedelta(hours=1),
        )

        slots_after = _compute_available_slots(self.service, self.monday)
        self.assertIn(first_slot, slots_after)
        self.assertEqual(len(slots_after), 3)


# DOUBLE-BOOKING PREVENTION

class DoubleBookingTests(TestCase):

    def setUp(self):
        self.business = make_business(booking_lead_time=0)
        self.service  = make_service(self.business, duration_minutes=60)
        make_availability(self.business, day_of_week=0, start="09:00", end="12:00")
        self.monday = next_weekday(0)
        slots = _compute_available_slots(self.service, self.monday)
        self.first_slot = slots[0]

    def test_second_booking_on_full_slot_raises_service_error(self):
        dto1 = make_dto(self.service, self.first_slot, name="Ada Obi",   email="ada@test.com")
        dto2 = make_dto(self.service, self.first_slot, name="Emeka Eze", email="emeka@test.com")

        create_booking(dto1)

        with self.assertRaises(ServiceError):
            create_booking(dto2)

    def test_booking_at_different_slot_succeeds(self):
        slots = _compute_available_slots(self.service, self.monday)
        dto1 = make_dto(self.service, slots[0], email="ada@test.com")
        dto2 = make_dto(self.service, slots[1], email="emeka@test.com")

        appt1 = create_booking(dto1)
        appt2 = create_booking(dto2)

        self.assertEqual(appt1.status, Appointment.Status.PENDING)
        self.assertEqual(appt2.status, Appointment.Status.PENDING)


# CACHE INVALIDATION

class CacheInvalidationTests(TestCase):
    """
    Uses Django's LocMemCache (default in tests).
    Verifies that create_booking and cancel_booking clear the right keys.
    """

    def setUp(self):
        self.business = make_business(booking_lead_time=0)
        self.service  = make_service(self.business, duration_minutes=60)
        make_availability(self.business, day_of_week=0, start="09:00", end="12:00")
        self.monday = next_weekday(0)
        self.slots  = _compute_available_slots(self.service, self.monday)
        self.slot   = self.slots[0]

    def test_create_booking_invalidates_slot_cache(self):
        from django.core.cache import cache

        # Prime the cache
        get_available_slots(self.service, self.monday)
        cache_key = f"available_slots:{self.service.id}:{self.monday}"
        self.assertIsNotNone(cache.get(cache_key))

        # Create a booking — should bust the cache
        dto = make_dto(self.service, self.slot)
        create_booking(dto)

        self.assertIsNone(cache.get(cache_key))

    def test_create_booking_invalidates_date_cache(self):
        from django.core.cache import cache
        from bookings.services import get_available_dates

        # Prime the date cache
        get_available_dates(self.service, self.monday.year, self.monday.month)
        date_key = f"available_dates:{self.service.id}:{self.monday.year}:{self.monday.month}"
        self.assertIsNotNone(cache.get(date_key))

        dto = make_dto(self.service, self.slot)
        create_booking(dto)

        self.assertIsNone(cache.get(date_key))

    def test_cancel_booking_invalidates_slot_cache(self):
        from django.core.cache import cache

        dto  = make_dto(self.service, self.slot)
        appt = create_booking(dto)

        # Confirm it so it can be cancelled
        appt.email_verified = True
        appt.status = Appointment.Status.CONFIRMED
        appt.save()

        # Prime the cache again
        get_available_slots(self.service, self.monday)
        cache_key = f"available_slots:{self.service.id}:{self.monday}"
        self.assertIsNotNone(cache.get(cache_key))

        cancel_booking(str(appt.confirmation_token))

        self.assertIsNone(cache.get(cache_key))


# CANCELLATION NOTICE WINDOW

class CancellationNoticeTests(TestCase):

    def setUp(self):
        # 24-hour notice window
        self.business = make_business(booking_lead_time=0, cancellation_notice_hours=24)
        self.service  = make_service(self.business)
        make_availability(self.business, day_of_week=0, start="09:00", end="17:00")
        self.monday = next_weekday(0)

    def _make_confirmed_appt(self, start_datetime):
        """Helper — creates a confirmed appointment at the given time."""
        return Appointment.objects.create(
            service=self.service,
            customer_name="Ada Obi",
            customer_email="ada@test.com",
            start_datetime=start_datetime,
            end_datetime=start_datetime + timedelta(hours=1),
            status=Appointment.Status.CONFIRMED,
            email_verified=True,
            token_expires_at=timezone.now() + timedelta(hours=1),
        )

    def test_cancel_outside_notice_window_succeeds(self):
        # Appointment is 48 hours away — well outside 24-hour notice window
        future = timezone.now() + timedelta(hours=48)
        appt = self._make_confirmed_appt(future)
        cancelled = cancel_booking(str(appt.confirmation_token))
        self.assertEqual(cancelled.status, Appointment.Status.CANCELLED)

    def test_cancel_inside_notice_window_raises_error(self):
        # Appointment is 6 hours away — inside 24-hour notice window
        soon = timezone.now() + timedelta(hours=6)
        appt = self._make_confirmed_appt(soon)
        with self.assertRaises(ServiceError):
            cancel_booking(str(appt.confirmation_token))

    def test_cancel_exactly_at_deadline_raises_error(self):
        # Appointment is exactly 24 hours away — at the boundary
        # can_cancel checks timezone.now() < deadline, so exactly at deadline = False
        at_deadline = timezone.now() + timedelta(hours=24)
        appt = self._make_confirmed_appt(at_deadline)
        with self.assertRaises(ServiceError):
            cancel_booking(str(appt.confirmation_token))

    def test_already_cancelled_is_idempotent(self):
        future = timezone.now() + timedelta(hours=48)
        appt = self._make_confirmed_appt(future)
        cancel_booking(str(appt.confirmation_token))
        # Calling again should not raise
        result = cancel_booking(str(appt.confirmation_token))
        self.assertEqual(result.status, Appointment.Status.CANCELLED)

    def test_cancel_with_zero_notice_hours_always_succeeds(self):
        self.business.cancellation_notice_hours = 0
        self.business.save()
        # Appointment is 5 minutes away
        soon = timezone.now() + timedelta(minutes=5)
        appt = self._make_confirmed_appt(soon)
        cancelled = cancel_booking(str(appt.confirmation_token))
        self.assertEqual(cancelled.status, Appointment.Status.CANCELLED)

    def test_invalid_token_raises_error(self):
        import uuid
        with self.assertRaises(ServiceError):
            cancel_booking(str(uuid.uuid4()))


# BOOKING LIFECYCLE

class BookingLifecycleTests(TestCase):

    def setUp(self):
        self.business = make_business(booking_lead_time=0, cancellation_notice_hours=0)
        self.service  = make_service(self.business)
        make_availability(self.business, day_of_week=0, start="09:00", end="12:00")
        self.monday = next_weekday(0)
        self.slot   = _compute_available_slots(self.service, self.monday)[0]

    def test_create_booking_is_pending_unverified(self):
        dto  = make_dto(self.service, self.slot)
        appt = create_booking(dto)

        self.assertEqual(appt.status, Appointment.Status.PENDING)
        self.assertFalse(appt.email_verified)
        self.assertIsNotNone(appt.confirmation_token)
        self.assertIsNotNone(appt.lookup_token)

    def test_create_booking_sets_end_datetime_correctly(self):
        dto  = make_dto(self.service, self.slot)
        appt = create_booking(dto)
        expected_end = self.slot + timedelta(minutes=self.service.duration_minutes)
        self.assertEqual(appt.end_datetime, expected_end)

    def test_confirm_booking_marks_verified_and_confirmed(self):
        dto  = make_dto(self.service, self.slot)
        appt = create_booking(dto)
        confirmed = confirm_booking(str(appt.confirmation_token))

        self.assertEqual(confirmed.status, Appointment.Status.CONFIRMED)
        self.assertTrue(confirmed.email_verified)

    def test_confirm_booking_is_idempotent(self):
        dto  = make_dto(self.service, self.slot)
        appt = create_booking(dto)
        confirm_booking(str(appt.confirmation_token))
        # Second confirm should not raise
        result = confirm_booking(str(appt.confirmation_token))
        self.assertEqual(result.status, Appointment.Status.CONFIRMED)

    def test_confirm_expired_booking_cancels_it(self):
        dto  = make_dto(self.service, self.slot)
        appt = create_booking(dto)

        # Force-expire the token
        appt.token_expires_at = timezone.now() - timedelta(minutes=1)
        appt.save()

        with self.assertRaises(ServiceError):
            confirm_booking(str(appt.confirmation_token))

        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.CANCELLED)

    def test_confirm_with_invalid_token_raises_error(self):
        import uuid
        with self.assertRaises(ServiceError):
            confirm_booking(str(uuid.uuid4()))

    def test_email_normalised_to_lowercase(self):
        dto  = make_dto(self.service, self.slot, email="Ada.OBI@Test.COM")
        appt = create_booking(dto)
        self.assertEqual(appt.customer_email, "ada.obi@test.com")

    def test_customer_name_stripped(self):
        dto  = make_dto(self.service, self.slot, name="  Ada Obi  ")
        appt = create_booking(dto)
        self.assertEqual(appt.customer_name, "Ada Obi")

    def test_missing_name_raises_value_error(self):
        with self.assertRaises(ValueError):
            CreateBookingDTO(
                service_id=self.service.id,
                start_datetime=self.slot,
                customer_name="",
                customer_email="ada@test.com",
            )

    def test_missing_email_raises_value_error(self):
        with self.assertRaises(ValueError):
            CreateBookingDTO(
                service_id=self.service.id,
                start_datetime=self.slot,
                customer_name="Ada Obi",
                customer_email="",
            )


# EXPIRED BOOKING CLEANUP

class ExpireBookingsTests(TestCase):

    def setUp(self):
        self.business = make_business(booking_lead_time=0)
        self.service  = make_service(self.business)
        make_availability(self.business, day_of_week=0, start="09:00", end="17:00")
        self.monday = next_weekday(0)
        self.slot   = _compute_available_slots(self.service, self.monday)[0]

    def _make_pending(self, expired=False):
        appt = Appointment.objects.create(
            service=self.service,
            customer_name="Test User",
            customer_email="test@test.com",
            start_datetime=self.slot,
            end_datetime=self.slot + timedelta(hours=1),
            status=Appointment.Status.PENDING,
            email_verified=False,
            token_expires_at=(
                timezone.now() - timedelta(minutes=1)  # already expired
                if expired else
                timezone.now() + timedelta(minutes=30)  # still valid
            ),
        )
        return appt

    def test_expired_pending_bookings_are_cancelled(self):
        self._make_pending(expired=True)
        count = expire_unverified_bookings()
        self.assertEqual(count, 1)

    def test_non_expired_pending_booking_not_cancelled(self):
        self._make_pending(expired=False)
        count = expire_unverified_bookings()
        self.assertEqual(count, 0)

    def test_confirmed_booking_not_expired(self):
        appt = self._make_pending(expired=True)
        appt.email_verified = True
        appt.status = Appointment.Status.CONFIRMED
        appt.save()
        count = expire_unverified_bookings()
        self.assertEqual(count, 0)

    def test_returns_correct_count(self):
        for _ in range(3):
            self._make_pending(expired=True)
        self._make_pending(expired=False)
        count = expire_unverified_bookings()
        self.assertEqual(count, 3)

    def test_already_cancelled_not_double_counted(self):
        appt = self._make_pending(expired=True)
        appt.status = Appointment.Status.CANCELLED
        appt.save()
        count = expire_unverified_bookings()
        self.assertEqual(count, 0)


# PUBLIC SUPPORT PAGES

class PublicSupportPageTests(TestCase):
    def test_help_centre_page_renders(self):
        response = self.client.get(reverse("bookings:help_centre"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Help Centre")
        self.assertContains(response, "omotayoisrael24@gmail.com")

    def test_cancellation_policy_page_renders(self):
        response = self.client.get(reverse("bookings:cancellation_policy"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cancellation Policy")
        self.assertContains(response, "24 hours")

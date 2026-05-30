from dataclasses import dataclass
from datetime import datetime

"""
Data Transfer Objects (DTOs) for the dashboard app.
DTOs carry validated form data from views into the service layer.
They normalise and do lightweight checks — no DB access, no business logic.
Heavy validation and all DB writes live in services.py.
"""


#  STAFF INVITE 
# Built from StaffInviteForm on /dashboard/staff/.
# invited_by_id comes from request.user in the view — never from the form.

@dataclass
class StaffInviteDTO:
    email: str
    invited_by_id: int

    def __post_init__(self):
        self.email = self.email.strip().lower()
        if not self.email:
            raise ValueError("Email is required.")
        if not self.invited_by_id:
            raise ValueError("Inviter is required.")


#  APPOINTMENT FILTER 
# Built from GET params on /dashboard/appointments/.
# All fields optional — empty string means no filter applied.

@dataclass
class AppointmentFilterDTO:
    status: str = ""
    service_slug: str = ""
    search: str = ""
    date_str: str = ""

    def __post_init__(self):
        self.status = self.status.strip()
        self.service_slug = self.service_slug.strip()
        self.search = self.search.strip()
        self.date_str = self.date_str.strip()


#  APPOINTMENT STATUS UPDATE 
# Built from POST on /dashboard/appointments/<pk>/update/.
# appointment_id comes from URL kwargs in the view — not from the form.

@dataclass
class AppointmentStatusUpdateDTO:
    appointment_id: int
    new_status: str

    def __post_init__(self):
        if not self.appointment_id:
            raise ValueError("Appointment ID is required.")
        if not self.new_status:
            raise ValueError("Status is required.")
        self.new_status = self.new_status.strip()


#  SERVICE 
# Built from ServiceForm on /dashboard/services/create/ and /edit/.
# business is set in the view from the BusinessProfile — never from the form.
# slug is excluded — auto-generated in Service.save().
# pk is None for create, an int for update.

@dataclass
class ServiceDTO:
    name: str
    duration_minutes: int
    price: float
    color: str
    is_active: bool
    description: str = ""
    pk: int = None           # None = create, int = update

    def __post_init__(self):
        self.name = self.name.strip()
        self.description = self.description.strip()
        if not self.name:
            raise ValueError("Service name is required.")
        if self.duration_minutes < 5:
            raise ValueError("Duration must be at least 5 minutes.")
        if float(self.price) < 0:
            raise ValueError("Price cannot be negative.")


#  WEEKLY AVAILABILITY 
# Built from WeeklyAvailabilityForm on /dashboard/availability/.
# business is set in the view.
# One row per day_of_week — the service upserts (create or update).

@dataclass
class AvailabilityDTO:
    day_of_week: int
    start_time: object    # datetime.time
    end_time: object      # datetime.time
    is_active: bool

    def __post_init__(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValueError("Close time must be after open time.")


@dataclass
class DailyBreakDTO:
    start_time: object = None
    end_time: object = None

    def __post_init__(self):
        if bool(self.start_time) != bool(self.end_time):
            raise ValueError("Enter both break start and end times, or leave both empty.")
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValueError("Break end must be after break start.")


#  BLOCKED TIME 
# Built from BlockedTimeForm on /dashboard/blocked-times/.
# business is set in the view.

@dataclass
class BlockedTimeDTO:
    start_datetime: datetime
    end_datetime: datetime
    reason: str = ""

    def __post_init__(self):
        self.reason = self.reason.strip()
        if self.start_datetime and self.end_datetime:
            if self.end_datetime <= self.start_datetime:
                raise ValueError("End must be after start.")


#  ADMIN BOOKING 
# Built from AdminBookingForm on /dashboard/appointments/new/.
# Admin-created bookings skip email verification — confirmed immediately.
# Reuses bookings.schemas.CreateBookingDTO for the actual service call.

@dataclass
class AdminBookingDTO:
    service_id: int
    start_datetime: datetime
    customer_name: str
    customer_email: str
    customer_phone: str = ""
    notes: str = ""

    def __post_init__(self):
        self.customer_name = self.customer_name.strip()
        self.customer_email = self.customer_email.strip().lower()
        self.customer_phone = self.customer_phone.strip()
        if not self.customer_name:
            raise ValueError("Customer name is required.")
        if not self.customer_email:
            raise ValueError("Customer email is required.")
        if not self.service_id:
            raise ValueError("Service is required.")
        if not self.start_datetime:
            raise ValueError("Date and time are required.")

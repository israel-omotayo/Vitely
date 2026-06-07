from dataclasses import dataclass
from datetime import datetime

"""
Data Transfer Objects (DTOs) for the bookings app.

DTOs are plain dataclasses that carry validated form data
from the view into the service layer. They do lightweight
structural checks in __post_init__ (types, required fields,
basic normalisation). They do NOT touch the database.

Heavy validation (slot availability, rate limiting) lives in
services.py. Business logic lives in services.py.
"""


# CREATE BOOKING
# Built from BookingForm on /book/<slug>/.
# Used by both the public booking flow and the dashboard new-booking view.
# service_id and start_datetime come from hidden fields populated by the
# slot picker — the view reads them from form.cleaned_data like the rest.

@dataclass
class CreateBookingDTO:
    service_id: int
    start_datetime: datetime
    customer_name: str
    customer_email: str
    customer_phone: str = ""
    notes: str = ""
    practitioner_id: int | None = None

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
            raise ValueError("Start time is required.")


# EMAIL LOOKUP
# Built from EmailLookupForm on /my-bookings/.
# The service receives dto.email as a plain string — the DTO exists
# to normalise and validate before it gets there.

@dataclass
class EmailLookupDTO:
    email: str

    def __post_init__(self):
        self.email = self.email.strip().lower()

        if not self.email:
            raise ValueError("Email is required.")
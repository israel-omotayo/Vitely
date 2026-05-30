from django import forms
from django.contrib.auth import get_user_model

from .models import BusinessProfile, Service, WeeklyAvailability, BlockedTime

User = get_user_model()


# STAFF INVITE
# Owner fills this on /dashboard/staff/ to send an invite email.
# Validates the email is not already an active account.

class StaffInviteForm(forms.Form):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            "placeholder": "staff@example.com",
            "autocomplete": "off",
        }),
        label="Staff Email Address",
    )

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if User.objects.filter(email__iexact=email, is_active=True).exists():
            raise forms.ValidationError(
                "An account with this email already exists."
            )
        return email


# SERVICE FORM 
# Owner creates or edits a service.
# business is NOT a field here — it's set in the view from the BusinessProfile.
# slug is excluded — auto-generated in Service.save().

class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = [
            "name",
            "description",
            "duration_minutes",
            "price",
            "color",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={
                "placeholder": "e.g. Deep Tissue Massage",
            }),
            "description": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Brief description of this service...",
            }),
            "duration_minutes": forms.NumberInput(attrs={
                "min": 5,
                "step": 5,
                "placeholder": "60",
            }),
            "price": forms.NumberInput(attrs={
                "min": 0,
                "step": 0.01,
                "placeholder": "0.00",
            }),
            "color": forms.TextInput(attrs={
                "type": "color",
                # Renders as a colour picker — browser native, no JS needed
            }),
            "is_active": forms.CheckboxInput(),
        }
        labels = {
            "duration_minutes": "Duration (minutes)",
            "color": "Calendar colour",
            "is_active": "Active (visible to customers)",
        }

    def clean_duration_minutes(self):
        val = self.cleaned_data.get("duration_minutes")
        if val is not None and val < 5:
            raise forms.ValidationError("Duration must be at least 5 minutes.")
        return val

    def clean_price(self):
        val = self.cleaned_data.get("price")
        if val is not None and val < 0:
            raise forms.ValidationError("Price cannot be negative.")
        return val


# WEEKLY AVAILABILITY FORM 
# Owner sets the recurring weekly schedule.
# business is set in the view. One row per day_of_week per business.

class WeeklyAvailabilityForm(forms.ModelForm):
    class Meta:
        model = WeeklyAvailability
        fields = ["day_of_week", "start_time", "end_time", "is_active"]
        widgets = {
            "day_of_week": forms.Select(attrs={}),
            "start_time": forms.TimeInput(
                attrs={"type": "time"},
                format="%H:%M",
            ),
            "end_time": forms.TimeInput(
                attrs={"type": "time"},
                format="%H:%M",
            ),
            "is_active": forms.CheckboxInput(),
        }
        labels = {
            "day_of_week": "Day",
            "start_time": "Opens at",
            "end_time": "Closes at",
            "is_active": "Open this day",
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start_time")
        end = cleaned_data.get("end_time")
        if start and end and end <= start:
            self.add_error("end_time", "Close time must be after open time.")
        return cleaned_data


class DailyBreakForm(forms.ModelForm):
    class Meta:
        model = BusinessProfile
        fields = ["break_start_time", "break_end_time"]
        widgets = {
            "break_start_time": forms.TimeInput(
                attrs={"type": "time"},
                format="%H:%M",
            ),
            "break_end_time": forms.TimeInput(
                attrs={"type": "time"},
                format="%H:%M",
            ),
        }
        labels = {
            "break_start_time": "Break starts",
            "break_end_time": "Break ends",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["break_start_time"].input_formats = ["%H:%M"]
        self.fields["break_end_time"].input_formats = ["%H:%M"]

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("break_start_time")
        end = cleaned_data.get("break_end_time")
        if bool(start) != bool(end):
            raise forms.ValidationError("Enter both break start and end times, or leave both empty.")
        if start and end and end <= start:
            self.add_error("break_end_time", "Break end must be after break start.")
        return cleaned_data


# BLOCKED TIME FORM 
# Owner blocks out a date range — holiday, leave, one-off closure.
# business is set in the view.

class BlockedTimeForm(forms.ModelForm):
    class Meta:
        model = BlockedTime
        fields = ["start_datetime", "end_datetime", "reason"]
        widgets = {
            "start_datetime": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "end_datetime": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "reason": forms.TextInput(attrs={
                "placeholder": "e.g. Public Holiday, Staff Training Day",
            }),
        }
        labels = {
            "start_datetime": "Block from",
            "end_datetime": "Block until",
            "reason": "Reason (optional)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # HTML datetime-local needs this exact input format
        self.fields["start_datetime"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["end_datetime"].input_formats = ["%Y-%m-%dT%H:%M"]

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start_datetime")
        end = cleaned_data.get("end_datetime")
        if start and end and end <= start:
            self.add_error("end_datetime", "End must be after start.")
        return cleaned_data


# ADMIN BOOKING FORM
# Staff creates a booking on behalf of a customer.
# Unlike the public BookingForm, this skips email verification —
# admin-created bookings are confirmed immediately.
# service choices are populated in the view from the business's active services.

class AdminBookingForm(forms.Form):
    service_id = forms.IntegerField(
        widget=forms.Select(),  # choices injected in view via field.widget.choices
        label="Service",
    )
    start_datetime = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M"],
        label="Date & Time",
    )
    customer_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Customer full name"}),
        label="Customer Name",
    )
    customer_email = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "customer@example.com"}),
        label="Customer Email",
    )
    customer_phone = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "+234 000 000 0000"}),
        label="Phone (optional)",
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Any notes about this booking...",
        }),
        label="Notes (optional)",
    )

    def __init__(self, *args, services_qs=None, **kwargs):
        super().__init__(*args, **kwargs)
        if services_qs is not None:
            # Build choices from the queryset: (id, "Name — 60 min — $85")
            self.fields["service_id"].widget.choices = [
                ("", "Select a service…")] + [
                (svc.id, f"{svc.name} — {svc.duration_minutes} min — ${svc.price}")
                for svc in services_qs]

    def clean_customer_email(self):
        return self.cleaned_data.get("customer_email", "").strip().lower()

    def clean_customer_name(self):
        return self.cleaned_data.get("customer_name", "").strip()


# APPOINTMENT FILTER FORM
# Used on /dashboard/appointments/ — all fields optional.
# Rendered as GET params, not POST — no CSRF needed.
# service choices are populated in the view.

class AppointmentFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Search name or email…"}),
        label="Search",
    )
    status = forms.ChoiceField(
        required=False,
        choices=[],  # injected in view from Appointment.Status.choices
        label="Status",
    )
    service = forms.ChoiceField(
        required=False,
        choices=[],  # injected in view from active services
        label="Service",
    )
    date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Date",
    )

    def __init__(self, *args, status_choices=None, service_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [("", "All statuses")] + (status_choices or [])
        self.fields["service"].choices = [("", "All services")] + (service_choices or [])

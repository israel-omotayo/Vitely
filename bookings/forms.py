from django import forms


class BookingForm(forms.Form):
    customer_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            "placeholder": "Full name",
        }),
    )
    customer_email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "placeholder": "Email address",
        }),
    )
    customer_phone = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Phone number (optional)",
        }),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "placeholder": "Any notes for us? (optional)",
            "rows": 3,
        }),
    )
    start_datetime = forms.DateTimeField(
        widget=forms.HiddenInput(),
    )
    service_id = forms.IntegerField(
        widget=forms.HiddenInput(),
    )


class EmailLookupForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "placeholder": "Enter your email address",
            "autofocus": True,
        }),
    )
from django import forms
from django.contrib.auth.forms import PasswordResetForm as DjangoPasswordResetForm
from django.contrib.auth.password_validation import validate_password
from django.template import loader

from core.utils import send_email_async



class LoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "Email address", "autofocus": True})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Password"})
    )


class OwnerSetupForm(forms.Form):
    business_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Serenity Wellness Clinic"})
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "your@email.com"})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Choose a strong password"})
    )

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password


class StaffPasswordSetForm(forms.Form):
    """
    Used anywhere a password needs to be SET with no old password required:
      - Staff invite acceptance (/accounts/invite/<token>/)
      - Password reset confirmation (/accounts/password/reset/<uid>/<token>/)

    Distinct from PasswordChangeForm which VERIFIES the current password first.
    """
    new_password = forms.CharField(
        label="New password",
        widget=forms.PasswordInput(attrs={"placeholder": "Choose a strong password"}),
    )
    confirm_password = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs={"placeholder": "Repeat your password"}),
    )

    def clean_new_password(self):
        password = self.cleaned_data["new_password"]
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password")
        p2 = cleaned.get("confirm_password")
        if p1 and p2 and p1 != p2:
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned


class PasswordChangeForm(forms.Form):
    """
    Used when a logged-in user wants to change their password.
    REQUIRES the current password — that's the whole difference from StaffPasswordSetForm.
    """
    current_password = forms.CharField(
        label="Current password",
        widget=forms.PasswordInput(attrs={"placeholder": "Your current password"}),
    )
    new_password = forms.CharField(
        label="New password",
        widget=forms.PasswordInput(attrs={"placeholder": "Choose a strong password"}),
    )
    confirm_password = forms.CharField(
        label="Confirm new password",
        widget=forms.PasswordInput(attrs={"placeholder": "Repeat your new password"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_password(self):
        password = self.cleaned_data["new_password"]
        validate_password(password, user=self.user)
        return password

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password")
        p2 = cleaned.get("confirm_password")
        if p1 and p2 and p1 != p2:
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned


class AsyncPasswordResetForm(DjangoPasswordResetForm):
    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        subject = loader.render_to_string(subject_template_name, context)
        subject = "".join(subject.splitlines())
        if html_email_template_name:
            html_content = loader.render_to_string(html_email_template_name, context)
        else:
            html_content = loader.render_to_string(email_template_name, context)

        send_email_async(
            to_email=to_email,
            subject=subject,
            html_content=html_content,
            context="password-reset",
        )

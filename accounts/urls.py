from django.urls import path, reverse_lazy
from . import views
from .forms import AsyncPasswordResetForm
from django.contrib.auth import views as auth_views

app_name = "accounts"

urlpatterns = [
    # One-time setup — closes itself after BusinessProfile exists
    path("setup/", views.setup_view, name="setup"),

    # Login / Logout
    path("login/", views.login_view, name="login"),
    path("demo-login/", views.demo_login_view, name="demo_login"),
    path("logout/", views.logout_view, name="logout"),

    # Password reset
    path("password/reset/",
        auth_views.PasswordResetView.as_view(
            form_class=AsyncPasswordResetForm,
            template_name="accounts/password_reset.html",
            email_template_name="accounts/emails/password_reset_email.txt",
            html_email_template_name="accounts/emails/password_reset_email.html",
            subject_template_name="accounts/emails/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset"),

    path("password/reset/sent/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html",
        ),
        name="password_reset_done"),

    path("password/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm"),

    path("password/reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html",
        ),
        name="password_reset_complete"),


    # Password change
    path("password/change/", views.password_change_view, name="password_change"),
    path("password/change/done/", views.password_change_done_view, name="password_change_done"),

    # Staff invite acceptance
    path("invite/<uuid:token>/", views.invite_accept_view, name="invite_accept"),
    path("invite/expired/", views.invite_expired_view, name="invite_expired"),
]

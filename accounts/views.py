import logging

from django.contrib import messages
from django.contrib.auth import login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from core.ratelimit import check_ratelimit, RateLimitError
from .forms import (
    LoginForm,
    OwnerSetupForm,
    StaffPasswordSetForm,
    PasswordChangeForm,
)
from . import services, schemas

logger = logging.getLogger(__name__)
User = get_user_model()


# HELPERS 

def get_ip(request):
    """
    Returns the client's real IP address.
    In production behind a proxy (Render, Railway), reads X-Forwarded-For.
    In dev, reads REMOTE_ADDR directly.
    """
    behind_proxy = bool(getattr(__import__('django.conf', fromlist=['settings']).settings,
        "SECURE_PROXY_SSL_HEADER", None))
    
    if behind_proxy:
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded_for:
            ips = [ip.strip() for ip in forwarded_for.split(",")]
            return ips[0]
    return request.META.get("REMOTE_ADDR", "")


def redirect_if_logged_in(view_func):
    """
    Decorator — redirects already-authenticated users to the dashboard.
    Use on login, setup, invite pages so authenticated users don't see them.
    """
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard:home")
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


# SETUP  

@require_http_methods(["GET", "POST"])
def setup_view(request):
    """
    One-time owner setup page — /setup/
    Creates the owner account + BusinessProfile on first visit.
    Permanently redirects to /login/ once setup is complete.
    Authenticated users are also redirected away — setup is done.
    """
    # If setup is already done, nobody should be here
    if services.is_setup_complete():
        return redirect("accounts:login")

    if request.method == "GET":
        return render(request, "accounts/setup.html", {"form": OwnerSetupForm()})

    form = OwnerSetupForm(request.POST)
    if not form.is_valid():
        return render(request, "accounts/setup.html", {"form": form})

    try:
        dto = schemas.OwnerSetupDTO(
            business_name=form.cleaned_data["business_name"],
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
        )
        services.create_owner(dto)
        messages.success(request, "Your Vitely account is ready. Please log in.")
        return redirect("accounts:login")

    except services.ServiceError as e:
        messages.error(request, str(e))
        return render(request, "accounts/setup.html", {"form": form})


# LOGIN

@redirect_if_logged_in
@require_http_methods(["GET", "POST"])
def login_view(request):
    """
    Email + password login for owner and staff — /login/
    On success, redirects to ?next= if safe, otherwise to dashboard.
    Rate limited to 10 failed attempts per IP per minute.
    """
    if request.method == "GET":
        return render(request, "accounts/login.html", {"form": LoginForm()})

    form = LoginForm(request.POST)
    ip = get_ip(request)
    ratelimit_key = f"login_fail_{ip}"

    # Rate limit check — blocks after 10 failures per minute
    try:
        check_ratelimit(ratelimit_key, limit=10, period=60)
    except RateLimitError as e:
        messages.error(request, str(e))
        return render(request, "accounts/login.html", {"form": form})

    if not form.is_valid():
        messages.error(request, "Please fill in both fields.")
        return render(request, "accounts/login.html", {"form": form})

    dto = schemas.LoginDTO(
        email=form.cleaned_data["email"],
        password=form.cleaned_data["password"],
    )
    user, status = services.login_user(request, dto)

    if status == "success":
        login(request, user)
        # Safe redirect — prevent open redirect attacks
        next_url = request.GET.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect("dashboard:home")

    if status == "inactive":
        messages.error(request, "Your account has been deactivated. Contact the owner.")
        return render(request, "accounts/login.html", {"form": form})

    # "invalid" — wrong email or password. Don't reveal which.
    messages.error(request, "Invalid email or password.")
    return render(request, "accounts/login.html", {"form": form})


# LOGOUT 

@login_required
@require_POST
def logout_view(request):
    """
    Logs out the current user — POST /logout/
    GET requests are rejected — logout must always be a deliberate POST
    to prevent CSRF-based logouts via a crafted link.
    """
    logout(request)
    return redirect("accounts:login")



@require_http_methods(["GET", "POST"])
def invite_accept_view(request, token):
    """
    Staff sets their password and creates their account — /invite/<token>/
    Token is validated in services.accept_staff_invite().
    Email is shown read-only in the template — pulled from the invite record.
    On success: account created, staff auto-logged in, redirected to dashboard.
    """
    from dashboard.models import StaffInvite

    # Fetch the invite — show expired page for any problem
    try:
        invite = StaffInvite.objects.get(token=token)
    except StaffInvite.DoesNotExist:
        return render(request, "accounts/invite_expired.html", status=404)

    if not invite.is_valid:
        return render(request, "accounts/invite_expired.html", status=410)

    if request.method == "GET":
        return render(request, "accounts/invite_accept.html",
            {"form": StaffPasswordSetForm(), 
            "invite": invite
        })

    form = StaffPasswordSetForm(request.POST)
    if not form.is_valid():
        return render(request, "accounts/invite_accept.html",
            {"form": form, 
            "invite": invite
        })
    try:
        password = form.cleaned_data["new_password"]
        user = services.accept_staff_invite(token, password)

        login(request, user, backend="accounts.backends.VerificationAwareBackend")
        messages.success(request, f"Welcome! Logged in as {user.email}.")
        return redirect("dashboard:home")
    except Exception as e:
        messages.error(request, str(e))
        return render(request, "accounts/invite_accept.html",
            {"form": form, 
            "invite": invite
        })

@require_GET
def invite_expired_view(request):
    return render(request, "accounts/invite_expired.html", status=410)

# PASSWORD CHANGE (logged in)

@login_required
@require_http_methods(["GET", "POST"])
def password_change_view(request):
    """
    Change password while logged in — /password-change/
    Requires current password. Does NOT log the user out after changing
    because services.change_password() calls update_session_auth_hash().
    """
    if request.method == "GET":
        return render(request, "accounts/password_change.html", {
            "form": PasswordChangeForm(user=request.user)
        })

    form = PasswordChangeForm(request.POST, user=request.user)
    if not form.is_valid():
        return render(request, "accounts/password_change.html", {"form": form})

    try:
        dto = schemas.PasswordChangeDTO(
            user_id=request.user.id,
            current_password=form.cleaned_data["current_password"],
            new_password=form.cleaned_data["new_password"],
            confirm_password=form.cleaned_data['confirm_password'],
        )
        services.change_password(request, dto)
        messages.success(request, "Password updated successfully.")
        return redirect("accounts:password_change_done")

    except services.ServiceError as e:
        messages.error(request, str(e))
        return render(request, "accounts/password_change.html", {"form": form})


@login_required
@require_GET
def password_change_done_view(request):
    """Simple confirmation page after a successful password change."""
    return render(request, "accounts/password_change_done.html")

def custom_400_handler(request, exception=None):
    return render(request, 'errors/400.html', status=400)

def custom_403_handler(request, exception=None):
    return render(request, 'errors/403.html', status=403)

def custom_404_handler(request, exception=None):
    return render(request, 'errors/404.html', status=404)

def custom_500_handler(request):
    return render(request, 'errors/500.html', status=500)

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils.http import url_has_allowed_host_and_scheme


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _block_demo_writes(request):
    if request.session.get("demo_mode") and request.method not in SAFE_METHODS:
        messages.info(request, "Demo mode is read-only. Sign in as the real owner to make changes.")
        referer = request.META.get("HTTP_REFERER", "")
        if referer and url_has_allowed_host_and_scheme(
            referer,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(referer)
        return redirect("dashboard:home")
    return None


def owner_required(view_func):
    """Restricts view to the business owner only."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        blocked = _block_demo_writes(request)
        if blocked:
            return blocked
        try:
            if request.user.userprofile.is_owner:
                return view_func(request, *args, **kwargs)
        except AttributeError:
            pass
        messages.error(request, "Owner access required.")
        return redirect("dashboard:home") 
    return wrapper


def staff_required(view_func):
    """Restricts view to any authenticated staff or owner."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        blocked = _block_demo_writes(request)
        if blocked:
            return blocked
        try:
            role = request.user.userprofile.role
            if role in ("owner", "staff"):
                return view_func(request, *args, **kwargs)
        except AttributeError:
            pass
        messages.error(request, "Staff access required.")
        return redirect("accounts:login")
    return wrapper

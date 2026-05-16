from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required


def owner_required(view_func):
    """Restricts view to the business owner only."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
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
        try:
            role = request.user.userprofile.role
            if role in ("owner", "staff"):
                return view_func(request, *args, **kwargs)
        except AttributeError:
            pass
        messages.error(request, "Staff access required.")
        return redirect("accounts:login")
    return wrapper
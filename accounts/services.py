import logging
from time import timezone

from django.contrib.auth import get_user_model, authenticate, update_session_auth_hash
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.db import transaction
from .schemas import (
    OwnerSetupDTO,
    LoginDTO,
    PasswordChangeDTO,
)

# bookings app is imported inline inside create_owner() to avoid
# circular imports at module load time.

User = get_user_model()
logger = logging.getLogger(__name__)

# Reuse Django's built-in token generator for password reset links.
# It signs the user's pk + password hash + timestamp so tokens
# automatically expire after PASSWORD_RESET_TIMEOUT (default 3 days).
password_reset_token_generator = PasswordResetTokenGenerator()


class ServiceError(Exception):
    """Raised for expected business-rule failures. Views catch this and
    show the message to the user."""
    pass


#  SETUP CHECK 

def is_setup_complete() -> bool:
    """
    Returns True if the BusinessProfile already exists.
    Used by setup_view to redirect away once the site is configured.
    Once this returns True, /setup/ is permanently closed.
    """
    from dashboard.models import BusinessProfile
    return BusinessProfile.objects.exists()


#   CREATE OWNER 

@transaction.atomic
def create_owner(dto: OwnerSetupDTO):
    """
    Creates the owner User + UserProfile(role='owner') + BusinessProfile.
    Called once from setup_view. setup_view guards against repeat calls
    by checking is_setup_complete() first, but we double-check here too.

    Sets username = email so Django's auth machinery works normally
    while the UI only ever shows the email field.
    """
    from dashboard.models import BusinessProfile

    if BusinessProfile.objects.exists():
        raise ServiceError("Setup has already been completed.")

    if User.objects.filter(email__iexact=dto.email).exists():
        raise ServiceError("An account with this email already exists.")

    # username = email keeps things simple — users never see or type a username
    user = User.objects.create_user(
        username=dto.email,
        email=dto.email,
        password=dto.password,
        is_active=True,
    )
    user.userprofile.role = "owner"
    user.userprofile.save(update_fields=["role"])

    BusinessProfile.objects.create(
        owner=user,
        name=dto.business_name,
        slug=_slugify_business_name(dto.business_name),
    )

    logger.info("Owner account created for %s", dto.email)
    return user


def _slugify_business_name(name: str) -> str:
    """e.g Converts 'Serenity Wellness Clinic' → 'serenity-wellness-clinic'."""
    from django.utils.text import slugify
    return slugify(name)


# LOGIN 

def login_user(request, dto: LoginDTO) -> tuple:
    """
    Authenticates by email using our custom EmailBackend in backends.py.
    Returns (user, status_string) so the view can decide what to do.

    Status values:
        "success"   → authenticated, redirect to dashboard
        "invalid"   → wrong email or password
        "inactive"  → account exists but is_active=False (shouldn't happen in normal Vitely flow, but guard anyway)

    Never reveals whether the email exists — both wrong-email and
    wrong-password return "invalid".
    """
    user = authenticate(request, email=dto.email, password=dto.password)

    if user is None:
        return None, "invalid"

    if not user.is_active:
        return user, "inactive"

    return user, "success"

#  ACCEPT STAFF INVITE
@transaction.atomic
def accept_staff_invite(token: str, password: str):
    """
    Validates the invite token, creates the staff account, sets their password.

    Accepts new_password as a plain string — the view passes
    form.cleaned_data["new_password"] directly after StaffPasswordSetForm validates it.

    Returns the new User so the view can auto-login them.
    """
    from dashboard.models import StaffInvite
    
    try:
        invite = StaffInvite.objects.get(token=token)
    except StaffInvite.DoesNotExist:
        raise ServiceError("This invite link is invalid.")

    if invite.accepted:
        raise ServiceError("This invite has already been used.")

    if invite.is_expired:
        raise ServiceError("This invite link has expired. Ask the owner to send a new one.")

    if User.objects.filter(email__iexact=invite.email, is_active=True).exists():
        raise ServiceError("An account with this email already exists.")

    user = User.objects.create_user(
        username=invite.email,
        email=invite.email,
        password=None, # don't set it via create_user — use set_password below
        is_active=True,
    )

    set_password(user, password)   # ← shared service

    # Signal auto-creates profile with role=staff
    user.userprofile.role = "staff"
    user.userprofile.save(update_fields=["role"])

    invite.accepted = True
    invite.save(update_fields=["accepted"])

    logger.info("Staff account created for %s via invite token", invite.email)
    return user

# SET PASSWORD

def set_password(user, password: str) -> None:
    """
    Sets a user's password without verifying the old one.

    Used for:
      - Staff invite acceptance — user has no password yet
      - Password reset confirm — user is locked out

    Never use this for a logged-in user changing their own password.
    Use change_password() for that — it verifies the current password first.
    """
    user.set_password(password)
    user.save(update_fields=["password"])
    logger.info("Password set for user_id=%s", user.id)

#   CHANGE PASSWORD (logged in) 

def change_password(request, dto: PasswordChangeDTO) -> None:
    """
    Verifies the current password then sets the new one.
    Calls update_session_auth_hash so the user is NOT logged out after changing.

    Raises ServiceError if the current password is wrong.
    """
    user = request.user
    if not user.check_password(dto.current_password):
        raise ServiceError("Your current password is incorrect.")

    user.set_password(dto.new_password)
    user.save()
    update_session_auth_hash(request, user)

    logger.info("Password changed for user_id=%s", user.id)

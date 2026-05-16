from dataclasses import dataclass

"""
Data Transfer Objects (DTOs) for the accounts app.

DTOs are plain dataclasses that carry validated form data
from the view into the service layer. They do lightweight
structural checks in __post_init__ (types, required fields,
basic normalisation). They do NOT touch the database.

Heavy validation (password strength, email uniqueness) lives
in forms.py. Business logic lives in services.py.
"""


# OWNER SETUP 
# Built from OwnerSetupForm on /setup/.
# Carries everything needed to create the owner account
# and BusinessProfile in one atomic operation.

@dataclass
class OwnerSetupDTO:
    business_name: str
    email: str
    password: str

    def __post_init__(self):
        self.business_name = self.business_name.strip()
        self.email = self.email.strip().lower()

        if not self.business_name:
            raise ValueError("Business name is required.")
        if not self.email:
            raise ValueError("Email is required.")
        if not self.password:
            raise ValueError("Password is required.")


# LOGIN 
# Built from LoginForm on /login/.
# Used by both owner and staff — role is checked after authentication.

@dataclass
class LoginDTO:
    email: str
    password: str

    def __post_init__(self):
        self.email = self.email.strip().lower()

        if not self.email:
            raise ValueError("Email is required.")
        if not self.password:
            raise ValueError("Password is required.")


# PASSWORD CHANGE 
# Built from PasswordChangeForm on /password-change/.
# current_password is verified in the service against user.check_password().
# user_id is set in the view from request.user — not from the form.

@dataclass
class PasswordChangeDTO:
    user_id: int
    current_password: str
    new_password: str
    confirm_password: str

    def __post_init__(self):
        if not self.current_password:
            raise ValueError("Current password is required.")
        if not self.new_password:
            raise ValueError("New password is required.")
        if not self.confirm_password:
            raise ValueError("Password confirmation is required")
        if self.current_password == self.new_password:
            raise ValueError("New password cannot be the same as the current password.")

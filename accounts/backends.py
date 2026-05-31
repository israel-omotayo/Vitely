from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()

class VerificationAwareBackend(ModelBackend):
    """
    Custom authentication backend that:
    1. Authenticates by EMAIL
    2. Returns unverified users (is_active=False) instead of rejecting them
    
    This allows the view to check is_active separately and show
    the verification page instead of a "login failed" message.
    """
    
    def authenticate(self, request, email=None, password=None):
        """Authenticate using email + password, returning unverified users."""
        if not email or not password:
            return None
        
        try:
            # Look up user by email (case-insensitive)
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Run the hasher once to prevent timing attacks
            User().set_password(password)
            return None
        
        # Check password (works for both active and inactive users)
        if user.check_password(password):
            return user
        
        return None

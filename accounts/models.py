from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


# USER PROFILE

class UserProfile(models.Model):
    """
    Extends Django's built-in User with Vitely-specific fields.

    Every User in Vitely has exactly one UserProfile.
    The post_save signal at the bottom auto-creates it whenever
    a new User is created, so you never need to manually call
    UserProfile.objects.create() outside of services.py.

    Role meanings:
        owner → full access including revenue, settings, staff management
        staff → can manage appointments and view services (read-only),
            cannot see revenue or touch any settings
    """

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        STAFF = "staff", "Staff"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="userprofile",
    )
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.STAFF,
        # Default is staff so accidental account creation never
        # grants owner privileges. create_owner() explicitly sets owner.
    )
    avatar_url = models.URLField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"{self.user.email} ({self.role})"

    @property
    def is_owner(self) -> bool:
        return self.role == self.Role.OWNER

    @property
    def is_staff_member(self) -> bool:
        """
        Named is_staff_member to avoid shadowing Django's built-in
        User.is_staff boolean which controls Django admin access.
        """
        return self.role == self.Role.STAFF


# Auto-create a UserProfile whenever a new User is saved for the first time.
# This means you can always safely call request.user.userprofile without
# worrying about a RelatedObjectDoesNotExist error.
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)

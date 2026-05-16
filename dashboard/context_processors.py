from .models import BusinessProfile

def business_context(request):
    """Injects the BusinessProfile into every template context."""
    try:
        business = BusinessProfile.objects.select_related("owner").first()
    except Exception:
        business = None
    return {"business": business}
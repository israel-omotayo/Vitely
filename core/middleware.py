from django.http import HttpResponsePermanentRedirect
from django.conf import settings


def add_security_headers(response):
    csp = getattr(settings, "CONTENT_SECURITY_POLICY", "")
    if csp:
        response.setdefault("Content-Security-Policy", csp)

    permissions_policy = getattr(settings, "PERMISSIONS_POLICY", "")
    if permissions_policy:
        response.setdefault("Permissions-Policy", permissions_policy)

    return response


class EnforceCustomDomainMiddleware:
    """
    Redirects any traffic hitting the Render domain to the primary custom domain.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().lower()
        # Check if the request is coming through the Render domain
        if 'onrender.com' in host:
            # Replace with your actual domain name
            custom_domain = getattr(settings, 'BASE_FRONTEND_URL', None)
            redirect_url = f"https://{custom_domain}{request.get_full_path()}"
            return add_security_headers(HttpResponsePermanentRedirect(redirect_url))

        return add_security_headers(self.get_response(request))

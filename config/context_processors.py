from django.conf import settings


def google_fonts(_request):
    """Expose only the server-controlled Google Fonts CSP opt-in to templates."""
    return {"csp_allow_google_fonts": settings.CSP_ALLOW_GOOGLE_FONTS}

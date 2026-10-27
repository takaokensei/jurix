from django.conf import settings


def google_fonts(_request):
    """Expose only the server-controlled Google Fonts CSP opt-in to templates."""
    return {"csp_allow_google_fonts": settings.CSP_ALLOW_GOOGLE_FONTS}


def archive_assistant(_request):
    """Expose whether the isolated, explicitly unreviewed archive assistant is enabled."""
    from src.apps.legislation.pilot_catalog import operational_pilot

    try:
        enabled = operational_pilot() is not None
    except (OSError, ValueError, KeyError, TypeError):
        enabled = False
    return {
        "operational_pilot_enabled": enabled,
        "archive_assistant_enabled": bool(
            getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False)
        )
    }

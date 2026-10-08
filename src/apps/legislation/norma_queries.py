"""Shared queryset rules for the product-facing normative catalogue."""

from django.db.models import Q

from .models import Norma


def consolidated_normas_for_product():
    """Return consolidated norms, excluding fixtures explicitly marked synthetic."""
    return Norma.objects.filter(status="consolidated").filter(
        ~Q(identity_json__synthetic_fixture=True)
        | Q(identity_json__synthetic_fixture__isnull=True)
    )

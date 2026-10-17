"""Shared queryset rules for the product-facing normative catalogue."""

from django.db.models import Q

from .models import Norma


def normas_for_product():
    """Return product-visible norms, excluding records explicitly marked synthetic."""
    return Norma.objects.filter(
        (~Q(identity_json__synthetic_fixture=True) | Q(identity_json__synthetic_fixture__isnull=True))
        & (~Q(identity_json__synthetic=True) | Q(identity_json__synthetic__isnull=True))
    ).exclude(ementa__istartswith="[QA SINTÉTICO")


def consolidated_normas_for_product():
    """Return consolidated norms, excluding fixtures explicitly marked synthetic."""
    return normas_for_product().filter(status="consolidated")

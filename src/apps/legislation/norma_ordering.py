"""Shared, database-portable ordering for municipal norms."""

from django.db.models import BigIntegerField, Case, F, IntegerField, Value, When
from django.db.models.functions import Cast


def order_normas_by_publication(queryset, *, descending=True):
    """Order by publication date, then year and a safe numeric number key.

    Only 1–18 digit identifiers are cast to BIGINT. Other legal identifiers
    remain valid and receive a deterministic lexical tie-break instead of
    risking a database cast error.
    """
    numeric_number = r"^\d{1,18}$"
    queryset = queryset.annotate(
        _numero_is_numeric=Case(
            When(numero__regex=numeric_number, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
        _numero_numeric=Case(
            When(numero__regex=numeric_number, then=Cast("numero", BigIntegerField())),
            default=Value(0),
            output_field=BigIntegerField(),
        ),
    )
    if descending:
        return queryset.order_by(
            F("data_publicacao").desc(nulls_last=True),
            "-ano",
            "-_numero_is_numeric",
            "-_numero_numeric",
            "-numero",
            "-pk",
        )
    return queryset.order_by(
        F("data_publicacao").asc(nulls_last=True),
        "ano",
        "-_numero_is_numeric",
        "_numero_numeric",
        "numero",
        "pk",
    )

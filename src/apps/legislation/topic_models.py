"""Non-authoritative thematic tags; never encode legal effect or validity."""

from django.contrib.auth.models import User
from django.db import models

from src.apps.core.models import TimeStampedModel


class Topic(TimeStampedModel):
    """Stable, curated topic vocabulary used to filter norms."""

    code = models.SlugField(max_length=64, unique=True)
    label = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True)
    active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["label", "code"]

    def __str__(self):
        return self.label


class NormaTopic(TimeStampedModel):
    """A versioned thematic association with explicit confidence/provenance."""

    class Origin(models.TextChoices):
        MANUAL = "manual", "Manual"
        RULE = "rule", "Regra"
        SEMANTIC = "semantic", "Semântica"

    class Status(models.TextChoices):
        CANDIDATE = "candidate", "Candidata"
        CONFIRMED = "confirmed", "Confirmada"

    norma = models.ForeignKey(
        "legislation.Norma", on_delete=models.CASCADE, related_name="topic_links"
    )
    topic = models.ForeignKey(Topic, on_delete=models.PROTECT, related_name="norm_links")
    origin = models.CharField(max_length=12, choices=Origin.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CANDIDATE)
    version = models.PositiveIntegerField(default=1)
    score = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    decided_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="norma_topic_decisions"
    )

    class Meta:
        ordering = ["topic__label", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["norma", "topic", "version"], name="unique_norma_topic_version"),
            models.CheckConstraint(
                condition=models.Q(score__isnull=True) | models.Q(score__gte=0, score__lte=1),
                name="norma_topic_score_0_1",
            ),
            models.CheckConstraint(
                condition=(models.Q(status="candidate") & models.Q(origin__in=["rule", "semantic"]))
                | (models.Q(status="confirmed") & models.Q(origin__in=["manual", "rule", "semantic"])),
                name="norma_topic_candidate_origin",
            ),
        ]

    def __str__(self):
        return f"{self.norma}: {self.topic} ({self.get_status_display()})"

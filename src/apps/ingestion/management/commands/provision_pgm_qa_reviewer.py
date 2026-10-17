"""Provision or disable the dedicated, non-superuser PGM browser-test account."""

from __future__ import annotations

import os
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

QA_REVIEWER_USERNAME = "jurix-pgm-smoke-reviewer"
QA_REVIEWER_EMAIL = "jurix-pgm-smoke-reviewer@invalid"


class Command(BaseCommand):
    help = "Provisiona ou desativa somente a conta sintética de browser QA da PGM."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default=QA_REVIEWER_USERNAME,
            help="Nome do revisor sintético temporário, restrito ao padrão QA permitido.",
        )
        parser.add_argument(
            "--disable",
            action="store_true",
            help="Desativa apenas a conta de teste marcada por este comando.",
        )
        parser.add_argument(
            "--include-pending-relations",
            action="store_true",
            help=(
                "Concede somente em QA as permissões necessárias para visualizar o grafo "
                "de relações candidatas ainda não revisadas."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if os.environ.get("JURIX_QA_ONLY") != "1":
            raise CommandError("Conta de teste só pode ser provisionada em QA isolado.")

        database = settings.DATABASES["default"]
        expected_name = "test_jurix_audit" if os.environ.get("PYTEST_CURRENT_TEST") else "jurix_audit"
        host_qa = all(
            str(database.get(key, "")) == expected
            for key, expected in {
                "NAME": expected_name,
                "USER": "jurix_audit",
                "HOST": "127.0.0.1",
                "PORT": "55432",
            }.items()
        )
        container_qa = (
            os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings_normative_container_qa"
            and all(
                str(database.get(key, "")) == expected
                for key, expected in {
                    "NAME": expected_name,
                    "USER": "jurix_audit",
                    "HOST": "db",
                    "PORT": "5432",
                }.items()
            )
        )
        if not (host_qa or container_qa):
            raise CommandError("Banco fora do perfil QA autorizado; nenhuma conta foi alterada.")

        User = get_user_model()
        username = options["username"]
        is_default_reviewer = username == QA_REVIEWER_USERNAME
        if not is_default_reviewer and not re.fullmatch(r"jurix-pgm-preview-[0-9a-f]{8}", username):
            raise CommandError("Username deve ser o revisor padrão ou jurix-pgm-preview-<8 hex>.")
        reviewer_email = QA_REVIEWER_EMAIL if is_default_reviewer else f"{username}@invalid"
        reviewer = User.objects.filter(username=username).first()
        if options["disable"]:
            if reviewer is None:
                self.stdout.write("Nenhuma conta sintética para desativar.")
                return
            if (
                reviewer.email != reviewer_email
                or reviewer.is_superuser
                or not reviewer.is_staff
            ):
                raise CommandError("Conta existente não corresponde ao perfil de teste; preservada.")
            reviewer.is_active = False
            reviewer.set_unusable_password()
            reviewer.save(update_fields=["is_active", "password"])
            self.stdout.write("Conta sintética de browser QA desativada.")
            return

        password = os.environ.get("JURIX_QA_REVIEWER_PASSWORD", "")
        if len(password) < 24:
            raise CommandError("Defina senha QA temporária com pelo menos 24 caracteres.")
        if reviewer is not None:
            raise CommandError("A conta de teste já existe; nenhuma credencial foi substituída.")

        reviewer = User.objects.create_user(
            username=username,
            email=reviewer_email,
            password=password,
            is_staff=True,
            is_superuser=False,
            is_active=True,
        )
        review_permission = Permission.objects.get(
            content_type__app_label="legislation",
            codename="view_documentonormativo",
        )
        reviewer.user_permissions.add(review_permission)
        if options["include_pending_relations"]:
            reviewer.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label="legislation",
                    codename="view_eventoalteracao",
                ),
                Permission.objects.get(
                    content_type__app_label="legislation",
                    codename="review_eventonormativocandidato",
                ),
            )
        self.stdout.write(
            "Conta sintética de revisão provisionada no QA com permissões limitadas; "
            "nenhuma fixture ou evidência jurídica foi criada."
        )

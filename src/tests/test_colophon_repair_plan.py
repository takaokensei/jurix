import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from src.apps.legislation.models import Dispositivo, Norma


@pytest.mark.django_db
def test_apply_requires_manifest_hash_and_backup_confirmation():
    norma = Norma.objects.create(
        tipo="Lei", numero="99301", ano=2026, texto_original="Art. 1º Texto oficial."
    )
    with pytest.raises(CommandError, match="exige --approved-manifest"):
        call_command("repair_legal_colophons", "--norma-id", str(norma.pk), "--apply")


@pytest.mark.django_db
def test_stale_manifest_aborts_before_writing(tmp_path):
    original = (
        "Art. 1º Objeto.\nArt. 2º Esta Lei entra em vigor na data de sua publicação. "
        "Sala das Sessões, em Natal, 20 de agosto de 2026. Publicada no Diário Oficial "
        "do Município em: 21/9/2026 Autoria: Câmara Municipal."
    )
    norma = Norma.objects.create(
        tipo="Lei", numero="99302", ano=2026, texto_original=original, status="segmented"
    )
    article = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="2º",
        texto=(
            "Esta Lei entra em vigor na data de sua publicação. Sala das Sessões, em Natal, "
            "20 de agosto de 2026. Publicada no Diário Oficial do Município em: 21/9/2026 "
            "Autoria: Câmara Municipal."
        ),
        ordem=2,
    )
    manifest_path = tmp_path / "approved.json"
    call_command(
        "repair_legal_colophons",
        "--norma-id",
        str(norma.pk),
        "--manifest-out",
        str(manifest_path),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    norma.texto_original += "\nArt. 3º Nova alteração posterior."
    norma.save(update_fields=["texto_original"])

    with pytest.raises(CommandError, match="stale"):
        call_command(
            "repair_legal_colophons",
            "--norma-id",
            str(norma.pk),
            "--apply",
            "--approved-manifest",
            str(manifest_path),
            "--expected-manifest-sha256",
            manifest["sha256"],
            "--backup-verified",
        )

    article.refresh_from_db()
    norma.refresh_from_db()
    assert "Sala das Sessões" in article.texto
    assert norma.data_publicacao is None


@pytest.mark.django_db
def test_manifest_hash_does_not_include_source_ocr_text():
    norma = Norma.objects.create(
        tipo="Lei",
        numero="99303",
        ano=2026,
        texto_original=(
            "Art. 1º Esta Lei entra em vigor na data de sua publicação. "
            "Sala das Sessões, em Natal, 20 de agosto de 2026. Publicada no Diário Oficial "
            "do Município em: 21/9/2026 Autoria: Câmara Municipal."
        ),
    )
    Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        texto="Esta Lei entra em vigor na data de sua publicação. Sala das Sessões, em Natal, "
        "20 de agosto de 2026. Publicada no Diário Oficial do Município em: 21/9/2026 "
        "Autoria: Câmara Municipal.",
        ordem=1,
    )
    from io import StringIO

    output = StringIO()
    call_command("repair_legal_colophons", "--norma-id", str(norma.pk), stdout=output)
    assert "Correção disponível" in output.getvalue()


@pytest.mark.django_db
def test_conflicting_publication_dates_allow_only_approved_article_cleanup(tmp_path):
    from datetime import date
    from io import StringIO

    original = (
        "Art. 1º Objeto.\nArt. 2º Esta Lei entra em vigor na data de sua publicação.\n"
        "Sala das Sessões, em Natal, 20 de agosto de 2026. Publicada no Diário Oficial "
        "do Município em: 22/9/2026. Autoria: Câmara Municipal."
    )
    norma = Norma.objects.create(
        tipo="Lei",
        numero="99304",
        ano=2026,
        texto_original=original,
        texto_consolidado=original,
        data_publicacao=date(2026, 9, 21),
        data_vigencia=date(2026, 9, 21),
        status="consolidated",
    )
    article = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="2º",
        texto=(
            "Esta Lei entra em vigor na data de sua publicação. Sala das Sessões, em Natal, "
            "20 de agosto de 2026. Publicada no Diário Oficial do Município em: 22/9/2026. "
            "Autoria: Câmara Municipal."
        ),
        ordem=2,
    )
    manifest_path = tmp_path / "conflicting-dates.json"
    call_command(
        "repair_legal_colophons",
        "--norma-id",
        str(norma.pk),
        "--manifest-out",
        str(manifest_path),
        stdout=StringIO(),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["entries"][0]["publication_date_divergence"] is True

    output = StringIO()
    call_command(
        "repair_legal_colophons",
        "--norma-id",
        str(norma.pk),
        "--apply",
        "--approved-manifest",
        str(manifest_path),
        "--expected-manifest-sha256",
        manifest["sha256"],
        "--backup-verified",
        stdout=output,
    )

    article.refresh_from_db()
    norma.refresh_from_db()
    assert article.texto == "Esta Lei entra em vigor na data de sua publicação."
    assert norma.data_publicacao == date(2026, 9, 21)
    assert norma.data_vigencia == date(2026, 9, 21)
    assert norma.needs_review is True
    assert "Datas SAPL/OCR divergentes preservadas sem alteração: 1" in output.getvalue()

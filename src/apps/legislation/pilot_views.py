"""QA pilot adapters; the reviewed dossier and approval rules remain separate."""

import re

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET

from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.pilot_catalog import operational_pilot
from src.processing.pilot_casefile import build_pilot_casefile, casefile_url, norm_label
from src.processing.pilot_corpus import DIGEST


def _load(request):
    try:
        corpus = operational_pilot(request.GET.get("revision") or None)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Http404("Revisão do piloto indisponível ou inválida.") from exc
    if corpus is None:
        raise Http404("Corpus experimental não habilitado nesta instância.")
    return corpus


@require_GET
def casefile_view(request):
    corpus = _load(request)
    if not request.GET.get("norma"):
        cases = []
        for source in corpus["sources"]:
            if source["source_role"] != "primary":
                continue
            key = source["norma_key"]
            count = sum(key in {event["source_norma_key"], event.get("target_norma_key")} for event in corpus.get("events", []))
            cases.append({"label": norm_label(key), "event_count": count, "url": casefile_url(key, corpus["corpus_revision"])})
        cases.sort(key=lambda row: (-row["event_count"], row["label"]))
        return render(request, "legislation/workspace/_pilot_index.html", {"cases": cases, "active_nav": "explore"})
    raw = request.GET.get("as_of", "")
    day = parse_date(raw) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else None
    if raw and (day is None or day > timezone.localdate()):
        return HttpResponse("Informe uma data válida que não esteja no futuro.", status=400)
    try:
        casefile = build_pilot_casefile(
            corpus, request.GET.get("norma", ""), paths=tuple(path for path in request.GET.getlist("dispositivo") if path),
            as_of=day, source_sha256=request.GET.get("edicao") or None,
        )
    except ValueError as exc:
        raise Http404(str(exc)) from exc
    response_format = request.GET.get("formato")
    if response_format == "json":
        return JsonResponse(casefile, json_dumps_params={"ensure_ascii": False}, headers={
            "Content-Disposition": f'attachment; filename="jurix-{casefile["casefile_id"][:12]}.json"',
        })
    if response_format == "markdown":
        from src.processing.pilot_casefile import render_pilot_casefile_markdown
        return HttpResponse(render_pilot_casefile_markdown(casefile), content_type="text/markdown; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="jurix-{casefile["casefile_id"][:12]}.md"',
        })
    query = request.GET.copy()
    query.pop("formato", None)
    return render(request, "legislation/workspace/normative_casefile.html", {
        "casefile": casefile, "pilot_casefile": True, "active_nav": "explore",
        "normative_graph_enabled": True, "export_query": query.urlencode(),
    })


@require_GET
def source_pdf_view(request, pdf_sha256):
    if not DIGEST.fullmatch(pdf_sha256):
        raise Http404("Identificador de fonte inválido.")
    corpus = _load(request)
    if not any(source["pdf_sha256"] == pdf_sha256 for source in corpus["sources"]):
        raise Http404("Fonte fora desta revisão.")
    document = DocumentoNormativo.objects.filter(content_sha256=pdf_sha256).order_by("created_at", "pk").first()
    if document is None:
        raise Http404("PDF desta fonte não está disponível.")
    return redirect(reverse("legislation:document_pdf", args=(document.public_id,)))

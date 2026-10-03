"""Read-only audit probes. No writes to the application database."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from django.test import Client, override_settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from src.apps.legislation.models import Norma, Dispositivo, EventoAlteracao
from src.processing.strict_grounding import evaluate_strict_grounding
from src.processing.rag_context_builder import build_relevant_context
from src.processing.adaptive_rag_service import AdaptiveRAGService
from src.processing.adaptive_retrieval import RetrievalOptions
from src.apps.legislation.api_limits import parse_question
from src.apps.legislation.api_search import _resolve_article_followup
from src.apps.legislation.serializers import serialize_dispositivo_source
from src.processing.temporal_scope import TemporalScope
from datetime import date

report = {}
report["corpus"] = {
    "normas": Norma.objects.count(),
    "dispositivos": Dispositivo.objects.count(),
    "eventos": EventoAlteracao.objects.count(),
    "eventos_validated": EventoAlteracao.objects.filter(validado=True).count(),
    "embedded_devices": Dispositivo.objects.exclude(embedding__isnull=True).count(),
    "normas_needs_review": Norma.objects.filter(needs_review=True).count(),
}
grounding_cases = [
    ("negation_inversion", "A lei exige autorização.", "A lei não exige autorização."),
    ("condition_omission", "O município pode conceder o benefício.", "O município pode conceder o benefício se houver dotação orçamentária."),
    ("number_relationship_swap", "O prazo é de 20 dias e a multa é de 10 reais.", "O prazo é de 10 dias e a multa é de 20 reais."),
]
report["grounding"] = {}
for name, answer, evidence in grounding_cases:
    r = evaluate_strict_grounding(answer, [{"text": evidence, "norma_ref": "Lei 1234/2025", "identifier": "Art. 1", "dispositivo_id": 1}], require_source_diversity=False)
    report["grounding"][name] = {"grounded": r["grounded"], "claims": r["claims"]}

norma = SimpleNamespace(tipo="Lei", numero="1234", ano=2025, ementa="")
device = SimpleNamespace(norma=norma, texto="Uma regra inicial. " * 100 + "SENTINELA_FORA_DO_PROMPT", get_full_identifier=lambda: "Art. 1")
row = {"dispositivo": device, "similarity_score": 0.8}
fake = SimpleNamespace(semantic_search=lambda *args, **kwargs: [row])
context, used = build_relevant_context(fake, "regra", max_tokens=40)
report["truncation"] = {
    "context_length": len(context),
    "evidence_length": len(used[0]["evidence_text"]),
    "sentinel_in_prompt": "SENTINELA" in context,
    "sentinel_in_grounding_evidence": "SENTINELA" in used[0]["evidence_text"],
}
service = AdaptiveRAGService()
query = "O que prevê o art. 7º da Lei nº 8206/2026?"
cited = service._find_cited_normas(query)
rows = service._retrieve_cited_norma_devices(cited, query, RetrievalOptions())
report["exact_article_retrieval"] = {
    "question": query,
    "candidates": [r["dispositivo"].get_full_identifier() for r in rows],
    "requested_article_exists": Dispositivo.objects.filter(norma__numero="8206", tipo="artigo", numero__startswith="7").exists(),
}
report["followup_rewrite"] = _resolve_article_followup("E o artigo 2, quem financia as atividades?", "O que prevê a Lei nº 8205/2026?")
report["followup_dotted_law"] = _resolve_article_followup("E o artigo 2?", "O que prevê a Lei nº 8.205/2026?")
try:
    parse_question("x" * 2001)
    report["question_2001"] = "accepted"
except ValueError:
    report["question_2001"] = "rejected"
report["attachment_full_text_serialization"] = serialize_dispositivo_source({"text": "preview", "full_text": "full document SENTINEL", "attachment": True})["full_text"]
report["unknown_date_in_explicit_scope"] = TemporalScope(published_from=date(2026, 1, 1), published_to=date(2026, 12, 31)).contains_publication(None)
report["render_queries"] = {}
with override_settings(ALLOWED_HOSTS=["testserver"]):
    client = Client()
    for route in ["/normas/", "/normas/3/", "/normas/3/tree/", "/normas/3/compare/", "/configuracoes/", "/colecoes/", "/historico/", "/pesquisa/"]:
        with CaptureQueriesContext(connection) as captured:
            response = client.get(route)
        report["render_queries"][route] = {"status": response.status_code, "queries": len(captured)}
print(json.dumps(report, ensure_ascii=True, indent=2))
Path(__file__).with_name("probe-results.json").write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")

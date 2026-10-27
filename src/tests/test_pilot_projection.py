from copy import deepcopy

from src.processing.pilot_events import evidence
from src.processing.pilot_projection import device_paths, project_pilot_device
from src.tests.test_pilot_events import source

KEY = "BR-RN-NATAL|lei|20|2020"


def base():
    text = "Art. 1º Regra anterior.\n§ 1º Filho anterior.\nArt. 2º Vizinho."
    first, neighbor = text.index("§"), text.index("Art. 2")
    result = source(KEY, text, devices=[
        {"type": "artigo", "number": "1º", "device_key": "a1", "parent_key": None, "start": 0, "end": first},
        {"type": "paragrafo", "number": "1º", "device_key": "p1", "parent_key": "a1", "start": first, "end": neighbor},
        {"type": "artigo", "number": "2º", "device_key": "a2", "parent_key": None, "start": neighbor, "end": len(text)},
    ])
    result["base_valid_from"] = "2020-01-01"
    return result


def event(value="Art. 1º Regra nova.\n§ 1º Filho novo.", *, target="art:1", action="ALTERA", day="2025-01-10", identifier="e1"):
    modifier = source("BR-RN-NATAL|lei|30|2025", value, devices=[
        {"type": "artigo", "number": "1", "device_key": "a1", "parent_key": None, "start": 0, "end": value.index("§") if "§" in value else len(value)},
        *([{"type": "paragrafo", "number": "1", "device_key": "p1", "parent_key": "a1", "start": value.index("§"), "end": len(value)}] if "§" in value else []),
    ])
    return modifier, {
        "event_id": identifier, "action": action, "target_norma_key": KEY, "target_device_path": target,
        "source_norma_key": modifier["norma_key"], "source_article": "9",
        "resolution": "resolved", "new_text": None if action == "REVOGA" else value,
        "evidence": evidence(modifier, 0, len(value)),
        "temporal": {"effective_on": day, "publication_on": day, "status": "documentary_derived" if day else "unknown_date"},
    }


def corpus(*items, original=None):
    return {"corpus_revision": "r1", "sources": [original or base(), *(item[0] for item in items)], "events": [item[1] for item in items]}


def test_effect_boundaries_and_identity_are_deterministic_without_mutation():
    c = corpus(event())
    snapshot = deepcopy(c)
    before = project_pilot_device(c, KEY, "art:1", as_of="2025-01-09")
    at = project_pilot_device(c, KEY, "art:1", as_of="2025-01-10")
    after = project_pilot_device(c, KEY, "art:1", as_of="2025-01-11")
    assert before["after"] == before["before"]
    assert before["interval"]["end"] == "2025-01-10"
    assert at["after"] == after["after"] == c["events"][0]["new_text"]
    assert at["after"].count("Filho novo") == 1
    assert c == snapshot
    assert at == project_pilot_device(c, KEY, "art:1", as_of="2025-01-10")


def test_effect_order_not_event_id_or_publication_number():
    early = event("Art. 1º Primeira.", day="2025-01-10", identifier="z")
    late = event("Art. 1º Segunda.", day="2025-01-20", identifier="a")
    result = project_pilot_device(corpus(late, early), KEY, "art:1", as_of="2025-02-01")
    assert result["after"] == "Art. 1º Segunda."
    assert result["applied_events"] == ["z", "a"]


def test_partial_repeal_never_blanks_parent_or_neighbor():
    c = corpus(event("Fica revogado o § 1º.", target="art:1/par:1", action="REVOGA"))
    parent = project_pilot_device(c, KEY, "art:1", as_of="2025-01-10")
    child = project_pilot_device(c, KEY, "art:1/par:1", as_of="2025-01-10")
    neighbor = project_pilot_device(c, KEY, "art:2", as_of="2025-01-10")
    assert parent["after"] == "Art. 1º Regra anterior.\n"
    assert parent["legal_status"] == "partially_revoked_in_scope"
    assert child["after"] == "" and child["legal_status"] == "revoked_in_scope"
    assert neighbor["before"] == neighbor["after"] and not neighbor["events"]


def test_parent_replacement_supplies_its_child_once():
    result = project_pilot_device(corpus(event()), KEY, "art:1/par:1")
    assert result["after"] == "§ 1º Filho novo."
    assert "Regra nova" not in result["after"]


def test_unknown_date_is_documentary_comparison_and_not_a_dated_version():
    c = corpus(event(day=None))
    documentary = project_pilot_device(c, KEY, "art:1")
    dated = project_pilot_device(c, KEY, "art:1", as_of="2026-01-01")
    assert documentary["status"] == dated["status"] == "unknown_date"
    assert documentary["after"] == c["events"][0]["new_text"]
    assert dated["after"] is None and not dated["applied_events"]


def test_material_same_day_conflict_has_no_hash_tiebreaker():
    c = corpus(event("Art. 1º A.", identifier="a"), event("Art. 1º B.", identifier="b"))
    result = project_pilot_device(c, KEY, "art:1", as_of="2025-01-10")
    assert result["status"] == "conflict" and result["after"] is None
    assert set(result["conflicts"]) == {"a", "b"}
    assert not result["applied_events"]


def test_compilation_cutoff_and_incorporation_are_not_silently_assumed():
    original = base()
    original.update(edition_kind="compilation", edition_year=2025)
    c = corpus(event(), original=original)
    assert project_pilot_device(c, KEY, "art:1", as_of="2024-12-31")["status"] == "out_of_coverage"
    ambiguous = project_pilot_device(c, KEY, "art:1", as_of="2026-01-01")
    assert ambiguous["status"] == "partial" and not ambiguous["applied_events"]
    original["incorporated_event_ids"] = ["e1"]
    assert not project_pilot_device(c, KEY, "art:1", as_of="2026-01-01")["applied_events"]


def test_whole_repeal_and_later_repeal_of_revoker_do_not_resurrect():
    repeal = event("Revoga a lei.", action="REVOGA", target=None)
    later = event("Art. 1º Restaurada por inferência.", day="2025-02-01", identifier="later")
    c = corpus(repeal, later)
    c["events"].append({**repeal[1], "event_id": "revoker-repeal", "target_norma_key": "BR-RN-NATAL|lei|30|2025"})
    result = project_pilot_device(c, KEY, "art:1", as_of="2026-01-01")
    assert result["legal_status"] == "revoked_in_scope"
    assert result["after"] is None and result["pending_events"] == ["later"]


def test_ended_event_does_not_restore_previous_wording():
    item = event()
    item[1]["temporal"]["end_on"] = "2025-02-01"
    result = project_pilot_device(corpus(item), KEY, "art:1", as_of="2025-02-01")
    assert result["status"] == "partial" and result["after"] is None


def test_explicit_veto_is_preserved_not_overwritten():
    original = base()
    original["devices"][0]["marker"] = "vetado"
    result = project_pilot_device(corpus(event(), original=original), KEY, "art:1", as_of="2026-01-01")
    assert result["legal_status"] == "base_revoked_or_vetoed"
    assert not result["applied_events"]


def test_duplicate_event_is_idempotent_and_missing_target_remains_missing():
    c = corpus(event())
    c["events"].append(deepcopy(c["events"][0]))
    result = project_pilot_device(c, KEY, "art:1")
    assert result["applied_events"] == ["e1"]
    assert project_pilot_device(c, KEY, "art:99")["status"] == "out_of_coverage"
    assert device_paths(base())["art:1/par:1"]["device_key"] == "p1"


def test_addition_never_overwrites_a_preexisting_different_device():
    result = project_pilot_device(corpus(event("Art. 1º Outro.", action="ADICIONA")), KEY, "art:1")
    assert result["status"] == "partial" and not result["applied_events"]
    assert result["after"] == result["before"]


def test_unlabelled_replacement_body_preserves_the_original_structural_label():
    result = project_pilot_device(corpus(event("Texto novo.", target="art:1/par:1")), KEY, "art:1/par:1")
    assert result["after"] == "§ 1º Texto novo."

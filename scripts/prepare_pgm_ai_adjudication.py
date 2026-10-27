"""Freeze 20 documentary inputs; labels are authored separately after inspection."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pymupdf
import requests

CORE = [
    ("n01", "lei", "3882", 1989, "F03", "ctm", "compilacao"),
    ("n02", "lei_complementar", "271", 2025, "F04", "ctm", "reproducao"),
    ("n03", "lei_complementar", "258", 2024, "F06", "urbanismo", "reproducao"),
    ("n04", "lei_complementar", "55", 2004, "F09", "urbanismo", "compilacao"),
    ("n05", "lei_complementar", "173", 2017, "F11", "urbanismo", "reproducao"),
    ("n06", "lei_complementar", "185", 2019, "F12", "urbanismo", "reproducao"),
    ("n07", "lei_complementar", "208", 2022, "F13", "urbanismo", "reproducao"),
    ("n08", "lei_complementar", "261", 2025, "F14", "urbanismo", "reproducao"),
    ("n09", "lei", "4885", 1997, "F17", "urbanismo", "reproducao"),
    ("n10", "lei_promulgada", "275", 2009, "F18", "urbanismo", "diario"),
    ("n11", "lei_promulgada", "562", 2018, "F19", "urbanismo", "reproducao"),
    ("n12", "lei", "1894", 1969, "F15", "urbanismo", "reproducao"),
]
QA = [
    ("n13", "lei_complementar", "141", 2014, "LeiComplementar_20140829_141_", "ctm"),
    ("n14", "lei", "7805", 2025, "LeiOrdinaria_20250110_7805_", "isolada_7805"),
    ("n15", "lei", "7806", 2025, "LeiOrdinaria_20250110_7806_", "isolada_7806"),
    ("n16", "lei", "7807", 2025, "LeiOrdinaria_20250110_7807_", "ppa"),
    ("n17", "lei", "7808", 2025, "LeiOrdinaria_20250110_7808_", "isolada_7808"),
    ("n18", "lei", "7810", 2025, "LeiOrdinaria_20250110_7810_", "isolada_7810"),
    ("n19", "lei", "7811", 2025, "LeiOrdinaria_20250116_7811_", "isolada_7811"),
]
PPA_URL = "https://natal.rn.gov.br/storage/app/media/DOM/anexos/dom_20211231_d5463378b9ee874de50e153f35daeb33.pdf"
DOM_2025_URL = "https://natal.rn.gov.br/storage/app/media/DOM/anexos/dom_20250110_extra_79460ed3d8b9fd3d2c7f09fa7f890529.pdf"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def native(pdf):
    chunks, page_map = [], []
    cursor = 0
    with pymupdf.open(pdf) as document:
        for index, page in enumerate(document, 1):
            text = page.get_text()
            chunks.append(text)
            if text:
                page_map.append({"page": index, "start": cursor, "end": cursor + len(text)})
            cursor += len(text)
    return "".join(chunks), page_map


def download(url, path):
    if not path.exists():
        response = requests.get(url, timeout=(10, 90))
        response.raise_for_status()
        assert response.content.startswith(b"%PDF-")
        path.write_bytes(response.content)
    return path


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--prior-review-root", type=Path, required=True)
    parser.add_argument("--qa-export-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite a frozen input directory")
    args.cache_root.mkdir(parents=True, exist_ok=True)
    records = []
    prior = json.loads((args.prior_review_root / "sources.json").read_text(encoding="utf-8"))
    prior = {row["source_id"]: row for row in prior}
    now = datetime.now(UTC).isoformat()
    for uid, kind, number, year, source_id, chain, edition in CORE:
        source = prior[source_id]
        pdf = args.prior_review_root / f"{source_id}.pdf"
        assert sha(pdf.read_bytes()) == source["pdf_sha256"]
        frozen = args.prior_review_root / f"{source_id}.frozen.txt"
        if frozen.exists():
            text = frozen.read_text(encoding="utf-8")
            assert sha(text.encode()) == source["text_sha256"]
            extractor, version, page_map = source["extractor"], source["text_version"], []
        else:
            text, page_map = native(pdf)
            extractor, version = f"pymupdf-{pymupdf.VersionBind}", "native_pages_v1"
        records.append(
            {
                "unit_id": uid,
                "type": kind,
                "number": number,
                "year": year,
                "chain": chain,
                "edition": edition,
                "source_id": source_id,
                "title": source["title"],
                "official_url": source.get("url"),
                "pdf_path": str(pdf.resolve()),
                "pdf_sha256": source["pdf_sha256"],
                "text_sha256": sha(text.encode()),
                "text": text,
                "page_map": page_map,
                "extractor_version": extractor,
                "text_version": version,
                "document_public_id": source.get("document_id"),
            }
        )
    for uid, kind, number, year, filename, chain in QA:
        metadata = json.loads(
            (args.qa_export_root / f"{filename}.json").read_text(encoding="utf-8")
        )
        pdf = args.qa_export_root / f"{filename}.pdf"
        text = (args.qa_export_root / f"{filename}.txt").read_text(encoding="utf-8")
        assert sha(pdf.read_bytes()) == metadata["sha256"]
        assert sha(text.encode()) == metadata["text_sha256"]
        records.append(
            {
                "unit_id": uid,
                "type": kind,
                "number": number,
                "year": year,
                "chain": chain,
                "edition": "reproducao",
                "source_id": filename,
                "title": f"{kind} {number}/{year}",
                "official_url": metadata.get("official_url"),
                "pdf_path": str(pdf.resolve()),
                "pdf_sha256": metadata["sha256"],
                "text_sha256": metadata["text_sha256"],
                "text": text,
                "page_map": metadata["page_map"],
                "extractor_version": metadata["extractor_version"],
                "text_version": metadata["text_version"],
                "document_public_id": metadata["document_public_id"],
                "archive_sha256": metadata["archive_sha256"],
                "entry_index": metadata["entry_index"],
            }
        )
    pdf = download(PPA_URL, args.cache_root / "DOM-20211231.pdf")
    text, page_map = native(pdf)
    records.append(
        {
            "unit_id": "n20",
            "type": "lei",
            "number": "7280",
            "year": 2021,
            "chain": "ppa",
            "edition": "diario",
            "source_id": "DOM-20211231",
            "title": "Lei 7.280/2021 no DOM",
            "official_url": PPA_URL,
            "pdf_path": str(pdf.resolve()),
            "pdf_sha256": sha(pdf.read_bytes()),
            "text_sha256": sha(text.encode()),
            "text": text,
            "page_map": page_map,
            "extractor_version": f"pymupdf-{pymupdf.VersionBind}",
            "text_version": "native_pages_v1",
            "document_public_id": None,
        }
    )
    download(DOM_2025_URL, args.cache_root / "DOM-20250110-extra.pdf")
    args.output.mkdir(parents=True)
    (args.output / "texts").mkdir()
    for row in records:
        text = row.pop("text")
        row["text_path"] = f"texts/{row['unit_id']}.txt"
        row["captured_at"] = now
        (args.output / row["text_path"]).write_text(text, encoding="utf-8", newline="\n")
    (args.output / "inputs.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    selection = {
        "created_at": now,
        "seed": "jurix-pgm-ai-20261018-v1",
        "method": "Amostra intencional retrospectiva: 13 atos dos casos documentais, seis leis de janeiro de 2025 e a lei-base do PPA; sem usar saídas de recuperação como gabarito.",
        "prior_exposure": "Casos centrais já foram usados no desenvolvimento; não é teste científico cego nem estimativa de desempenho no acervo inteiro.",
        "units": [
            {
                k: row[k]
                for k in ("unit_id", "type", "number", "year", "chain", "pdf_sha256", "text_sha256")
            }
            for row in records
        ],
    }
    (args.output / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "units": len(records),
                "distinct_norms": len({(r["type"], r["number"], r["year"]) for r in records}),
                "source_freeze": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()

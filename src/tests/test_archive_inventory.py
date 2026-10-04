from __future__ import annotations

import hashlib
import json
import stat
import warnings
import zipfile
from pathlib import Path

import pytest

from src.processing.archive_inventory import InventoryPolicy, inventory_archive


def _zip(path: Path, entries: list[tuple[str | zipfile.ZipInfo, bytes]]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return path


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_inventory_hashes_pdfs_and_only_lists_other_extensions(tmp_path):
    archive = _zip(
        tmp_path / "corpus.zip",
        [
            ("LeiOrdinaria_20260821_55.pdf", b"%PDF-1.4 sample"),
            ("nested/readme.html", b"do not execute"),
            ("tools/import.py", b"do not execute"),
        ],
    )
    manifest = tmp_path / "manifest.jsonl"
    summary = inventory_archive(archive, manifest)
    rows = _records(manifest)
    pdf = rows[0]
    assert summary["complete"] is True
    assert pdf["content_sha256"] == hashlib.sha256(b"%PDF-1.4 sample").hexdigest()
    assert pdf["filename_metadata"]["number"] == "55"
    assert rows[1]["hash_status"] == "not_selected"
    assert rows[2]["hash_status"] == "not_selected"
    assert summary["extension_counts"] == {".html": 1, ".pdf": 1, ".py": 1}


def test_inventory_replay_is_byte_deterministic_for_same_input(tmp_path):
    archive = _zip(tmp_path / "same.zip", [("Lei_20200101_1.pdf", b"pdf")])
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    inventory_archive(archive, first)
    inventory_archive(archive, second)
    assert first.read_bytes() == second.read_bytes()


def test_inventory_refuses_to_overwrite_existing_evidence(tmp_path):
    archive = _zip(tmp_path / "source.zip", [("x.pdf", b"pdf")])
    output = tmp_path / "manifest.jsonl"
    output.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        inventory_archive(archive, output)
    assert output.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("name", ["../escape.pdf", "/absolute.pdf", "C:\\outside.pdf"])
def test_unsafe_archive_paths_are_not_hashed(name, tmp_path):
    archive = _zip(tmp_path / "unsafe.zip", [(name, b"pdf")])
    summary = inventory_archive(archive, tmp_path / "manifest.jsonl")
    row = _records(tmp_path / "manifest.jsonl")[0]
    assert summary["complete"] is False
    assert "unsafe_path" in row["flags"]
    assert row["content_sha256"] is None


def test_duplicate_entry_names_are_indexed_and_reported(tmp_path):
    archive_path = tmp_path / "duplicates.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        _zip(archive_path, [("same.pdf", b"first"), ("same.pdf", b"second")])
    summary = inventory_archive(archive_path, tmp_path / "manifest.jsonl")
    assert summary["entry_count"] == 2
    assert summary["case_insensitive_name_collision_groups"] == [[0, 1]]
    assert (
        _records(tmp_path / "manifest.jsonl")[0]["content_sha256"]
        != _records(tmp_path / "manifest.jsonl")[1]["content_sha256"]
    )


def test_unc_style_path_is_unsafe_before_zipfile_name_normalization():
    from src.processing.archive_inventory import _unsafe_path

    assert _unsafe_path("\\\\host\\x.pdf") is True


def test_exact_duplicate_contents_and_candidate_identity_are_reported_separately(tmp_path):
    archive = _zip(
        tmp_path / "dupes.zip",
        [
            ("LeiOrdinaria_20260821_055_a.pdf", b"same"),
            ("LeiOrdinaria_20260821_55_b.pdf", b"same"),
        ],
    )
    summary = inventory_archive(archive, tmp_path / "manifest.jsonl")
    assert summary["exact_content_duplicate_groups"] == [[0, 1]]
    assert summary["potential_filename_identity_collision_groups"] == [[0, 1]]


def test_symlink_entry_is_listed_but_not_hashed(tmp_path):
    link = zipfile.ZipInfo("link.pdf")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive = _zip(tmp_path / "link.zip", [(link, b"target.pdf")])
    summary = inventory_archive(archive, tmp_path / "manifest.jsonl")
    row = _records(tmp_path / "manifest.jsonl")[0]
    assert summary["complete"] is False
    assert "symlink" in row["flags"]
    assert row["content_sha256"] is None


def test_encrypted_pdf_entry_is_listed_but_not_opened(tmp_path):
    archive_path = _zip(tmp_path / "plain.zip", [("encrypted.pdf", b"secret bytes")])
    raw = bytearray(archive_path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        cursor = 0
        while True:
            cursor = raw.find(signature, cursor)
            if cursor < 0:
                break
            flags = int.from_bytes(raw[cursor + flag_offset : cursor + flag_offset + 2], "little")
            raw[cursor + flag_offset : cursor + flag_offset + 2] = (flags | 0x1).to_bytes(
                2, "little"
            )
            cursor += len(signature)
    archive_path.write_bytes(raw)
    summary = inventory_archive(archive_path, tmp_path / "manifest.jsonl")
    row = _records(tmp_path / "manifest.jsonl")[0]
    assert summary["complete"] is False
    assert "encrypted" in row["flags"]
    assert row["content_sha256"] is None


def test_pdf_and_batch_size_limits_leave_an_incomplete_manifest(tmp_path):
    oversized = _zip(tmp_path / "oversized.zip", [("first.pdf", b"12345")])
    size_summary = inventory_archive(
        oversized,
        tmp_path / "oversized.jsonl",
        policy=InventoryPolicy(max_pdf_bytes=4),
    )
    assert "pdf_size_limit" in _records(tmp_path / "oversized.jsonl")[0]["flags"]
    assert size_summary["unhashed_pdf_entries"] == [0]

    archive = _zip(
        tmp_path / "large.zip",
        [("first.pdf", b"12345"), ("second.pdf", b"12345")],
    )
    summary = inventory_archive(
        archive,
        tmp_path / "manifest.jsonl",
        policy=InventoryPolicy(max_total_uncompressed_bytes=6),
    )
    rows = _records(tmp_path / "manifest.jsonl")
    assert summary["complete"] is False
    assert rows[0]["hash_status"] == "hashed"
    assert "archive_batch_size_limit" in rows[1]["flags"]
    assert summary["unhashed_pdf_entries"] == [1]


def test_extreme_compression_ratio_is_flagged(tmp_path):
    archive = _zip(tmp_path / "ratio.zip", [("large.pdf", b"a" * 100_000)])
    policy = InventoryPolicy(max_compression_ratio=2)
    summary = inventory_archive(archive, tmp_path / "manifest.jsonl", policy=policy)
    row = _records(tmp_path / "manifest.jsonl")[0]
    assert summary["complete"] is False
    assert "compression_ratio_limit" in row["flags"]


def test_entry_count_limit_fails_before_creating_output(tmp_path):
    archive = _zip(tmp_path / "many.zip", [("one.txt", b"1"), ("two.txt", b"2")])
    output = tmp_path / "manifest.jsonl"
    with pytest.raises(ValueError, match="entry count"):
        inventory_archive(archive, output, policy=InventoryPolicy(max_entries=1))
    assert not output.exists()


def test_truncated_zip_fails_closed_without_manifest(tmp_path):
    archive = _zip(tmp_path / "good.zip", [("law.pdf", b"pdf")])
    truncated = tmp_path / "truncated.zip"
    truncated.write_bytes(archive.read_bytes()[:-22])
    output = tmp_path / "manifest.jsonl"
    with pytest.raises(zipfile.BadZipFile):
        inventory_archive(truncated, output)
    assert not output.exists()

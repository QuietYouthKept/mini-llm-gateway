from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

from scripts.build_evidence_manifest import collect_public_evidence_files
from scripts.evidence_policy import is_public_artifact_path
from scripts.validate_evidence_artifact import main, validate_archive


def _make_archive(
    path: Path, *, include: bool = True, tamper: bool = False, extra: bool = False
) -> None:
    payload = b"reviewable evidence\n"
    manifest = {
        "git_sha": "a" * 40,
        "files": [
            {
                "path": "pytest.log",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest_bytes)
        archive.writestr("manifest.sha256", f"{manifest_hash}  manifest.json\n")
        if include:
            archive.writestr("pytest.log", b"tampered evidence\n" if tamper else payload)
        if extra:
            archive.writestr("unexpected.txt", "unlisted file")


def test_valid_artifact_matches_exact_manifest_set_and_hashes(tmp_path: Path) -> None:
    archive = tmp_path / "valid.zip"
    _make_archive(archive)

    result = validate_archive(archive)

    assert result["passed"] is True
    assert result["git_sha"] == "a" * 40
    assert result["expected_file_count"] == 1
    assert result["actual_file_count"] == 1


def test_missing_manifested_file_fails(tmp_path: Path) -> None:
    archive = tmp_path / "missing.zip"
    _make_archive(archive, include=False)

    result = validate_archive(archive)

    assert result["passed"] is False
    assert result["missing_files"] == ["pytest.log"]


def test_tampered_payload_hash_or_size_fails(tmp_path: Path) -> None:
    archive = tmp_path / "tampered.zip"
    _make_archive(archive, tamper=True)

    result = validate_archive(archive)

    assert result["passed"] is False
    assert [item["path"] for item in result["hash_or_size_mismatches"]] == ["pytest.log"]


def test_unmanifested_extra_file_fails(tmp_path: Path) -> None:
    archive = tmp_path / "extra.zip"
    _make_archive(archive, extra=True)

    result = validate_archive(archive)

    assert result["passed"] is False
    assert result["extra_files"] == ["unexpected.txt"]


def test_hidden_file_is_rejected_even_if_unlisted(tmp_path: Path) -> None:
    archive = tmp_path / "hidden.zip"
    _make_archive(archive)
    with zipfile.ZipFile(archive, "a", compression=zipfile.ZIP_DEFLATED) as payload:
        payload.writestr("postgres/.coverage", b"coverage database")

    result = validate_archive(archive)

    assert result["passed"] is False
    assert "path_not_allowlisted:postgres/.coverage" in result["errors"]


def test_public_evidence_allowlist_excludes_hidden_and_sensitive_paths() -> None:
    assert is_public_artifact_path("pytest.log")
    assert is_public_artifact_path("coverage-gate.log")
    assert is_public_artifact_path("status/pytest.exitcode")
    assert is_public_artifact_path("coverage/html/status.json")
    assert not is_public_artifact_path("postgres/.coverage")
    assert not is_public_artifact_path("coverage/html/.gitignore")
    assert not is_public_artifact_path(".env")
    assert not is_public_artifact_path("private/token.pem")
    assert not is_public_artifact_path("postgres/local.sqlite3")
    assert not is_public_artifact_path("unreviewed-visible-file.txt")


def test_manifest_builder_excludes_hidden_files_and_rejects_unknown_visible_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "status").mkdir()
    (tmp_path / "postgres").mkdir()
    (tmp_path / "coverage" / "html").mkdir(parents=True)
    (tmp_path / "pytest.log").write_text("safe", encoding="utf-8")
    (tmp_path / "status" / "pytest.exitcode").write_text("0", encoding="utf-8")
    (tmp_path / "postgres" / ".coverage").write_bytes(b"sqlite coverage data")
    (tmp_path / "coverage" / "html" / ".gitignore").write_text("*", encoding="utf-8")
    (tmp_path / "coverage" / "html" / "status.json").write_text("{}", encoding="utf-8")

    files, rejected = collect_public_evidence_files(tmp_path)

    assert [path.relative_to(tmp_path).as_posix() for path in files] == [
        "coverage/html/status.json",
        "pytest.log",
        "status/pytest.exitcode",
    ]
    assert rejected == []

    (tmp_path / "unreviewed-visible-file.txt").write_text("must not upload", encoding="utf-8")
    _, rejected = collect_public_evidence_files(tmp_path)
    assert rejected == ["unreviewed-visible-file.txt"]


def test_cli_writes_machine_readable_failure_result(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "missing.zip"
    output = tmp_path / "result.json"
    _make_archive(archive, include=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["validate_evidence_artifact.py", "--archive", str(archive), "--output", str(output)],
    )

    assert main() == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert result["missing_files"] == ["pytest.log"]

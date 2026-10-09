"""Validate a downloaded GitHub Actions evidence ZIP against its manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evidence_policy import is_public_artifact_path

_MANIFEST_NAME = "manifest.json"
_CHECKSUM_NAME = "manifest.sha256"
_SHA256_PATTERN = re.compile(r"([0-9a-f]{64})  manifest\.json\n?")
_MAX_ENTRY_BYTES = 200 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_stream(source: Any) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(name: str) -> bool:
    return (
        bool(name)
        and not name.startswith("/")
        and "\\" not in name
        and all(part not in {"", ".", ".."} for part in name.split("/"))
    )


def validate_archive(archive_path: Path) -> dict[str, Any]:
    """Return a machine-readable result; invalid archives are never extracted."""
    result: dict[str, Any] = {
        "schema_version": 1,
        "validated_at_utc": datetime.now(UTC).isoformat(),
        "archive_name": archive_path.name,
        "passed": False,
        "git_sha": None,
        "manifest_sha256": None,
        "expected_file_count": 0,
        "actual_file_count": 0,
        "missing_files": [],
        "extra_files": [],
        "hash_or_size_mismatches": [],
        "errors": [],
    }

    try:
        if archive_path.stat().st_size > _MAX_ARCHIVE_BYTES:
            raise ValueError("archive exceeds maximum compressed size")
        with zipfile.ZipFile(archive_path) as archive:
            entries: dict[str, zipfile.ZipInfo] = {}
            total_size = 0
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if name in entries:
                    result["errors"].append(f"duplicate_archive_path:{name}")
                    continue
                entries[name] = info
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    result["errors"].append(f"symlink_not_allowed:{name}")
                if info.flag_bits & 0x1:
                    result["errors"].append(f"encrypted_entry_not_allowed:{name}")
                total_size += info.file_size
                if info.file_size > _MAX_ENTRY_BYTES:
                    result["errors"].append(f"entry_too_large:{name}")
                if name not in {_MANIFEST_NAME, _CHECKSUM_NAME} and not is_public_artifact_path(name):
                    result["errors"].append(f"path_not_allowlisted:{name}")
            if total_size > _MAX_ARCHIVE_BYTES:
                result["errors"].append("uncompressed_archive_exceeds_limit")

            for required in (_MANIFEST_NAME, _CHECKSUM_NAME):
                if required not in entries:
                    result["errors"].append(f"missing_required_file:{required}")
            if any(error.startswith("missing_required_file:") for error in result["errors"]):
                return result

            manifest_bytes = archive.read(entries[_MANIFEST_NAME])
            checksum_text = archive.read(entries[_CHECKSUM_NAME]).decode("ascii").strip()
            checksum_match = _SHA256_PATTERN.fullmatch(checksum_text + "\n")
            manifest_digest = _hash_bytes(manifest_bytes)
            result["manifest_sha256"] = manifest_digest
            if checksum_match is None or checksum_match.group(1) != manifest_digest:
                result["errors"].append("manifest_checksum_mismatch")
                return result

            manifest = json.loads(manifest_bytes)
            result["git_sha"] = manifest.get("git_sha")
            records = manifest.get("files")
            if not isinstance(records, list):
                result["errors"].append("manifest_files_not_a_list")
                return result

            expected: dict[str, dict[str, Any]] = {}
            for record in records:
                if not isinstance(record, dict):
                    result["errors"].append("invalid_manifest_record")
                    continue
                name = record.get("path")
                size = record.get("size_bytes")
                digest = record.get("sha256")
                if (
                    not isinstance(name, str)
                    or not isinstance(size, int)
                    or size < 0
                    or not isinstance(digest, str)
                    or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                ):
                    result["errors"].append("invalid_or_disallowed_manifest_record")
                    continue
                if name in expected:
                    result["errors"].append(f"duplicate_manifest_path:{name}")
                if not _safe_relative_path(name):
                    result["errors"].append(f"unsafe_manifest_path:{name}")
                    continue
                if not is_public_artifact_path(name):
                    result["errors"].append(f"manifest_path_not_allowlisted:{name}")
                expected[name] = record

            actual = set(entries) - {_MANIFEST_NAME, _CHECKSUM_NAME}
            expected_names = set(expected)
            result["expected_file_count"] = len(expected_names)
            result["actual_file_count"] = len(actual)
            result["missing_files"] = sorted(expected_names - actual)
            result["extra_files"] = sorted(actual - expected_names)

            for name in sorted(expected_names & actual):
                info = entries[name]
                record = expected[name]
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or info.flag_bits & 0x1:
                    continue
                with archive.open(info) as source:
                    actual_digest = _hash_stream(source)
                if info.file_size != record["size_bytes"] or actual_digest != record["sha256"]:
                    result["hash_or_size_mismatches"].append(
                        {
                            "path": name,
                            "expected_size_bytes": record["size_bytes"],
                            "actual_size_bytes": info.file_size,
                            "expected_sha256": record["sha256"],
                            "actual_sha256": actual_digest,
                        }
                    )

            result["passed"] = not any(
                result[key]
                for key in ("errors", "missing_files", "extra_files", "hash_or_size_mismatches")
            )
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        result["errors"].append(f"archive_validation_error:{type(exc).__name__}:{exc}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_archive(args.archive)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Allowlist for public, reviewable files in the CI evidence artifact."""

from __future__ import annotations

from pathlib import PurePosixPath

_ROOT_FILES = {
    "compileall.log",
    "coverage-gate.log",
    "dependency-audit.json",
    "dependency-audit.stderr",
    "diff-check.log",
    "environment.txt",
    "functional-eval.txt",
    "pytest-junit.xml",
    "pytest.log",
    "ruff.log",
    "secret-scan.txt",
    "security-eval.txt",
}
_DIRECTORY_FILES = {
    "coverage": {"coverage.xml"},
    "postgres": {
        "coverage.json",
        "coverage.txt",
        "coverage.xml",
        "integration.json",
        "integration.stderr",
    },
    "redis": {
        "adapters.json",
        "adapters.stderr",
        "coverage.json",
        "coverage.txt",
        "coverage.xml",
        "two-replica.json",
        "two-replica.stderr",
    },
    "http-sse": {"junit.xml", "result.log"},
    "provider": {"junit.xml", "result.log"},
}
_HTML_DIRECTORIES = {("coverage", "html"), ("postgres", "coverage-html"), ("redis", "coverage-html")}
_REPORT_SUFFIXES = {".css", ".html", ".js", ".json", ".png", ".svg"}
_FORBIDDEN_SUFFIXES = {
    ".cer",
    ".crt",
    ".db",
    ".exe",
    ".key",
    ".p12",
    ".pfx",
    ".pem",
    ".pyc",
    ".pyd",
    ".sqlite",
    ".sqlite3",
    ".so",
}
_MANIFEST_FILES = {"manifest.json", "manifest.sha256", "artifact-validation.json"}


def is_public_artifact_path(value: str) -> bool:
    """Return whether a relative POSIX path is allowed in the public artifact.

    Hidden path components are intentionally excluded to match
    ``upload-artifact``'s ``include-hidden-files: false`` behavior. The
    remaining paths must belong to the explicit CI evidence layout.
    """
    if not value or "\\" in value or value.startswith("/"):
        return False
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part.startswith(".") for part in parts):
        return False
    if len(parts) > 1 and any(part.lower() in {".git", ".venv", "node_modules"} for part in parts):
        return False

    name = parts[-1]
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in _FORBIDDEN_SUFFIXES or name in _MANIFEST_FILES:
        return False

    if len(parts) == 1:
        return name in _ROOT_FILES
    if parts[0] == "status":
        return len(parts) == 2 and name.endswith(".exitcode")
    if parts[0] in _DIRECTORY_FILES:
        if len(parts) == 2:
            return name in _DIRECTORY_FILES[parts[0]]
        if len(parts) == 3 and (parts[0], parts[1]) in _HTML_DIRECTORIES:
            return suffix in _REPORT_SUFFIXES
    return False

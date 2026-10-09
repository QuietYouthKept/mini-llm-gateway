from __future__ import annotations

import runpy
import subprocess
import sys

from coverage import Coverage


def test_coverage_cli_fails_for_data_below_required_threshold(tmp_path) -> None:
    """Protect the independent CI gate from a pytest-cov status regression."""
    module = tmp_path / "undercovered.py"
    module.write_text(
        "def covered():\n"
        "    return True\n"
        "\n"
        "def not_covered():\n"
        "    return False\n"
        "\n"
        "def also_not_covered():\n"
        "    return None\n"
        "\n"
        "covered()\n",
        encoding="utf-8",
    )
    data_file = tmp_path / ".coverage-under-threshold"
    coverage = Coverage(data_file=str(data_file), source=[str(tmp_path)], branch=True)
    coverage.start()
    try:
        runpy.run_path(str(module))
    finally:
        coverage.stop()
        coverage.save()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "report",
            f"--data-file={data_file}",
            "--fail-under=80",
            "--precision=2",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Coverage failure:" in result.stdout
    assert "fail-under=80.00" in result.stdout

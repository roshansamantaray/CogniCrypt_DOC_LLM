import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "delete_disabled_code_cache_files.py"
)

PLACEHOLDER = "// LLM secure example disabled by flag."


def _run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_report_path_derives_default_cache_dir(tmp_path: Path) -> None:
    report_path = tmp_path / "custom-output"
    cache_dir = report_path / "resources" / "code_cache"
    cache_dir.mkdir(parents=True)

    placeholder_file = cache_dir / "one.txt"
    placeholder_file.write_text(PLACEHOLDER, encoding="utf-8")
    normal_file = cache_dir / "two.txt"
    normal_file.write_text("real example", encoding="utf-8")

    proc = _run_script("--report-path", str(report_path))

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert not placeholder_file.exists()
    assert normal_file.exists()


def test_cache_dir_override_takes_precedence_over_report_path(tmp_path: Path) -> None:
    report_path = tmp_path / "custom-output"
    derived_cache_dir = report_path / "resources" / "code_cache"
    derived_cache_dir.mkdir(parents=True)
    derived_file = derived_cache_dir / "derived.txt"
    derived_file.write_text(PLACEHOLDER, encoding="utf-8")

    override_cache_dir = tmp_path / "explicit-cache-dir"
    override_cache_dir.mkdir(parents=True)
    override_file = override_cache_dir / "override.txt"
    override_file.write_text(PLACEHOLDER, encoding="utf-8")

    proc = _run_script(
        "--report-path",
        str(report_path),
        "--cache-dir",
        str(override_cache_dir),
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert not override_file.exists()
    assert derived_file.exists()

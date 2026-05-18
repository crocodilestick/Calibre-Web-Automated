import os
import subprocess
import sys
import textwrap
import importlib
import inspect
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_import_and_missing_target_skip_heavy_startup(tmp_path):
    config_processed_books = Path("/config/processed_books")
    config_processed_books_existed = config_processed_books.exists()
    script = textwrap.dedent(
        """
        import os
        import sys
        from pathlib import Path

        scripts_dir = Path(os.environ["CWA_TEST_SCRIPTS_DIR"])
        tmp_path = Path(os.environ["CWA_TEST_TMPDIR"])
        sys.path.insert(0, str(scripts_dir))

        import ingest_processor

        lock_path = tmp_path / "ingest_processor.lock"
        if lock_path.exists():
            raise AssertionError("default lock was created during import")
        if ingest_processor.process_lock is not None:
            raise AssertionError("default process lock was initialized during import")

        result = ingest_processor.main(str(tmp_path / "missing.epub"))
        if result not in (0, None):
            raise AssertionError(f"missing target returned unexpected status: {result!r}")
        if lock_path.exists():
            raise AssertionError("default lock was created for missing target")
        if ingest_processor.process_lock is not None:
            raise AssertionError("process lock was initialized for missing target")
        """
    )
    env = os.environ.copy()
    env["TMPDIR"] = str(tmp_path)
    env["CWA_TEST_TMPDIR"] = str(tmp_path)
    env["CWA_TEST_SCRIPTS_DIR"] = str(Path(__file__).resolve().parents[2] / "scripts")

    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[ingest-processor] Skipping missing ingest target:" in result.stdout
    assert "File did not become ready in time or vanished" not in result.stdout
    assert not (tmp_path / "ingest_processor.lock").exists()
    if not config_processed_books_existed:
        assert not config_processed_books.exists()


def test_failed_runtime_initialization_is_not_retried(monkeypatch, tmp_path):
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    ingest_processor = importlib.import_module("ingest_processor")
    ingest_processor._runtime_initialized = False
    ingest_processor._runtime_init_attempted = False
    ingest_processor.process_lock = None

    acquire_calls = 0

    class ContendedLock:
        def acquire(self, timeout=5):
            nonlocal acquire_calls
            acquire_calls += 1
            assert timeout == 10
            return False

        def release(self):
            pass

    monkeypatch.setattr(ingest_processor, "_ensure_project_root_on_path", lambda: None)
    monkeypatch.setattr(ingest_processor, "_load_runtime_dependencies", lambda: None)
    monkeypatch.setattr(ingest_processor, "_load_optional_cps_modules", lambda: None)
    monkeypatch.setattr(ingest_processor, "ProcessLock", ContendedLock)

    assert ingest_processor.initialize_runtime() is False
    assert ingest_processor.initialize_runtime() is False
    assert acquire_calls == 1


def test_optional_cps_modules_retry_after_partial_load(monkeypatch, tmp_path):
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    ingest_processor = importlib.import_module("ingest_processor")
    source = inspect.getsource(ingest_processor._load_optional_cps_modules)

    assert "if _GDRIVE_AVAILABLE and _CPS_AVAILABLE:" in source
    assert "if _GDRIVE_AVAILABLE or _CPS_AVAILABLE:" not in source

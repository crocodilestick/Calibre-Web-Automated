# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Opt-in support for user-installed Calibre plugins during ingest.

When ``CWA_CALIBRE_USER_PLUGINS`` is set to a truthy value (``1`` /
``true`` / ``yes`` / ``on``), Calibre subprocess invocations launched by
the ingest pipeline run with ``HOME=/config`` and
``CALIBRE_CONFIG_DIRECTORY=/config/.config/calibre`` so that the
embedded Calibre process loads any plugins the operator has placed under
``/config/.config/calibre/plugins/``. The plugins directory is created
on first use if missing.

``CALIBRE_CONFIG_DIRECTORY`` is Calibre's documented configuration
variable and is authoritative; ``HOME`` is kept alongside it for any
Calibre code path that derives dotfile locations from the home
directory. (The image used to set a misspelled ``CALIBRE_CONFIG_DIR``
globally in the Dockerfile — Calibre ignores that name, which is why
plugin loading historically only worked through the HOME override.
Diagnosed by @jasonobrien in fork PR #434. A global
``CALIBRE_CONFIG_DIRECTORY`` would defeat this module's off-state, so
the variable is set here, per-subprocess, gated on the opt-in.)

The default is **off**. Plugin loading is the operator's explicit
choice — it activates third-party Python code from a user-controlled
directory inside the running container, and the operator should opt in
deliberately. Closes upstream Calibre-Web-Automated [issue
#243](https://github.com/crocodilestick/Calibre-Web-Automated/issues/243).

Public API:
    is_enabled() -> bool
    apply_to_env(env: dict[str, str]) -> dict[str, str]
    ensure_plugins_dir() -> Path | None

The module has no Flask / SQLAlchemy dependencies — safe to import from
any layer (cps/, scripts/) and from cont-init bootstrap code.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


_ENV_VAR = "CWA_CALIBRE_USER_PLUGINS"
_HOME = "/config"
_PLUGINS_SUBPATH = ".config/calibre/plugins"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_enabled() -> bool:
    """True iff the operator has opted into Calibre user-plugin loading.

    Reads ``CWA_CALIBRE_USER_PLUGINS`` from the process environment and
    normalizes the value (case- and whitespace-insensitive) against the
    standard truthy set used elsewhere in the codebase
    (cf. NETWORK_SHARE_MODE).
    """
    raw = os.environ.get(_ENV_VAR, "")
    return raw.strip().lower() in _TRUTHY


def apply_to_env(env: dict[str, str]) -> dict[str, str]:
    """If enabled, set ``HOME=/config`` and
    ``CALIBRE_CONFIG_DIRECTORY=/config/.config/calibre`` on the given
    env mapping in place and return it. If disabled, return the env
    unchanged.

    Designed to be called right before ``subprocess.run(..., env=env)``:

        env = os.environ.copy()
        env = calibre_user_plugins.apply_to_env(env)
        subprocess.run(["ebook-convert", ...], env=env, check=True)

    When disabled, the subprocess inherits whatever HOME is already set
    in the parent (typically the abc service user's home), and Calibre
    looks for plugins in that user's home — usually empty, so plugins
    do not load. That is the intended off-state.
    """
    if is_enabled():
        env["HOME"] = _HOME
        env["CALIBRE_CONFIG_DIRECTORY"] = str(config_dir())
    return env


def config_dir() -> Path:
    """Absolute path to the Calibre configuration directory the opt-in
    points subprocesses at (``/config/.config/calibre``). The plugins
    directory lives directly beneath it."""
    return Path(_HOME) / _PLUGINS_SUBPATH.rsplit("/", 1)[0]


def plugins_dir() -> Path:
    """Absolute path to where Calibre will look for user plugins when
    HOME=/config. Always returns a path; doesn't check existence."""
    return Path(_HOME) / _PLUGINS_SUBPATH


def ensure_plugins_dir() -> Path | None:
    """If enabled, create ``/config/.config/calibre/plugins`` (with
    parents) so the operator has a destination ready for their plugin
    .zip files. Returns the path on success, ``None`` if disabled or on
    permission error (logged, not raised — bootstrap should be best-
    effort, not block the container start).

    Idempotent: harmless when the dir already exists.
    """
    if not is_enabled():
        return None
    target = plugins_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
        return target
    except (PermissionError, OSError):
        # Bootstrap is best-effort. The operator can mkdir manually if
        # the container is running with restricted FS perms; ingest will
        # still see HOME=/config and use whatever the operator placed
        # there.
        return None


# Path to the calibre customize.py.json registry under our HOME=/config.
# When a plugin is added via `calibre-customize -a`, calibre records it
# under the "plugins" key of this file. We use that to detect what's
# already registered so we don't redundantly re-register on every boot.
_CUSTOMIZE_JSON = Path(_HOME) / ".config" / "calibre" / "customize.py.json"


def _registered_plugin_names() -> set[str]:
    """Return the set of plugin display names already registered with
    calibre. Empty set if customize.py.json doesn't exist or can't be
    parsed."""
    import json
    if not _CUSTOMIZE_JSON.is_file():
        return set()
    try:
        data = json.loads(_CUSTOMIZE_JSON.read_text())
    except (json.JSONDecodeError, OSError):
        return set()
    plugins = data.get("plugins", {})
    if isinstance(plugins, dict):
        return set(plugins.keys())
    return set()


def auto_register_plugins(
    calibre_customize_binary: str = "/app/calibre/calibre-customize",
) -> list[str]:
    """If enabled, scan the plugins dir for ``*.zip`` files and call
    ``calibre-customize -a`` on each one with HOME=/config so calibre
    records it in customize.py.json. Returns the list of plugin names
    successfully registered this call (could be empty if nothing new).

    Idempotent across reboots — calibre's own internal dedup handles
    re-registration of the same .zip cleanly. We additionally short-
    circuit when the registry already has entries to keep boot fast.

    Designed to be called from the container bootstrap (auto_library)
    after ensure_plugins_dir(). When disabled, returns ``[]`` without
    touching the filesystem.

    The binary path defaults to the canonical location inside our
    Docker image (`/app/calibre/calibre-customize`); override for
    tests or alternate Calibre installs.
    """
    import subprocess

    if not is_enabled():
        return []

    target = plugins_dir()
    if not target.is_dir():
        return []

    # On reboots after the first registration pass, calibre has copied
    # each plugin .zip into the same dir under its display-name (e.g.
    # `DeDRM_plugin.zip` → `DeDRM.zip`). The operator's original drop
    # is still there. To avoid spamming calibre-customize -a with files
    # it has already absorbed, we skip the scan when customize.py.json
    # already has a non-empty `plugins` dict — operator can manually
    # register additional plugins later via `docker exec` if they want
    # to add more without a fresh container start.
    if _registered_plugin_names():
        return []

    env = {"HOME": _HOME, "PATH": "/usr/bin:/bin:/app/calibre"}
    registered: list[str] = []
    # `calibre-customize -a` copies the source .zip into
    # `<plugins_dir>/<PluginDisplayName>.zip`. When the source filename
    # already matches the display name (e.g. operator drops `DeACSM.zip`
    # and the plugin's display name is "DeACSM"), source and destination
    # collide and the registration silently fails — the source file gets
    # truncated/removed, customize.py.json stays unchanged. Stage every
    # source through /tmp first so the destination path can never equal
    # the source path. Side benefit: keeps the operator's original .zip
    # exactly as they dropped it, untouched by calibre's copy logic.
    import shutil
    import tempfile
    for zip_path in sorted(target.glob("*.zip")):
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".zip", prefix="cwa-plugin-", delete=False
            ) as tmp:
                staged_path = tmp.name
            shutil.copy(str(zip_path), staged_path)
            result = subprocess.run(
                [calibre_customize_binary, "-a", staged_path],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            try:
                Path(staged_path).unlink()
            except OSError:
                pass
            if result.returncode == 0:
                # Calibre prints a final line `Plugin added: <Name> (...)`.
                # Extract the name to log + return; fall back to filename.
                for line in (result.stdout or "").splitlines():
                    if line.startswith("Plugin added:"):
                        name = line[len("Plugin added:"):].strip()
                        registered.append(name)
                        break
                else:
                    registered.append(zip_path.stem)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            # Best-effort. A missing calibre-customize binary or hung
            # subprocess shouldn't block container boot. The operator
            # can still manually register via docker exec later.
            continue
    return registered


def env_var_name() -> str:
    """Public accessor so tests / docs can reference the canonical name
    without re-defining it."""
    return _ENV_VAR


def home_path() -> str:
    """Public accessor for the HOME value injected when enabled."""
    return _HOME

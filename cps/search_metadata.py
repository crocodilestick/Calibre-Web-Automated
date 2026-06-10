# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import concurrent.futures
import importlib
import inspect
import json
import os
import sys

from flask import Blueprint, request, url_for, make_response, jsonify, copy_current_request_context
from .cw_login import current_user
from flask_babel import get_locale
from sqlalchemy.exc import InvalidRequestError, OperationalError
from sqlalchemy.orm.attributes import flag_modified

from cps.services.Metadata import Metadata
from cps.services.cover_booster import boost_covers
from . import config, constants, logger, ub, web_server
from .usermanagement import user_login_required


meta = Blueprint("metadata", __name__)

log = logger.create()

try:
    from dataclasses import asdict
except ImportError:
    log.info('*** "dataclasses" is needed for calibre-web automated to run. Please install it using pip: "pip install dataclasses" ***')
    print('*** "dataclasses" is needed for calibre-web automated to run. Please install it using pip: "pip install dataclasses" ***')
    web_server.stop(True)
    sys.exit(6)

new_list = list()
meta_dir = os.path.join(constants.BASE_DIR, "cps", "metadata_provider")
modules = os.listdir(os.path.join(constants.BASE_DIR, "cps", "metadata_provider"))
for f in modules:
    if os.path.isfile(os.path.join(meta_dir, f)) and not f.endswith("__init__.py"):
        a = os.path.basename(f)[:-3]
        try:
            importlib.import_module("cps.metadata_provider." + a)
            new_list.append(a)
        except (IndentationError, SyntaxError) as e:
            log.error("Syntax error for metadata source: {} - {}".format(a, e))
        except ImportError as e:
            log.debug("Import error for metadata source: {} - {}".format(a, e))


def list_classes(provider_list):
    classes = list()
    for element in provider_list:
        for name, obj in inspect.getmembers(
            sys.modules["cps.metadata_provider." + element]
        ):
            if (
                inspect.isclass(obj)
                and name != "Metadata"
                and issubclass(obj, Metadata)
            ):
                classes.append(obj())
    return classes


cl = list_classes(new_list)
# Alphabetises the list of Metadata providers
cl.sort(key=lambda x: x.__class__.__name__)


# Optional verbose logging across every metadata provider — flip via env
# CWA_METADATA_DEBUG=1 to bump the family of cps.metadata_provider.* loggers
# to DEBUG without touching the global log level.
if os.environ.get("CWA_METADATA_DEBUG", "").lower() in ("1", "true", "yes"):
    import logging
    for provider_module in new_list:
        logging.getLogger("cps.metadata_provider." + provider_module).setLevel(logging.DEBUG)
    logging.getLogger("cps.search_metadata").setLevel(logging.DEBUG)
    log.info("CWA_METADATA_DEBUG=1: metadata-provider logs bumped to DEBUG")


# Helper to load global provider enablement map from CWA settings
def _get_global_provider_enabled_map() -> dict:
    try:
        # Import here to avoid circular import issues and keep startup fast
        sys.path.insert(1, '/app/calibre-web-automated/scripts/')
        from cwa_db import CWA_DB  # type: ignore
        cwa_db = CWA_DB()
        settings = cwa_db.get_cwa_settings()
        
        if not settings:
            log.warning("Could not get CWA settings for provider enabled map")
            return {}
        
        from cps.cwa_functions import parse_metadata_providers_enabled
        return parse_metadata_providers_enabled(
            settings.get('metadata_providers_enabled', '{}')
        )
    except Exception as e:
        # On any failure, treat as all enabled (empty dict = all default to enabled)
        log.warning(f"Error loading provider enabled map: {e}")
        return {}
    # Remove redundant return


# Helper to load the configured provider hierarchy from CWA settings (fork #405).
# The interactive search modal must present providers in the order the user
# configured — the same order the ingest auto-fetch in cps/metadata_helper.py
# obeys — falling back to alphabetical only for providers not named in the
# hierarchy. Returns the ordered list of provider ids.
def _get_provider_hierarchy() -> list:
    from .metadata_constants import (
        DEFAULT_METADATA_PROVIDER_HIERARCHY,
        DEFAULT_METADATA_PROVIDER_HIERARCHY_JSON,
    )
    try:
        sys.path.insert(1, '/app/calibre-web-automated/scripts/')
        from cwa_db import CWA_DB  # type: ignore
        settings = CWA_DB().get_cwa_settings() or {}
        hierarchy = json.loads(
            settings.get('metadata_provider_hierarchy', DEFAULT_METADATA_PROVIDER_HIERARCHY_JSON)
        )
        if not isinstance(hierarchy, list):
            raise ValueError("metadata_provider_hierarchy must be a list")
        return [p for p in hierarchy if isinstance(p, str)]
    except Exception as e:
        log.warning(f"Error loading provider hierarchy, using default: {e}")
        return list(DEFAULT_METADATA_PROVIDER_HIERARCHY)


def _hierarchy_sort_key(hierarchy: list):
    """Sort key: configured-hierarchy index first (providers not listed sort
    after all listed ones), then alphabetical by provider id for stability."""
    order = {pid: idx for idx, pid in enumerate(hierarchy)}
    big = len(order)

    def key(provider_id: str, name: str = ""):
        return (order.get(provider_id, big), (name or provider_id).lower())

    return key

# Providers that take a single API token / key plus the config column that
# stores it and a public signup URL. Used by the metadata-search modal's
# 🔑 Keys panel so users don't have to leave the modal to plug in a key.
PROVIDER_KEY_REGISTRY = {
    "hardcover": {
        "name":   "Hardcover",
        "config": "config_hardcover_token",
        "signup": "https://hardcover.app/account/api",
        "help":   "Free Hardcover account; click 'API Tokens' on your profile page.",
    },
    "google": {
        "name":   "Google Books",
        "config": "config_google_books_api_key",
        "signup": "https://console.cloud.google.com/apis/library/books.googleapis.com",
        "help":   "Enable 'Books API' in any Google Cloud project, then create an API key under Credentials.",
    },
    "goodreads": {
        "name":   "Goodreads",
        "config": "config_goodreads_api_key",
        "signup": "https://www.goodreads.com/api/keys",
        "help":   "Goodreads' developer API was discontinued in 2020. Existing keys still work for legacy integrations.",
    },
}


def _is_admin_user() -> bool:
    try:
        return bool(current_user.role_admin())
    except Exception:
        return False


@meta.route("/metadata/keys")
@user_login_required
def metadata_keys():
    """Return the API-key inventory for providers that support one.

    Never returns the actual key value — only whether a key is configured.
    Used to populate the modal's 🔑 Keys panel.
    """
    payload = []
    can_edit = _is_admin_user()
    for pid, spec in PROVIDER_KEY_REGISTRY.items():
        configured_value = getattr(config, spec["config"], None)
        payload.append({
            "id":         pid,
            "name":       spec["name"],
            "configured": bool(configured_value),
            "signup":     spec["signup"],
            "help":       spec["help"],
            "can_edit":   can_edit,
        })
    return make_response(jsonify(payload))


@meta.route("/metadata/cover/preview", methods=["POST"])
@user_login_required
def metadata_cover_preview():
    """Validate a cover URL the user pasted on the edit page (or in the
    cover-picker URL panel without a book scope). Same code path the
    save handler uses, so successful preview = successful save."""
    from cps.services.cover_url_validator import validate_cover_url
    body = request.get_json(silent=True) or {}
    result = validate_cover_url(body.get("url") or "")
    return make_response(jsonify(result.to_dict()))


@meta.route("/metadata/keys/<prov_id>", methods=["POST"])
@user_login_required
def metadata_keys_save(prov_id):
    """Set or clear a provider's API key. Admin-only."""
    if not _is_admin_user():
        return make_response(jsonify({"error": "admin required"}), 403)
    spec = PROVIDER_KEY_REGISTRY.get(prov_id)
    if not spec:
        return make_response(jsonify({"error": "unknown provider"}), 404)
    body = request.get_json(silent=True) or {}
    value = (body.get("value") or "").strip()
    try:
        setattr(config, spec["config"], value or None)
        config.save()
    except Exception as exc:
        log.error("Failed to save API key for %s: %s", prov_id, exc)
        return make_response(jsonify({"error": "save failed"}), 500)
    return make_response(jsonify({"id": prov_id, "configured": bool(value)}))


@meta.route("/metadata/provider")
@user_login_required
def metadata_provider():
    active = current_user.view_settings.get("metadata", {})
    global_enabled = _get_global_provider_enabled_map()
    provider = list()
    for c in cl:
        ac = active.get(c.__id__, True)
        provider.append(
            {
                "name": c.__name__,
                "active": ac,
                "initial": ac,
                "id": c.__id__,
                "globally_enabled": bool(global_enabled.get(c.__id__, True)),
            }
        )
    return make_response(jsonify(provider))


@meta.route("/metadata/provider", methods=["POST"])
@meta.route("/metadata/provider/<prov_name>", methods=["POST"])
@user_login_required
def metadata_change_active_provider(prov_name):
    new_state = request.get_json()
    active = current_user.view_settings.get("metadata", {})
    active[new_state["id"]] = new_state["value"]
    current_user.view_settings["metadata"] = active
    try:
        try:
            flag_modified(current_user, "view_settings")
        except AttributeError:
            pass
        ub.session.commit()
    except (InvalidRequestError, OperationalError):
        log.error("Invalid request received: {}".format(request))
        return "Invalid request", 400
    if "initial" in new_state and prov_name:
        data = []
        provider = next((c for c in cl if c.__id__ == prov_name), None)
        # Respect global disablement for preview search as well
        global_enabled = _get_global_provider_enabled_map()
        if provider is not None:
            if bool(global_enabled.get(provider.__id__, True)):
                try:
                    data = provider.search(new_state.get("query", ""))
                except Exception as exc:
                    log.warning("Metadata provider %s failed: %s", provider.__class__.__name__, exc)
                    data = []
            else:
                data = []
        if not data:
            return make_response(jsonify([]))
        return make_response(jsonify([asdict(x) for x in data if x]))
    return ""


def _classify_empty_provider(provider) -> tuple:
    """Decide why an enabled provider returned 0 results.

    Several providers fail silently (return [] without raising) when a
    required key is missing. We surface that to the UI as 'missing_key' so
    the user gets a "go set an API key" hint instead of a generic
    "no results" message.
    """
    pid = getattr(provider, "__id__", "")
    if pid == "hardcover":
        token = getattr(config, "config_hardcover_token", None)
        if not token:
            return ("missing_key",
                    "Set a Hardcover API key in Admin → Configuration → "
                    "Feature Configuration to enable this source.")
    if pid == "google":
        # Google returns [] both for no-results and for 429. We can't tell
        # from the wire, but if the user has no key configured then a 429 is
        # the dominant cause on shared IPs.
        if not getattr(config, "config_google_books_api_key", None):
            return ("empty",
                    "No matches. If this happens consistently, Google Books "
                    "may be rate-limiting your IP — set a Google Books API key "
                    "in Configuration to lift the quota.")
    return ("empty", "No results for this query")


def _classify_provider_failure(exc: Exception) -> tuple:
    """Map a provider exception to a (status, message) UI hint pair.

    Returns one of:
      ("blocked",       "...")  – upstream is actively refusing us (403/503)
      ("rate_limited",  "...")  – we hit a quota (429)
      ("missing_key",   "...")  – provider needs an API key we don't have
      ("error",         "...")  – everything else
    """
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    if "429" in text or "too many requests" in lowered or "quota" in lowered:
        return ("rate_limited", text)
    if "503" in text or "service unavailable" in lowered:
        return ("blocked", text)
    if "401" in text or "403" in text or "forbidden" in lowered or "unauthorized" in lowered:
        return ("missing_key", text)
    if "token missing" in lowered or "api key" in lowered:
        return ("missing_key", text)
    return ("error", text)


@meta.route("/metadata/search", methods=["POST"])
@user_login_required
def metadata_search():
    """Run all enabled providers in parallel and return a structured response.

    Response shape:
        {
          "results":   [ MetaRecord, ... ],   # flattened, dedup left to UI
          "providers": [
            { "id": "google",      "name": "Google",
              "status": "ok"|"empty"|"rate_limited"|"blocked"|"missing_key"|"error"|"disabled",
              "count":  <int>,
              "message": "<short, user-facing reason>",
              "duration_ms": <int> },
            ...
          ]
        }
    """
    query = request.form.to_dict().get("query")
    results: list = []
    provider_status: list = []
    active = current_user.view_settings.get("metadata", {})
    locale = get_locale()
    global_enabled = _get_global_provider_enabled_map()

    # Build the static "what each provider returned" structure first so the UI
    # can show a row even for providers we don't run (disabled per-user or
    # globally). This keeps modal copy stable across reload.
    runnable = {}
    for provider in cl:
        is_active = active.get(provider.__id__, True)
        is_global = bool(global_enabled.get(provider.__id__, True))
        if not is_active or not is_global:
            provider_status.append({
                "id": provider.__id__,
                "name": provider.__name__,
                "status": "disabled",
                "count": 0,
                "message": "Disabled" if is_active else "Off (per-user toggle)",
                "duration_ms": 0,
            })
            continue
        runnable[provider.__id__] = provider

    if not query or not runnable:
        return make_response(jsonify({"results": results, "providers": provider_status}))

    static_cover = url_for("static", filename="generic_cover.svg")

    import time
    started_at = {pid: time.monotonic() for pid in runnable}

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_provider = {
            executor.submit(copy_current_request_context(provider.search), query, static_cover, locale): provider
            for provider in runnable.values()
        }
        for future in concurrent.futures.as_completed(future_to_provider):
            provider = future_to_provider[future]
            elapsed_ms = int((time.monotonic() - started_at.get(provider.__id__, time.monotonic())) * 1000)
            try:
                provider_results = future.result() or []
            except Exception as exc:
                status, message = _classify_provider_failure(exc)
                log.warning(
                    "Metadata provider %s failed (%s) in %dms: %s",
                    provider.__class__.__name__, status, elapsed_ms, exc,
                )
                provider_status.append({
                    "id": provider.__id__,
                    "name": provider.__name__,
                    "status": status,
                    "count": 0,
                    "message": message,
                    "duration_ms": elapsed_ms,
                })
                continue
            results.extend([asdict(x) for x in provider_results if x])
            count = len(provider_results)
            status, message = ("ok", "") if count else _classify_empty_provider(provider)
            provider_status.append({
                "id": provider.__id__,
                "name": provider.__name__,
                "status": status,
                "count": count,
                "message": message,
                "duration_ms": elapsed_ms,
            })
    # Order provider rows by the configured hierarchy (fork #405) so the modal
    # presents providers in the order the user set — the same order the ingest
    # auto-fetch obeys — with alphabetical fallback for providers not listed.
    _hierarchy = _get_provider_hierarchy()
    _hkey = _hierarchy_sort_key(_hierarchy)
    provider_status.sort(key=lambda p: _hkey(p["id"], p["name"]))
    # Same ordering for the flattened results so the preferred provider's
    # matches lead; stable sort preserves each provider's internal order.
    _rank = {pid: idx for idx, pid in enumerate(_hierarchy)}
    _big = len(_rank)
    results.sort(key=lambda r: _rank.get((r.get("source") or {}).get("id"), _big))

    # Upgrade thumbnail-sized covers to high-DPI variants (Kobo Libra Color
    # etc.) by ISBN/title lookup against iTunes Search API. No-op when the
    # cover is already known to be high-res or no ISBN/title match exists.
    try:
        boost_covers(results)
    except Exception as exc:  # pragma: no cover - defensive: never break search
        log.warning("cover boost pass failed: %s", exc)

    return make_response(jsonify({"results": results, "providers": provider_status}))

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
import threading
import time

try:
    from gevent import sleep as _metadata_sleep
except ImportError:
    # The threaded server does not require gevent.
    _metadata_sleep = time.sleep

from flask import Blueprint, request, url_for, make_response, jsonify, copy_current_request_context
from .cw_login import current_user
from flask_babel import get_locale
from sqlalchemy.exc import InvalidRequestError, OperationalError
from sqlalchemy.orm.attributes import flag_modified

from cps.services.Metadata import Metadata
from . import constants, logger, ub, web_server
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
                data = _metadata_search_providers([provider], new_state.get("query", ""))
            else:
                data = []
        if not data:
            return make_response(jsonify([]))
        return make_response(jsonify(data))
    return ""


# Reuse native workers; never wait for executor shutdown in a WSGI greenlet.
_METADATA_MAX_WORKERS = 5
_METADATA_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=_METADATA_MAX_WORKERS)
_METADATA_SLOTS = threading.BoundedSemaphore(_METADATA_MAX_WORKERS)
_METADATA_TIMEOUT = 15.0


def _metadata_search_providers(providers, *args):
    # One deadline includes waiting for capacity across concurrent requests.
    deadline = time.monotonic() + _METADATA_TIMEOUT
    pending = iter(providers)
    provider = next(pending, None)
    futures = {}
    data = []
    try:
        while provider is not None or futures:
            for future in list(futures):
                if not future.done():
                    continue
                completed_provider = futures.pop(future)
                try:
                    result = future.result()
                    if result:
                        data.extend(asdict(x) for x in result if x)
                except Exception as exc:
                    log.warning("Metadata provider %s failed: %s",
                                completed_provider.__class__.__name__, exc)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            while provider is not None and _METADATA_SLOTS.acquire(blocking=False):
                try:
                    # Each task owns a separate Flask request context.
                    search = copy_current_request_context(provider.search)
                    future = _METADATA_EXECUTOR.submit(search, *args)
                except BaseException:
                    _METADATA_SLOTS.release()
                    raise
                # Timed-out tasks keep their slot until they actually terminate.
                future.add_done_callback(lambda done: _METADATA_SLOTS.release())
                futures[future] = provider
                provider = next(pending, None)
                if time.monotonic() >= deadline:
                    break
            if provider is not None or futures:
                # Future.wait/as_completed use native locks without monkey patching.
                _metadata_sleep(min(0.01, max(0, deadline - time.monotonic())))
    finally:
        # Cancellation only stops tasks which have not started. Running threads
        # cannot be killed safely; bound them globally and never join them here.
        for future in futures:
            future.cancel()
    return data


@meta.route("/metadata/search", methods=["POST"])
@user_login_required
def metadata_search():
    query = request.form.to_dict().get("query")
    data = list()
    active = current_user.view_settings.get("metadata", {})
    locale = get_locale()
    global_enabled = _get_global_provider_enabled_map()
    if query:
        static_cover = url_for("static", filename="generic_cover.svg")
        providers = [c for c in cl
                     if active.get(c.__id__, True) and bool(global_enabled.get(c.__id__, True))]
        data = _metadata_search_providers(providers, query, static_cover, locale)
    return  make_response(jsonify(data))

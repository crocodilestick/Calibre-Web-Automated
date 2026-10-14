"""Execute the real metadata routes without application startup, DB or network.

AST isolation follows the repository's regression-test convention, but executes
handlers and helpers instead of checking their source text. Only authentication,
provider discovery and database persistence are replaced.
"""
import ast
import concurrent.futures
from dataclasses import asdict, dataclass
import logging
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from flask import (Flask, copy_current_request_context, current_app, jsonify,
                   make_response, request, url_for)

gevent = pytest.importorskip("gevent")
pytestmark = pytest.mark.unit


@dataclass
class Result:
    title: str = "Synthetic result"


class Provider:
    __id__ = "fake"

    def __init__(self, search):
        self.search = search


@pytest.fixture
def routes():
    tree = ast.parse((Path(__file__).resolve().parents[2] /
                      "cps/search_metadata.py").read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and (
                node.name in {"metadata_search", "metadata_change_active_provider"}
                or node.name.startswith("_metadata_")):
            node.decorator_list = []
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id.startswith("_METADATA_")
                for target in node.targets):
            nodes.append(node)
    namespace: dict = dict(concurrent=concurrent, threading=threading, time=time,
                     _metadata_sleep=gevent.sleep, asdict=asdict,
                     request=request, url_for=url_for, make_response=make_response,
                     jsonify=jsonify, copy_current_request_context=copy_current_request_context,
                     current_user=SimpleNamespace(view_settings={}),
                     get_locale=lambda: "en", _get_global_provider_enabled_map=lambda: {},
                     log=logging.getLogger(__name__), cl=[],
                     flag_modified=lambda *args: None,
                     ub=SimpleNamespace(session=SimpleNamespace(commit=lambda: None)),
                     InvalidRequestError=type("InvalidRequestError", (Exception,), {}),
                     OperationalError=type("OperationalError", (Exception,), {}))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "search_metadata.py", "exec"), namespace)
    app = Flask(__name__)
    app.config["TEST_SENTINEL"] = "copied context"
    app.add_url_rule("/metadata/search", view_func=namespace["metadata_search"], methods=["POST"])
    app.add_url_rule("/metadata/provider/<prov_name>", view_func=namespace["metadata_change_active_provider"], methods=["POST"])
    yield app, namespace
    executor = namespace.get("_METADATA_EXECUTOR")
    if executor:
        # Test providers always terminate; production must not wait on timeout.
        executor.shutdown(wait=True)
        assert all(not thread.is_alive() for thread in executor._threads)
        slots = namespace.get("_METADATA_SLOTS")
        if slots:
            for _ in range(namespace["_METADATA_MAX_WORKERS"]):
                assert slots.acquire(blocking=False), "worker capacity leaked"
            assert not slots.acquire(blocking=False)
            for _ in range(namespace["_METADATA_MAX_WORKERS"]):
                slots.release()


def post(app, preview=False):
    with app.test_client() as client:
        if preview:
            return client.post("/metadata/provider/fake", json={
                "id": "fake", "value": True, "initial": True, "query": "synthetic"})
        return client.post("/metadata/search", data={"query": "synthetic"})


def heartbeat_request(app, preview=False):
    ticks = []

    def heartbeat():
        while True:
            ticks.append(time.monotonic())
            gevent.sleep(0.005)

    beat = gevent.spawn(heartbeat)
    gevent.sleep(0.01)
    try:
        response = gevent.spawn(post, app, preview).get(timeout=3)
        gevent.sleep(0.01)
    finally:
        beat.kill()
    gap = max(b - a for a, b in zip(ticks, ticks[1:]))
    return response, gap


def test_search_keeps_unpatched_gevent_heartbeat_running(routes):
    app, ns = routes

    def slow(*args):
        from gevent import monkey
        assert not monkey.is_module_patched("time")
        assert not monkey.is_module_patched("threading")
        time.sleep(0.3)
        return [Result()]

    ns["cl"] = [Provider(slow)]
    response, gap = heartbeat_request(app)
    assert response.get_json() == [{"title": "Synthetic result"}]
    print(f"heartbeat maximum gap: {gap:.3f}s")
    assert gap < 0.1


def test_preview_keeps_unpatched_gevent_heartbeat_running(routes):
    app, ns = routes

    def slow(query):
        assert query == "synthetic"
        time.sleep(0.3)
        return [Result()]

    ns["cl"] = [Provider(slow)]
    response, gap = heartbeat_request(app, preview=True)
    assert response.get_json() == [{"title": "Synthetic result"}]
    assert gap < 0.1


@pytest.mark.parametrize("preview", [False, True])
def test_request_deadline_returns_without_waiting_for_slow_provider(routes, preview):
    app, ns = routes
    ns["_METADATA_TIMEOUT"] = 0.08

    def slow(*args):
        time.sleep(0.35)
        return [Result("Too late")]

    ns["cl"] = [Provider(slow)]
    if not preview:
        fast = Provider(lambda *args: [Result("Partial")])
        fast.__id__ = "fast"
        ns["cl"].append(fast)
    start = time.monotonic()
    response = post(app, preview)
    elapsed = time.monotonic() - start
    assert elapsed < 0.22
    assert response.get_json() == ([] if preview else [{"title": "Partial"}])


def test_timed_out_requests_do_not_accumulate_queued_work_or_threads(routes):
    app, ns = routes
    ns["_METADATA_TIMEOUT"] = 0.02
    release = threading.Event()
    submitted = []
    real_copy = copy_current_request_context

    def track_copy(function):
        submitted.append(function)
        return real_copy(function)

    def blocked(*args):
        assert release.wait(3), "test must release its workers"
        return [Result()]

    ns["copy_current_request_context"] = track_copy
    ns["cl"] = [Provider(blocked) for _ in range(8)]
    try:
        for _ in range(8):
            assert post(app).get_json() == []
        assert len(submitted) <= 5, "timed-out workers must retain capacity until they finish"
    finally:
        release.set()
    # Slots must recover after workers finish, without replacing the executor.
    gevent.sleep(0.05)
    ns["cl"] = [Provider(lambda *args: [Result()])]
    assert post(app).get_json() == [{"title": "Synthetic result"}]


@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("behavior", ["none", "empty", "error", "null_item"])
def test_provider_empty_results_and_failures_are_isolated(routes, preview, behavior, caplog):
    app, ns = routes

    def search(*args):
        if behavior == "error":
            raise ValueError("synthetic provider error")
        return {"none": None, "empty": [], "null_item": [None, Result()]}[behavior]

    ns["cl"] = [Provider(search)]
    response = post(app, preview)
    assert response.status_code == 200
    assert response.get_json() == ([{"title": "Synthetic result"}] if behavior == "null_item" else [])
    if behavior == "error":
        assert "synthetic provider error" in caplog.text


@pytest.mark.parametrize("preview", [False, True])
def test_provider_has_its_own_flask_request_context(routes, preview):
    app, ns = routes
    caller_thread = threading.get_ident()

    def search(query, *args):
        assert threading.get_ident() != caller_thread
        assert current_app.config["TEST_SENTINEL"] == "copied context"
        assert request.path == ("/metadata/provider/fake" if preview else "/metadata/search")
        assert query == "synthetic"
        if not preview:
            assert args == ("/static/generic_cover.svg", "en")
        return [Result()]

    ns["cl"] = [Provider(search)]
    assert post(app, preview).get_json() == [{"title": "Synthetic result"}]


def test_single_deadline_includes_all_provider_batches(routes):
    app, ns = routes
    ns["_METADATA_TIMEOUT"] = 0.08

    def slow(*args):
        time.sleep(0.35)
        return [Result()]

    ns["cl"] = [Provider(slow) for _ in range(20)]
    start = time.monotonic()
    assert post(app).get_json() == []
    assert time.monotonic() - start < 0.22


def test_global_and_user_disablement_are_respected(routes):
    app, ns = routes

    def unexpected(*args):
        pytest.fail("disabled provider was invoked")

    ns["cl"] = [Provider(unexpected)]
    ns["current_user"].view_settings = {"metadata": {"fake": False}}
    assert post(app).get_json() == []
    ns["current_user"].view_settings = {}
    ns["_get_global_provider_enabled_map"] = lambda: {"fake": False}
    assert post(app).get_json() == []
    assert post(app, preview=True).get_json() == []


def test_threaded_server_fallback_without_gevent(routes, monkeypatch):
    app, ns = routes
    tree = ast.parse((Path(__file__).resolve().parents[2] /
                      "cps/search_metadata.py").read_text(encoding="utf-8"))
    sleep_import = next(node for node in tree.body if isinstance(node, ast.Try)
                        and any(isinstance(child, ast.ImportFrom) and child.module == "gevent"
                                for child in ast.walk(node)))
    monkeypatch.setitem(sys.modules, "gevent", None)
    exec(compile(ast.Module(body=[sleep_import], type_ignores=[]), "search_metadata.py", "exec"), ns)
    assert ns["_metadata_sleep"] is time.sleep
    ns["cl"] = [Provider(lambda *args: [Result()])]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as clients:
        responses = list(clients.map(lambda _: post(app), range(6)))
    assert all(response.get_json() == [{"title": "Synthetic result"}] for response in responses)


def test_concurrent_search_and_preview_share_worker_limit(routes):
    app, ns = routes
    active = 0
    peak = 0
    lock = threading.Lock()

    def slow(*args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.04)
            return [Result()]
        finally:
            with lock:
                active -= 1

    ns["cl"] = [Provider(slow)]
    jobs = [gevent.spawn(post, app, bool(index % 2)) for index in range(12)]
    gevent.joinall(jobs, timeout=3, raise_error=True)
    assert all(job.ready() and job.value.get_json() == [{"title": "Synthetic result"}] for job in jobs)
    assert 1 < peak <= 5
    assert len(ns["_METADATA_EXECUTOR"]._threads) <= 5


def test_submission_failure_does_not_leak_capacity(routes, monkeypatch):
    app, ns = routes
    ns["cl"] = [Provider(lambda *args: [Result()])]
    executor = ns["_METADATA_EXECUTOR"]
    submit = executor.submit

    def fail(*args):
        raise RuntimeError("synthetic submission failure")

    monkeypatch.setattr(executor, "submit", fail)
    app.testing = True
    with pytest.raises(RuntimeError, match="synthetic submission failure"):
        post(app)
    monkeypatch.setattr(executor, "submit", submit)
    assert post(app).get_json() == [{"title": "Synthetic result"}]
    slots = ns["_METADATA_SLOTS"]
    for _ in range(5):
        assert slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)
    for _ in range(5):
        slots.release()

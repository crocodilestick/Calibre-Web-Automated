import types

from cps import app
import cps.admin as admin
import cps.shelf as shelf_module
import cps.web as web


class DummySession:
    def __init__(self):
        self.added = []
        self.committed = False
        self.rolled_back = False

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class QueryResult:
    def __init__(self, items=None, first=None, count_value=None, get_value=None):
        self._items = items or []
        self._first = first
        self._count_value = count_value
        self._get_value = get_value

    def filter(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
        return self

    def all(self):
        return list(self._items)

    def first(self):
        return self._first

    def count(self):
        return self._count_value if self._count_value is not None else len(self._items)

    def get(self, _value):
        return self._get_value

    def delete(self):
        return None


def test_edit_shelf_does_not_change_opds_exposure_when_checkbox_hidden(monkeypatch):
    shelf = types.SimpleNamespace(id=5, uuid="abc", kobo_sync=False)
    session = DummySession()
    calls = []
    monkeypatch.setattr(shelf_module.ub, "session", session)
    monkeypatch.setattr(shelf_module.ub, "is_opds_shelf_exposed_for_user", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(shelf_module.ub, "set_opds_shelf_exposed_for_user", lambda *args, **_kwargs: calls.append(args))
    monkeypatch.setattr(shelf_module, "current_user", types.SimpleNamespace(
        id=1,
        kobo_only_shelves_sync=0,
        opds_only_shelves_sync=0,
        role_edit_shelfs=lambda: True,
    ))
    monkeypatch.setattr(shelf_module.config, "config_kobo_sync", False, raising=False)
    monkeypatch.setattr(shelf_module, "check_shelf_is_unique", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(shelf_module, "flash", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(shelf_module, "redirect", lambda location: location)
    monkeypatch.setattr(shelf_module, "url_for", lambda *_args, **kwargs: f"/shelf/{kwargs['shelf_id']}")
    monkeypatch.setattr(shelf_module, "_", lambda value, **kwargs: value % kwargs if kwargs else value)

    with app.test_request_context("/shelf/5/edit", method="POST", data={"title": "Shelf Name"}):
        shelf_module.create_edit_shelf(shelf, "Edit Shelf", "shelf", shelf_id=5)

    assert calls == []


def test_edit_shelf_updates_current_users_opds_exposure(monkeypatch):
    shelf = types.SimpleNamespace(id=5, uuid="abc", kobo_sync=False)
    session = DummySession()
    calls = []
    monkeypatch.setattr(shelf_module.ub, "session", session)
    monkeypatch.setattr(shelf_module.ub, "is_opds_shelf_exposed_for_user", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(shelf_module.ub, "set_opds_shelf_exposed_for_user", lambda *args, **_kwargs: calls.append(args))
    monkeypatch.setattr(shelf_module, "current_user", types.SimpleNamespace(
        id=1,
        kobo_only_shelves_sync=0,
        opds_only_shelves_sync=1,
        role_edit_shelfs=lambda: True,
    ))
    monkeypatch.setattr(shelf_module.config, "config_kobo_sync", False, raising=False)
    monkeypatch.setattr(shelf_module, "check_shelf_is_unique", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(shelf_module, "flash", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(shelf_module, "redirect", lambda location: location)
    monkeypatch.setattr(shelf_module, "url_for", lambda *_args, **kwargs: f"/shelf/{kwargs['shelf_id']}")
    monkeypatch.setattr(shelf_module, "_", lambda value, **kwargs: value % kwargs if kwargs else value)

    with app.test_request_context("/shelf/5/edit", method="POST", data={"title": "Shelf Name", "opds_expose": "on"}):
        shelf_module.create_edit_shelf(shelf, "Edit Shelf", "shelf", shelf_id=5)

    assert calls == [(1, 5, True)]


def test_change_profile_updates_opds_only_shelves_sync(monkeypatch):
    current_user = types.SimpleNamespace(
        id=7,
        name="tester",
        email="user@example.com",
        kindle_mail="",
        kindle_mail_subject="",
        default_language="all",
        locale="en",
        random_books=0,
        kobo_only_shelves_sync=0,
        opds_only_shelves_sync=0,
        hardcover_token=None,
        auto_send_enabled=False,
        auto_metadata_fetch=False,
        allow_additional_ereader_emails=False,
        amazon_region="",
        is_anonymous=False,
        sidebar_view=0,
        view_settings={},
        role_passwd=lambda: False,
        role_admin=lambda: False,
    )

    class SessionStub(DummySession):
        def query(self, entity):
            return QueryResult(items=[])

    session = SessionStub()
    monkeypatch.setattr(web, "current_user", current_user)
    monkeypatch.setattr(web.ub, "session", session)
    monkeypatch.setattr(web, "valid_email", lambda value: value)
    monkeypatch.setattr(web, "check_email", lambda value: value)
    monkeypatch.setattr(web.kobo_sync_status, "update_on_sync_shelfs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(web, "flag_modified", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(web, "flash", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(web, "redirect", lambda location: location)
    monkeypatch.setattr(web, "url_for", lambda *_args, **_kwargs: "/me")
    monkeypatch.setattr(web, "_", lambda value, **kwargs: value % kwargs if kwargs else value)

    with app.test_request_context("/me", method="POST", data={"email": "user@example.com", "default_language": "all", "opds_only_shelves_sync": "on"}):
        web.change_profile(False, False, {}, None, [], [])

    assert current_user.opds_only_shelves_sync == 1
    assert session.committed is True


def test_create_magic_shelf_persists_opds_expose(monkeypatch):
    session = DummySession()
    current_user = types.SimpleNamespace(id=3, role_edit_shelfs=lambda: True, opds_only_shelves_sync=1)
    calls = []
    monkeypatch.setattr(web, "current_user", current_user)
    monkeypatch.setattr(web, "strip_whitespaces", lambda value: value.strip())
    monkeypatch.setattr(web, "jsonify", lambda payload: types.SimpleNamespace(get_json=lambda: payload))
    monkeypatch.setattr(web, "_", lambda value, **_kwargs: value)

    def fake_commit():
        session.committed = True
        if session.added:
            session.added[-1].id = 99

    session.flush = fake_commit

    monkeypatch.setattr(web, "ub", types.SimpleNamespace(
        MagicShelf=web.ub.MagicShelf,
        session=session,
        session_commit=fake_commit,
        set_opds_magic_shelf_exposed_for_user=lambda *args, **_kwargs: calls.append(args),
    ))

    with app.test_request_context("/magicshelf/create", method="POST", json={"name": "Magic", "rules": {"rules": [1]}, "opds_expose": True}):
        response = web.create_magic_shelf.__wrapped__()

    assert response.get_json()["success"] is True
    assert calls == [(3, 99, True)]


def test_edit_magic_shelf_updates_opds_expose(monkeypatch):
    shelf = types.SimpleNamespace(id=12, user_id=4, name="Magic", rules={"rules": [1]}, icon="🪄", kobo_sync=False, is_public=0)
    current_user = types.SimpleNamespace(id=4, role_admin=lambda: False, role_edit_shelfs=lambda: True, opds_only_shelves_sync=1)
    calls = []

    class SessionStub(DummySession):
        def query(self, entity):
            if entity is web.ub.MagicShelf:
                return QueryResult(get_value=shelf)
            if entity is web.ub.MagicShelfCache:
                return QueryResult()
            raise AssertionError(f"Unexpected entity: {entity}")

    session = SessionStub()
    monkeypatch.setattr(web, "current_user", current_user)
    monkeypatch.setattr(web, "strip_whitespaces", lambda value: value.strip())
    monkeypatch.setattr(web, "flag_modified", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(web, "jsonify", lambda payload: types.SimpleNamespace(get_json=lambda: payload))
    monkeypatch.setattr(web, "_", lambda value, **_kwargs: value)
    monkeypatch.setattr(web, "ub", types.SimpleNamespace(
        MagicShelf=web.ub.MagicShelf,
        MagicShelfCache=web.ub.MagicShelfCache,
        session=session,
        session_commit=lambda: setattr(session, "committed", True),
        is_opds_magic_shelf_exposed_for_user=lambda *_args, **_kwargs: False,
        set_opds_magic_shelf_exposed_for_user=lambda *args, **_kwargs: calls.append(args),
    ))

    with app.test_request_context("/magicshelf/12/edit", method="POST", json={"name": "Magic", "rules": {"rules": [1]}, "opds_expose": True}):
        response = web.edit_magic_shelf.__wrapped__(12)

    assert response.get_json()["success"] is True
    assert calls == [(4, 12, True)]


def test_handle_new_user_sets_opds_only_shelves_sync(monkeypatch):
    content = admin.ub.User()
    content.locale = "en"
    session = DummySession()
    monkeypatch.setattr(admin.constants, "selected_roles", lambda *_args, **_kwargs: 0, raising=False)
    monkeypatch.setattr(admin.helper, "valid_password", lambda value: value)
    monkeypatch.setattr(admin, "generate_password_hash", lambda value: f"hashed-{value}")
    monkeypatch.setattr(admin, "check_email", lambda value: value)
    monkeypatch.setattr(admin, "check_username", lambda value: value)
    monkeypatch.setattr(admin, "check_valid_domain", lambda value: True)
    monkeypatch.setattr(admin, "flash", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(admin, "redirect", lambda location: location)
    monkeypatch.setattr(admin, "url_for", lambda *_args, **_kwargs: "/admin")
    monkeypatch.setattr(admin, "_", lambda value, **kwargs: value % kwargs if kwargs else value)
    monkeypatch.setattr(admin.ub, "session", session)
    monkeypatch.setattr(admin.config, "config_public_reg", False, raising=False)
    monkeypatch.setattr(admin.config, "config_allowed_tags", [], raising=False)
    monkeypatch.setattr(admin.config, "config_denied_tags", [], raising=False)
    monkeypatch.setattr(admin.config, "config_allowed_column_value", [], raising=False)
    monkeypatch.setattr(admin.config, "config_denied_column_value", [], raising=False)

    with app.test_request_context("/admin/new", method="POST"):
        admin._handle_new_user(
            {"default_language": "all", "name": "user", "email": "user@example.com", "password": "secret", "opds_only_shelves_sync": "on"},
            content,
            [],
            [],
            False,
        )

    assert content.opds_only_shelves_sync is True
    assert session.committed is True

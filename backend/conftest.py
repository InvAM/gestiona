import pytest
from django.contrib.auth import get_user_model


@pytest.fixture(autouse=True)
def _test_settings(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    from config.celery import app

    app.conf.task_always_eager = True
    # LocMemCache keeps its data across tests while the DB rolls back: start clean so
    # cached field rules (apps/issues/fieldrules.py) never outlive the test that built them.
    from django.core.cache import cache

    cache.clear()
    from apps.issues import fieldrules

    fieldrules._local.clear()


@pytest.fixture
def make_user(db):
    User = get_user_model()
    counter = {"n": 0}

    def make(**kw):
        counter["n"] += 1
        kw.setdefault("email", f"user{counter['n']}@test.local")
        kw.setdefault("full_name", f"Usuario {counter['n']}")
        return User.objects.create_user(password="clave-segura-123", **kw)

    return make


@pytest.fixture
def admin(make_user):
    return make_user(email="admin@test.local", full_name="Admin", is_staff=True)


@pytest.fixture
def member(make_user):
    return make_user(email="member@test.local", full_name="Miembro Uno")


@pytest.fixture
def outsider(make_user):
    return make_user(email="outsider@test.local", full_name="Externo")


@pytest.fixture
def project(admin, member):
    from apps.projects.models import Role
    from apps.projects.services import create_project, set_member

    p = create_project(admin, name="Gestiona Core", key="GES", template="scrum")
    set_member(admin, p, member.id, Role.objects.get(name="Miembro").id)
    return p


@pytest.fixture
def types():
    from apps.issues.models import IssueType

    return {t.name: t for t in IssueType.objects.all()}


@pytest.fixture
def make_issue(project, admin, types):
    from apps.issues.services import IssueInput, create_issue

    def make(summary="Tarea", type_name="Tarea", actor=None, **kw):
        return create_issue(actor or admin, kw.pop("project", project),
                            IssueInput(issue_type_id=types[type_name].id, summary=summary, **kw))

    return make


@pytest.fixture
def api(client):
    """Django test client logged in helper; JSON by default."""

    class Api:
        def __init__(self):
            self.c = client

        def login(self, user):
            self.c.force_login(user)
            return self

        def _call(self, method, url, data=None, **kw):
            fn = getattr(self.c, method)
            if data is not None and method != "get":
                kw.setdefault("content_type", "application/json")
            return fn(f"/api/v1{url}", data=data, **kw)

        def get(self, url, **kw):
            return self._call("get", url, kw or None)

        def post(self, url, data=None, **kw):
            return self._call("post", url, data if data is not None else {}, **kw)

        def patch(self, url, data=None):
            return self._call("patch", url, data or {})

        def put(self, url, data=None):
            return self._call("put", url, data if data is not None else {})

        def delete(self, url):
            return self.c.delete(f"/api/v1{url}")

    return Api()

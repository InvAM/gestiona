"""Guard against static API routes being shadowed by an earlier `/{param}` route
(e.g. `/issues/{key}` declared before `/issues/rank` turns POST /issues/rank into a 405)."""

from django.urls import resolve


def _static_paths():
    from config.api import api

    paths = []
    for prefix, router in api._routers:
        for path in router.path_operations:
            full = f"{prefix.strip('/')}/{path.lstrip('/')}".strip("/")
            if "{" not in full:
                paths.append(full)
    return paths


def test_static_routes_are_not_shadowed():
    paths = _static_paths()
    assert len(paths) > 20
    shadowed = [p for p in paths if "<" in resolve(f"/api/v1/{p}").route]
    assert shadowed == []


def test_schema_names_are_unique():
    """Ninja names OpenAPI components by class name: two different `FooIn` classes silently
    overwrite each other in the generated TypeScript types."""
    import importlib
    import inspect

    from ninja import Schema

    seen: dict[str, str] = {}
    dupes = []
    for app in ("accounts", "projects", "issues", "boards", "search", "notifications",
                "workflows", "imports", "automation", "dashboards", "audit", "forms", "ai", "core",
                "plans", "listview", "analytics"):
        mods = []
        for sub in ("api", "schemas", "meta", "fields_api"):
            try:
                mods.append(importlib.import_module(f"apps.{app}.{sub}"))
            except ModuleNotFoundError:
                pass
        for mod in mods:
            for name, obj in vars(mod).items():
                own = inspect.isclass(obj) and issubclass(obj, Schema) and \
                    obj.__module__ == mod.__name__
                if own:
                    if name in seen and seen[name] != obj.__module__:
                        dupes.append(f"{name}: {seen[name]} / {obj.__module__}")
                    seen[name] = obj.__module__
    assert dupes == []

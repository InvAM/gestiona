"""ORDER BY of sprint, parent, labels and custom fields (Jira semantics).

EMPTY is the greatest value: last in ASC, first in DESC. Ties are broken by id (the search
appends `-id`), so every order here is fully deterministic.
"""

from datetime import UTC, datetime, timedelta

import pytest

from apps.issues.models import CustomField, Issue
from apps.search.jql import JQLError, search_issues

pytestmark = pytest.mark.django_db


def ordered(user, jql):
    return [i.key for i in search_issues(user, jql)]


def keyset(issues):
    return ", ".join(i.key for i in issues)


def check(user, issues, sort, expected_asc, empties=()):
    """`expected_asc`: issues with a value, in ASC order; `empties` sort last in ASC and
    first in DESC, among themselves by id descending (the search's tie-break)."""
    jql = f"key in ({keyset(issues)}) ORDER BY {sort}"
    tail = sorted(empties, key=lambda i: -i.id)
    asc = [i.key for i in [*expected_asc, *tail]]
    desc = [i.key for i in [*tail, *reversed(expected_asc)]]
    assert ordered(user, f"{jql} ASC") == asc, sort
    assert ordered(user, jql) == asc, sort  # ASC is the default
    assert ordered(user, f"{jql} DESC") == desc, sort


def set_cf(issue, values: dict):
    Issue.objects.filter(pk=issue.pk).update(custom_fields=values)


# --------------------------------------------------------------------------- system fields

def test_sprint_orders_by_start_date_then_id(admin, project, make_issue):
    from apps.boards.models import Board, Sprint

    board = Board.objects.filter(project=project).first()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    # created out of order so id and start date disagree
    late = Sprint.objects.create(board=board, name="Tardío", state="closed",
                                 start_date=t0 + timedelta(days=30))
    early = Sprint.objects.create(board=board, name="Temprano", state="active",
                                  start_date=t0)
    future_a = Sprint.objects.create(board=board, name="Futuro A")
    future_b = Sprint.objects.create(board=board, name="Futuro B")
    issues = {}
    for name, sprint in [("late", late), ("early", early), ("fa", future_a),
                         ("fb", future_b), ("early2", early), ("none", None)]:
        i = make_issue(name)
        Issue.objects.filter(pk=i.pk).update(sprint=sprint)
        issues[name] = i
    i = issues
    check(admin, [i[k] for k in ("late", "early", "fa", "fb", "none")], "sprint",
          [i["early"], i["late"], i["fa"], i["fb"]], empties=[i["none"]])
    # same sprint → id descending in both directions (stable tie-break)
    pair = f"key in ({keyset([i['early'], i['early2']])}) ORDER BY sprint"
    assert ordered(admin, pair) == ordered(admin, f"{pair} DESC") == [
        i["early2"].key, i["early"].key]


def test_parent_orders_by_natural_key(admin, project, make_issue):
    created = [make_issue(f"I{n}", type_name="Épica" if n in (2, 10) else "Tarea")
               for n in range(1, 11)]
    epic2, epic10 = created[1], created[9]
    assert (epic2.key, epic10.key) == ("GES-2", "GES-10")
    child10 = make_issue("Hija de 10", type_name="Historia", parent_id=epic10.id)
    child2 = make_issue("Hija de 2", type_name="Historia", parent_id=epic2.id)
    loose = make_issue("Sin principal", type_name="Historia")
    for alias in ("parent", "principal", '"epic link"'):
        check(admin, [child10, child2, loose], alias, [child2, child10], empties=[loose])
    # the key itself is natural too
    assert ordered(admin, "key in (GES-10, GES-2, GES-9) ORDER BY key") == [
        "GES-2", "GES-9", "GES-10"]
    assert ordered(admin, "key in (GES-10, GES-2, GES-9) ORDER BY key DESC") == [
        "GES-10", "GES-9", "GES-2"]


def test_labels_order_by_first_label_case_insensitive(admin, make_issue):
    zulu = make_issue("Z", labels=["Zulu"])
    alfa = make_issue("A", labels=["alfa", "zeta"])
    beta = make_issue("B", labels=["zeta", "Beta"])  # first alphabetically, not first stored
    none = make_issue("N")
    none2 = make_issue("N2", labels=[])
    for alias in ("labels", "etiquetas"):
        check(admin, [zulu, alfa, beta, none, none2], alias, [alfa, beta, zulu],
              empties=[none, none2])


def test_empty_values_follow_jira_for_plain_fields_too(admin, make_issue):
    a = make_issue("A", story_points=3)
    b = make_issue("B", story_points=8)
    c = make_issue("C")
    check(admin, [a, b, c], '"story points"', [a, b], empties=[c])


# --------------------------------------------------------------------------- custom fields

OPTIONS = [{"id": "lo", "value": "Zeta baja"}, {"id": "mid", "value": "Alfa media"},
           {"id": "hi", "value": "Media alta"},
           {"id": "old", "value": "Antigua", "deleted": True}]


@pytest.fixture
def people(make_user):
    return {
        "ana": make_user(full_name="ana"),
        "bruno": make_user(full_name="Bruno"),
        "carla": make_user(full_name="Carla"),
        # no full name: the display name is the e-mail's local part
        "dora": make_user(full_name="", email="dora@test.local"),
    }


def kind_cases(p):
    """kind → (values in ASC order, values that sort as EMPTY)."""
    return {
        "number": ([-1, 2.5, 10, 100], ["abc", [1], None]),
        "date": (["2025-12-31", "2026-01-09", "2026-01-10"], ["2026-02-30", "mañana", None]),
        "datetime": (["2026-01-01T10:00:00+00:00", "2026-01-01T11:00:00Z",
                      "2026-01-01T09:00:00-03:00"], ["ayer", None]),
        "text": (["Alfa", "beta", "Gamma"], ["", "   ", None]),
        "textarea": (["alfa", "Beta", "gamma"], ["", None]),
        "url": (["https://a.example", "HTTPS://B.example", "https://c.example"], [None]),
        # option position (lo, mid, hi, old), not the label (Alfa, Antigua, Media, Zeta)
        "select": (["lo", "mid", "hi", "old"], ["borrada", ["lo"], None]),
        "multiselect": ([["hi", "lo"], ["hi", "mid"], ["hi"]], [[], "lo", None]),
        "checkbox": ([["mid", "lo"], ["old", "mid"], ["hi"]], [[], None]),
        "labels": ([["zeta", "Alfa"], ["beta"], ["Gamma", "omega"]], [[], None]),
        "user": ([p["ana"].id, p["bruno"].id, p["carla"].id, p["dora"].id],
                 [999999, "x", None]),
        "multiuser": ([[p["carla"].id, p["ana"].id], [p["bruno"].id],
                       [p["dora"].id, 999999]], [[], [999999], None]),
    }


def test_every_custom_field_kind_has_a_sort(admin, people, make_issue):
    cases = kind_cases(people)
    assert set(cases) == set(CustomField.Kind.values)  # a new kind needs a case here
    for kind, (values, empties) in cases.items():
        cf = CustomField.objects.create(name=f"Campo {kind}", kind=kind, options=OPTIONS)
        with_value, without = [], []
        # create in reverse so ids disagree with the expected order
        for v in reversed(values):
            i = make_issue(f"{kind} {v}")
            set_cf(i, {str(cf.id): v})
            with_value.insert(0, i)
        for v in empties:
            i = make_issue(f"{kind} vacío")
            if v is not None:
                set_cf(i, {str(cf.id): v})
            without.append(i)
        issues = with_value + without
        check(admin, issues, f"cf[{cf.id}]", with_value, empties=without)
        check(admin, issues, f'"Campo {kind}"', with_value, empties=without)  # by name


def test_custom_field_sort_combines_with_other_keys(admin, make_issue):
    cf = CustomField.objects.create(name="Equipo QA", kind="select", options=OPTIONS)
    a = make_issue("A", story_points=1)
    b = make_issue("B", story_points=2)
    c = make_issue("C", story_points=3)
    for i, v in ((a, "hi"), (b, "lo"), (c, "lo")):
        set_cf(i, {str(cf.id): v})
    jql = f'key in ({keyset([a, b, c])}) ORDER BY cf[{cf.id}] ASC, "story points" DESC'
    assert ordered(admin, jql) == [c.key, b.key, a.key]


def test_unknown_or_deleted_custom_fields(admin, make_issue):
    i = make_issue("A")
    with pytest.raises(JQLError):
        ordered(admin, "ORDER BY cf[999999]")
    with pytest.raises(JQLError):
        ordered(admin, 'ORDER BY "No existe"')
    cf = CustomField.objects.create(name="Viejo", kind="number")
    set_cf(i, {str(cf.id): 5})
    cf.soft_delete()
    # values stay on the issues, so a saved filter that sorts by it keeps working
    assert ordered(admin, f"key = {i.key} ORDER BY cf[{cf.id}] DESC") == [i.key]


def test_fields_endpoint_says_what_sorts(api, member, project):
    cf = CustomField.objects.create(name="Entorno", kind="select", options=OPTIONS)
    api.login(member)
    fields = {f["name"]: f for f in api.get("/search/fields").json()["fields"]}
    for name in ("sprint", "parent", "labels", "key", "created", '"story points"', "team",
                 "rank", f"cf[{cf.id}]", "component", "fixVersion", "affectedVersion",
                 "resolution", "originalEstimate", "remainingEstimate", "timeSpent",
                 "workRatio", "flagged", "votes", "watcher", "lastViewed"):
        assert fields[name]["sortable"], name
    for name in ("text", "comment", "description"):
        assert not fields[name]["sortable"], name
    assert not fields["rank"]["searchable"] and fields["labels"]["searchable"]


def test_sort_query_count_does_not_grow_with_rows(admin, people, project, make_issue):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.projects.models import Component, Version

    comp = Component.objects.create(project=project, name="Web")
    version = Version.objects.create(project=project, name="1.0")
    cfs = {k: CustomField.objects.create(name=f"C {k}", kind=k, options=OPTIONS)
           for k in CustomField.Kind.values}
    cases = kind_cases(people)
    sort = ", ".join(["sprint", "parent DESC", "labels", "component", "fixVersion",
                      "affectedVersion DESC", "resolution", "originalEstimate",
                      "remainingEstimate", "timeSpent", "workRatio", "flagged", "votes",
                      "watchers", "lastViewed"] + [f"cf[{c.id}]" for c in cfs.values()])

    def run():
        with CaptureQueriesContext(connection) as ctx:
            keys = ordered(admin, f"project = GES ORDER BY {sort}")
        return len(ctx), keys

    def add(n):
        for _ in range(n):
            i = make_issue("Fila", labels=["x"], component_ids=[comp.id],
                           fix_version_ids=[version.id], affects_version_ids=[version.id],
                           original_estimate=3600)
            set_cf(i, {str(cf.id): cases[k][0][0] for k, cf in cfs.items()})
            i.voters.add(admin)

    add(2)
    small, keys = run()
    add(10)
    big, keys = run()
    assert len(keys) == 12
    assert big == small and small <= 3, (small, big)  # visible projects + issues


# --------------------------------------------------------------------------- Jira's other keys

def test_component_orders_by_first_name_case_insensitive(admin, project, make_issue):
    from apps.projects.models import Component

    beta, alfa, gamma = (Component.objects.create(project=project, name=n)
                         for n in ("beta", "Alfa", "Gamma"))
    two = make_issue("Dos", component_ids=[gamma.id, beta.id])  # first by name: beta
    one = make_issue("Uno", component_ids=[alfa.id])
    three = make_issue("Tres", component_ids=[gamma.id])
    none = make_issue("Ninguno")
    for alias in ("component", "componente", "components"):
        check(admin, [two, one, three, none], alias, [one, two, three], empties=[none])


def test_versions_order_by_project_sequence_not_name(admin, project, make_issue):
    from apps.projects.models import Version
    from apps.projects.services import create_project

    # names disagree with the sequence; positions 2 < 10 must not compare as text
    v_first = Version.objects.create(project=project, name="Zeta", position=2)
    v_second = Version.objects.create(project=project, name="Alfa", position=10)
    v_third = Version.objects.create(project=project, name="Beta", position=11)
    other = create_project(admin, name="Otro", key="ABC", template="kanban")
    v_other = Version.objects.create(project=other, name="Zzz", position=99)

    def issue(name, versions, **kw):
        ids = [v.id for v in versions]
        return make_issue(name, fix_version_ids=ids, affects_version_ids=ids, **kw)

    third = issue("En la tercera", [v_third])
    first = issue("En la primera y la tercera", [v_third, v_first])  # the lowest counts
    second = issue("En la segunda", [v_second])
    abc = issue("Otro proyecto", [v_other], project=other)  # project key ABC < GES
    none = issue("Sin versión", [])
    for alias in ("fixVersion", '"versión de corrección"', "affectedVersion",
                  '"versión afectada"'):
        check(admin, [third, first, second, abc, none], alias, [abc, first, second, third],
              empties=[none])


def test_resolution_orders_by_catalogue_position(admin, make_issue):
    from apps.issues.models import Resolution

    later = Resolution.objects.create(name="Alfa (segunda)", position=901)
    sooner = Resolution.objects.create(name="Zeta (primera)", position=900)
    a = make_issue("A")
    b = make_issue("B")
    unresolved = make_issue("Sin resolver")
    Issue.objects.filter(pk=a.pk).update(resolution=later)
    Issue.objects.filter(pk=b.pk).update(resolution=sooner)
    for alias in ("resolution", "resolución"):
        check(admin, [a, b, unresolved], alias, [b, a], empties=[unresolved])


def test_time_tracking_sorts_and_filters(admin, make_issue):
    h = 3600
    small = make_issue("Pequeña")
    big = make_issue("Grande")
    over = make_issue("Pasada")
    none = make_issue("Sin estimar")
    for i, oe, rem, spent in ((small, h, h, 0), (big, 10 * h, 4 * h, 6 * h),
                              (over, 2 * h, 0, 4 * h), (none, None, None, 30 * 60)):
        Issue.objects.filter(pk=i.pk).update(original_estimate=oe, remaining_estimate=rem,
                                             time_spent=spent)
    issues = [small, big, over, none]
    check(admin, issues, "originalEstimate", [small, over, big], empties=[none])
    check(admin, issues, '"estimación original"', [small, over, big], empties=[none])
    check(admin, issues, "remainingEstimate", [over, small, big], empties=[none])
    # no work logged (0) is EMPTY, like Jira
    check(admin, issues, "timeSpent", [none, over, big], empties=[small])
    # workRatio = spent / original × 100: small 0, big 60, over 200; no estimate → EMPTY
    check(admin, issues, "workRatio", [small, big, over], empties=[none])

    def keys(jql):
        return sorted(ordered(admin, f"key in ({keyset(issues)}) AND {jql}"))

    assert keys("originalEstimate > 2h") == [big.key]
    assert keys("originalEstimate >= 2h") == sorted([big.key, over.key])
    assert keys("originalEstimate = 60") == [small.key]  # plain numbers are minutes
    assert keys('originalEstimate = "1d 2h"') == [big.key]  # 1d = 8h
    assert keys('"estimación original" is EMPTY') == [none.key]
    assert keys("timeestimate < 1h") == [over.key]
    assert keys("timeSpent is EMPTY") == [small.key]
    assert keys("timeSpent >= 30m") == sorted([big.key, over.key, none.key])
    assert keys("workRatio > 100") == [over.key]
    assert keys("workRatio = 0") == [small.key]
    assert keys("workRatio is EMPTY") == [none.key]
    for bad in ("originalEstimate > mucho", "workRatio > alto", "timeSpent ~ 2h"):
        with pytest.raises(JQLError):
            ordered(admin, bad)


def test_flagged_first_in_ascending(admin, make_issue):
    flagged = make_issue("Bloqueada")
    Issue.objects.filter(pk=flagged.pk).update(flagged=True)
    calm = make_issue("Normal")
    calm2 = make_issue("Normal 2")
    for alias in ("flagged", "marcada"):
        check(admin, [calm, flagged, calm2], alias, [flagged], empties=[calm, calm2])


def test_votes_and_watchers_order_by_count(admin, member, outsider, make_issue):
    a, b, c = make_issue("A"), make_issue("B"), make_issue("C")
    for issue, voters, watchers in ((a, [admin, member], [admin]), (b, [], [admin, member,
                                                                           outsider]),
                                    (c, [outsider], [])):
        issue.voters.set(voters)
        issue.watchers.set(watchers)
    # zero is a value (not EMPTY): every issue sorts by its count
    check(admin, [a, b, c], "votes", [b, c, a])
    check(admin, [a, b, c], "votos", [b, c, a])
    check(admin, [a, b, c], "watchers", [c, a, b])

    def keys(jql):
        return sorted(ordered(admin, f"key in ({keyset([a, b, c])}) AND {jql}"))

    assert keys("votes >= 1") == sorted([a.key, c.key])
    assert keys("votes in (0, 2)") == sorted([a.key, b.key])
    assert keys("votes != 0") == sorted([a.key, c.key])
    # the user fields keep filtering by user
    assert keys("watcher = currentUser()") == sorted([a.key, b.key])
    with pytest.raises(JQLError):
        ordered(admin, "votes > 1.5")


def test_last_viewed_is_per_user(admin, member, make_issue):
    from django.utils import timezone

    from apps.search.models import RecentItem

    old, recent, never = make_issue("Vieja"), make_issue("Reciente"), make_issue("Nunca")
    now = timezone.now()
    for issue, when in ((old, now - timedelta(days=3)), (recent, now - timedelta(hours=1))):
        item = RecentItem.objects.create(user=admin, kind="issue", object_id=issue.id)
        RecentItem.objects.filter(pk=item.pk).update(viewed_at=when)
    # somebody else's views do not count
    RecentItem.objects.create(user=member, kind="issue", object_id=never.id)
    issues = [recent, never, old]
    check(admin, issues, "lastViewed", [old, recent], empties=[never])

    def keys(jql):
        return sorted(ordered(admin, f"key in ({keyset(issues)}) AND {jql}"))

    assert keys("lastViewed >= -1d") == [recent.key]
    assert keys("lastViewed is EMPTY") == [never.key]
    assert keys("lastViewed is not EMPTY") == sorted([old.key, recent.key])
    day = timezone.localtime(now - timedelta(days=3)).date().isoformat()
    assert keys(f'lastViewed = "{day}"') == [old.key]

import pytest

from apps.search.jql import Clause, Empty, Func, JQLError, Node, parse


@pytest.mark.parametrize(
    "q",
    [
        "project = GES AND status != Done ORDER BY priority DESC, created",
        'assignee in (currentUser(), "ana@x.com") or labels is empty',
        "not (type = Error) and created >= -7d and due < startOfWeek(1w)",
        'text ~ "login fail" and "story points" > 3',
        "sprint in openSprints() order by rank",
        "status not in (Done, \"En curso\")",
        "assignee is not empty",
        "order by created desc",
        "cf[10] = foo",
        "",
    ],
)
def test_parses(q):
    parse(q)


def test_structure():
    p = parse("project = GES AND (status = Done OR assignee is empty) ORDER BY created DESC")
    assert isinstance(p.where, Node) and p.where.kind == "and"
    left, right = p.where.children
    assert left == Clause("project", "=", "GES")
    assert right.kind == "or"
    assert right.children[1] == Clause("assignee", "is", Empty())
    assert p.order == [("created", True)]


def test_keywords_are_not_prefix_matched():
    assert parse("notes = 1").where == Clause("notes", "=", "1")
    assert parse("ordered = x").where == Clause("ordered", "=", "x")
    assert parse("index = 3").where == Clause("index", "=", "3")


def test_values():
    assert parse("key = GES-12").where.value == "GES-12"
    assert parse("created > 2026-01-31").where.value == "2026-01-31"
    assert parse("created > -7d").where.value == "-7d"
    assert parse("sprint in openSprints()").where.value == Func("opensprints", [])
    assert parse("assignee = currentUser()").where.value == Func("currentuser", [])


@pytest.mark.parametrize("q", ["project = GES and", "status was Done", "= x", "a in (1,"])
def test_syntax_errors(q):
    with pytest.raises(JQLError):
        parse(q)


def test_unquoted_accented_names():
    # Spanish aliases and values parse without quotes (resolución, descripción, España…)
    p = parse("resolución = Hecha AND país = España ORDER BY resolución DESC")
    assert p.where.children[1] == Clause("país", "=", "España")
    assert p.order == [("resolución", True)]

import pytest

from apps.core.richtext import InvalidDocument, to_text, validate_doc


def p(*content):
    return {"type": "doc", "content": [{"type": "paragraph", "content": list(content)}]}


def test_unsafe_link_dropped_text_kept():
    doc = p({"type": "text", "text": "clic",
             "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}]})
    out = validate_doc(doc)
    node = out["content"][0]["content"][0]
    assert node == {"type": "text", "text": "clic"}


def test_safe_link_kept_and_extra_attrs_removed():
    doc = p({"type": "text", "text": "x", "marks": [
        {"type": "link", "attrs": {"href": "https://a.b", "onclick": "evil()"}}]})
    mark = validate_doc(doc)["content"][0]["content"][0]["marks"][0]
    assert mark == {"type": "link", "attrs": {"href": "https://a.b"}}


def test_unknown_nodes_and_marks_dropped():
    doc = {"type": "doc", "content": [
        {"type": "iframe", "attrs": {"src": "https://evil"}},
        {"type": "paragraph", "attrs": {"style": "x"},
         "content": [{"type": "text", "text": "ok", "marks": [{"type": "script"}]}]},
    ]}
    out = validate_doc(doc)
    assert out == {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "ok"}]}]}


def test_mention_requires_integer_id():
    with pytest.raises(InvalidDocument):
        validate_doc(p({"type": "mention", "attrs": {"id": "<img>", "label": "x"}}))
    out = validate_doc(p({"type": "mention", "attrs": {"id": 5, "label": "Ana"}}))
    assert out["content"][0]["content"][0]["attrs"] == {"id": "5", "label": "Ana"}
    assert to_text(out) == "@Ana"


def test_plain_text_converted():
    assert to_text(validate_doc("hola\nmundo")) == "hola\nmundo"

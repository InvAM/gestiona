"""Helpers for ProseMirror/TipTap JSON documents.

`validate_doc` rebuilds the document from an allow-list of node types, mark types and
attributes, so nothing outside the schema the editor produces is ever stored.
"""

from __future__ import annotations

from typing import Any

BLOCK_TYPES = {
    "paragraph", "heading", "blockquote", "codeBlock", "listItem", "tableCell", "tableHeader",
    "taskItem",
}
MAX_DEPTH = 64
MAX_NODES = 20000
MAX_TEXT = 200_000

SAFE_URL_SCHEMES = ("http://", "https://", "mailto:")


class InvalidDocument(ValueError):
    pass


def _safe_url(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    v = v.strip()
    if v.lower().startswith(SAFE_URL_SCHEMES) or v.startswith("/"):
        return v[:2000]
    return None


def _int_attr(lo: int, hi: int, default: int):
    def clean(v):
        try:
            v = int(v)
        except (TypeError, ValueError):
            return default
        return min(max(v, lo), hi)

    return clean


def _str_attr(max_len: int, allowed: set[str] | None = None):
    def clean(v):
        if v is None:
            return None
        v = str(v)[:max_len]
        if allowed is not None and v not in allowed:
            return None
        return v

    return clean


def _bool_attr(v):
    return bool(v)


def _mention_id(v):
    try:
        return str(int(v))
    except (TypeError, ValueError):
        raise InvalidDocument("Mención inválida") from None


# node type -> {attr: cleaner}
NODE_ATTRS: dict[str, dict] = {
    "doc": {},
    "paragraph": {"textAlign": _str_attr(10, {"left", "center", "right", "justify"})},
    "text": {},
    "heading": {"level": _int_attr(1, 6, 1)},
    "blockquote": {},
    "bulletList": {},
    "orderedList": {"start": _int_attr(1, 100000, 1)},
    "listItem": {},
    "taskList": {},
    "taskItem": {"checked": _bool_attr},
    "codeBlock": {"language": _str_attr(40)},
    "hardBreak": {},
    "horizontalRule": {},
    "mention": {"id": _mention_id, "label": _str_attr(150)},
    "issueMention": {"key": _str_attr(24), "summary": _str_attr(255)},
    "table": {},
    "tableRow": {},
    "tableCell": {"colspan": _int_attr(1, 50, 1), "rowspan": _int_attr(1, 50, 1)},
    "tableHeader": {"colspan": _int_attr(1, 50, 1), "rowspan": _int_attr(1, 50, 1)},
    "image": {"src": _safe_url, "alt": _str_attr(255), "title": _str_attr(255)},
}

MARK_ATTRS: dict[str, dict] = {
    "bold": {},
    "italic": {},
    "strike": {},
    "underline": {},
    "code": {},
    "subscript": {},
    "superscript": {},
    "link": {"href": _safe_url},
    "textStyle": {"color": _str_attr(20)},
    "highlight": {"color": _str_attr(20)},
}


def _clean_attrs(spec: dict, attrs: Any) -> dict | None:
    if not spec or not isinstance(attrs, dict):
        return None
    out = {}
    for name, cleaner in spec.items():
        if name in attrs:
            v = cleaner(attrs[name])
            if v is not None:
                out[name] = v
    return out or None


def validate_doc(doc: Any) -> dict | None:
    """Return a sanitized copy of `doc` or raise InvalidDocument."""
    if doc is None:
        return None
    if isinstance(doc, str):
        return text_to_doc(doc)
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise InvalidDocument("Documento inválido")
    count = 0
    text_len = 0

    def walk(node: Any, depth: int) -> dict | None:
        nonlocal count, text_len
        count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            raise InvalidDocument("Documento demasiado grande")
        if not isinstance(node, dict):
            raise InvalidDocument("Nodo inválido")
        ntype = node.get("type")
        if ntype not in NODE_ATTRS:
            return None  # drop unknown nodes silently
        out: dict[str, Any] = {"type": ntype}
        attrs = _clean_attrs(NODE_ATTRS[ntype], node.get("attrs"))
        if ntype == "mention" and not (attrs and "id" in attrs):
            raise InvalidDocument("Mención inválida")
        if ntype == "image" and not (attrs and attrs.get("src")):
            return None
        if attrs:
            out["attrs"] = attrs
        if ntype == "text":
            text = node.get("text")
            if not isinstance(text, str) or not text:
                return None
            text_len += len(text)
            if text_len > MAX_TEXT:
                raise InvalidDocument("Texto demasiado largo")
            out["text"] = text
            marks = []
            for m in node.get("marks") or []:
                if not isinstance(m, dict) or m.get("type") not in MARK_ATTRS:
                    continue
                mo: dict[str, Any] = {"type": m["type"]}
                mattrs = _clean_attrs(MARK_ATTRS[m["type"]], m.get("attrs"))
                if m["type"] == "link" and not (mattrs and mattrs.get("href")):
                    continue  # unsafe link → keep text, drop link
                if mattrs:
                    mo["attrs"] = mattrs
                marks.append(mo)
            if marks:
                out["marks"] = marks
            return out
        content = node.get("content")
        if content is not None:
            if not isinstance(content, list):
                raise InvalidDocument("Contenido inválido")
            children = [c for c in (walk(ch, depth + 1) for ch in content) if c is not None]
            if children:
                out["content"] = children
        return out

    clean = walk(doc, 0)
    return clean


def text_to_doc(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]} if p
            else {"type": "paragraph"}
            for p in text.split("\n")
        ],
    }


def to_text(doc: dict | None) -> str:
    if not doc:
        return ""
    out: list[str] = []

    def walk(node):
        t = node.get("type")
        if t == "text":
            out.append(node.get("text", ""))
        elif t == "mention":
            out.append("@" + str((node.get("attrs") or {}).get("label", "")))
        elif t == "hardBreak":
            out.append("\n")
        for child in node.get("content", []) or []:
            walk(child)
        if t in BLOCK_TYPES:
            out.append("\n")

    walk(doc)
    return "".join(out).strip()


def mentions(doc: dict | None) -> set[int]:
    ids: set[int] = set()
    if not doc:
        return ids

    def walk(node):
        if node.get("type") == "mention":
            try:
                ids.add(int((node.get("attrs") or {}).get("id")))
            except (TypeError, ValueError):
                pass
        for child in node.get("content", []) or []:
            walk(child)

    walk(doc)
    return ids

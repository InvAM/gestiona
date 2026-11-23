"""Atlassian Document Format (Jira Cloud) → ProseMirror/TipTap JSON used by Gestiona.

ADF is itself ProseMirror-based, so most nodes map 1:1. Nodes without an equivalent are
degraded to readable text (cards → links, media → "📎 nombre", panels → citas). The output is
passed through `validate_doc`, so anything unexpected is dropped by the allow-list.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from apps.core.richtext import text_to_doc, validate_doc

# accountId, display text → (gestiona user id, label) | None
MentionResolver = Callable[[str, str], tuple[int, str] | None]

MARKS = {
    "strong": "bold", "em": "italic", "strike": "strike", "underline": "underline",
    "code": "code",
}
INLINE_TYPES = {
    "text", "hardBreak", "mention", "emoji", "inlineCard", "date", "status", "mediaInline",
    "placeholder", "inlineExtension",
}


def _text(text: str, marks: list | None = None) -> dict:
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = marks
    return node


def _marks(adf_marks: list | None) -> list:
    out = []
    for m in adf_marks or []:
        t = m.get("type")
        attrs = m.get("attrs") or {}
        if t in MARKS:
            out.append({"type": MARKS[t]})
        elif t == "link" and attrs.get("href"):
            out.append({"type": "link", "attrs": {"href": attrs["href"]}})
        elif t == "subsup":
            out.append({"type": "subscript" if attrs.get("type") == "sub" else "superscript"})
        elif t == "textColor" and attrs.get("color"):
            out.append({"type": "textStyle", "attrs": {"color": attrs["color"]}})
        elif t == "backgroundColor" and attrs.get("color"):
            out.append({"type": "highlight", "attrs": {"color": attrs["color"]}})
    return out


class AdfConverter:
    def __init__(self, resolve_mention: MentionResolver | None = None):
        self.resolve_mention = resolve_mention

    # ------------------------------------------------------------------ public
    def convert(self, value: Any) -> dict | None:
        """Accepts an ADF document, a plain string (Jira Server/DC) or None."""
        if value in (None, "", {}):
            return None
        if isinstance(value, str):
            return validate_doc(text_to_doc(value.replace("\r\n", "\n")))
        if not isinstance(value, dict):
            return None
        content = self._blocks(value.get("content") or [])
        if not content:
            return None
        return validate_doc({"type": "doc", "content": content})

    # ------------------------------------------------------------------ blocks
    def _blocks(self, nodes: list) -> list:
        out: list = []
        inline_run: list = []

        def flush():
            if inline_run:
                out.append({"type": "paragraph", "content": list(inline_run)})
                inline_run.clear()

        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("type") in INLINE_TYPES:
                inline_run.extend(self._inline(node))
                continue
            flush()
            out.extend(self._block(node))
        flush()
        return out

    def _wrap(self, ntype: str, children: list, attrs: dict | None = None) -> list:
        node: dict[str, Any] = {"type": ntype}
        if attrs:
            node["attrs"] = attrs
        if children:
            node["content"] = children
        return [node]

    def _block(self, node: dict) -> list:
        t = node.get("type")
        attrs = node.get("attrs") or {}
        content = node.get("content") or []
        if t == "paragraph":
            return self._wrap("paragraph", self._inlines(content))
        if t == "heading":
            return self._wrap("heading", self._inlines(content), {"level": attrs.get("level", 1)})
        if t == "bulletList":
            return self._wrap("bulletList", self._list_items(content))
        if t == "orderedList":
            start = attrs.get("order") or 1
            return self._wrap("orderedList", self._list_items(content), {"start": start})
        if t in ("listItem",):
            return self._wrap("listItem", self._blocks(content) or [{"type": "paragraph"}])
        if t == "taskList":
            items = []
            for item in content:
                if item.get("type") == "taskItem":
                    items.extend(self._task_item(item))
                elif item.get("type") == "taskList":  # nested lists come as siblings in ADF
                    if items:
                        items[-1].setdefault("content", []).extend(self._block(item))
            return self._wrap("taskList", items)
        if t == "decisionList":
            items = []
            for item in content:
                para = self._wrap("paragraph", self._inlines(item.get("content") or []))
                items.append({"type": "listItem", "content": para})
            return self._wrap("bulletList", items)
        if t == "codeBlock":
            text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
            lang = attrs.get("language")
            return self._wrap("codeBlock", [_text(text)] if text else [],
                              {"language": lang} if lang else None)
        if t == "blockquote":
            return self._wrap("blockquote", self._blocks(content))
        if t == "panel":
            return self._wrap("blockquote", self._blocks(content))
        if t in ("expand", "nestedExpand"):
            title = attrs.get("title")
            head = [{"type": "paragraph", "content": [_text(title, [{"type": "bold"}])]}] \
                if title else []
            return head + self._blocks(content)
        if t == "rule":
            return [{"type": "horizontalRule"}]
        if t == "table":
            rows = [r for r in (self._row(r) for r in content) if r]
            return self._wrap("table", rows) if rows else []
        if t in ("mediaSingle", "mediaGroup"):
            names = [self._media_label(m) for m in content if m.get("type") == "media"]
            return [{"type": "paragraph", "content": [_text(n)]} for n in names if n]
        if t == "media":
            label = self._media_label(node)
            return [{"type": "paragraph", "content": [_text(label)]}] if label else []
        if t == "blockCard" or t == "embedCard":
            url = attrs.get("url")
            if url:
                return [{"type": "paragraph",
                         "content": [_text(url, [{"type": "link", "attrs": {"href": url}}])]}]
            return []
        if t in ("bodiedExtension", "layoutSection", "layoutColumn", "multiBodiedExtension",
                 "extensionFrame"):
            return self._blocks(content)
        # unknown block: keep any text it carries
        return self._blocks(content) if content else []

    def _list_items(self, content: list) -> list:
        items: list = []
        for item in content:
            if item.get("type") == "listItem":
                items.extend(self._block(item))
        return items

    def _task_item(self, item: dict) -> list:
        checked = (item.get("attrs") or {}).get("state") == "DONE"
        inl = self._inlines(item.get("content") or [])
        para = {"type": "paragraph", "content": inl} if inl else {"type": "paragraph"}
        return [{"type": "taskItem", "attrs": {"checked": checked}, "content": [para]}]

    def _row(self, row: dict) -> dict | None:
        cells = []
        for cell in row.get("content") or []:
            ct = cell.get("type")
            if ct not in ("tableCell", "tableHeader"):
                continue
            a = cell.get("attrs") or {}
            attrs = {k: a[k] for k in ("colspan", "rowspan") if a.get(k)}
            body = self._blocks(cell.get("content") or []) or [{"type": "paragraph"}]
            node: dict[str, Any] = {"type": ct, "content": body}
            if attrs:
                node["attrs"] = attrs
            cells.append(node)
        return {"type": "tableRow", "content": cells} if cells else None

    @staticmethod
    def _media_label(media: dict) -> str | None:
        attrs = media.get("attrs") or {}
        name = attrs.get("alt") or attrs.get("__fileName")
        return f"📎 {name}" if name else "📎 adjunto"

    # ------------------------------------------------------------------ inline
    def _inlines(self, nodes: list) -> list:
        out: list = []
        for n in nodes:
            if isinstance(n, dict):
                out.extend(self._inline(n))
        return out

    def _inline(self, node: dict) -> list:
        t = node.get("type")
        attrs = node.get("attrs") or {}
        if t == "text":
            text = node.get("text") or ""
            return [_text(text, _marks(node.get("marks")))] if text else []
        if t == "hardBreak":
            return [{"type": "hardBreak"}]
        if t == "mention":
            label = (attrs.get("text") or "").lstrip("@") or "usuario"
            resolved = self.resolve_mention(str(attrs.get("id") or ""), label) \
                if self.resolve_mention else None
            if resolved:
                uid, name = resolved
                return [{"type": "mention", "attrs": {"id": uid, "label": name}}]
            return [_text(f"@{label}")]
        if t == "emoji":
            text = attrs.get("text") or attrs.get("shortName") or ""
            return [_text(text)] if text else []
        if t == "inlineCard":
            url = attrs.get("url")
            return [_text(url, [{"type": "link", "attrs": {"href": url}}])] if url else []
        if t == "date":
            try:
                ts = int(attrs.get("timestamp")) / 1000
                return [_text(datetime.fromtimestamp(ts, UTC).date().isoformat())]
            except (TypeError, ValueError):
                return []
        if t == "status":
            text = attrs.get("text")
            return [_text(f"[{text}]", [{"type": "bold"}])] if text else []
        if t == "mediaInline":
            label = self._media_label(node)
            return [_text(label)] if label else []
        return []


def adf_to_text(value: Any) -> str:
    """Plain text of an ADF/string value (used for worklog comments)."""
    from apps.core.richtext import to_text

    if isinstance(value, str):
        return value
    return to_text(AdfConverter().convert(value))

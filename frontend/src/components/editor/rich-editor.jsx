"use client";

import Mention from "@tiptap/extension-mention";
import { TaskItem, TaskList } from "@tiptap/extension-list";
import { Placeholder } from "@tiptap/extensions";
import { EditorContent, ReactRenderer, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  Bold, Code, Heading2, Italic, Link2, List, ListChecks, ListOrdered, Quote, Strikethrough,
} from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import { Avatar } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { api, unwrap } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ mention list */

const MentionList = forwardRef(function MentionList(props, ref) {
  const [index, setIndex] = useState(0);
  const items = props.items;
  const pick = (i) => {
    const u = items[i];
    if (u) props.command({ id: String(u.id), label: u.name });
  };
  useImperativeHandle(ref, () => ({
    onKeyDown: ({ event }) => {
      if (event.key === "ArrowDown") { setIndex((i) => (i + 1) % Math.max(items.length, 1)); return true; }
      if (event.key === "ArrowUp") { setIndex((i) => (i - 1 + items.length) % Math.max(items.length, 1)); return true; }
      if (event.key === "Enter" || event.key === "Tab") { pick(index); return true; }
      return false;
    },
  }));
  const rect = props.clientRect?.();
  if (!rect) return null;
  return (
    <div style={{ position: "fixed", left: rect.left, top: rect.bottom + 4 }}
         className="z-[200] w-64 rounded-[3px] border border-line bg-bg-overlay py-1 shadow-overlay">
      {items.length ? items.map((u, i) => (
        <button key={u.id} type="button" onMouseDown={(e) => { e.preventDefault(); pick(i); }}
                className={cn("flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm", i === index && "bg-bg-hover")}>
          <Avatar user={u} size="sm" />
          <span className="min-w-0"><span className="block truncate">{u.name}</span>
            <span className="block truncate text-xs text-fg-subtlest">{u.email}</span></span>
        </button>
      )) : <div className="px-3 py-1.5 text-sm text-fg-subtlest">Sin coincidencias</div>}
    </div>
  );
});

function mentionExtension(projectKey) {
  return Mention.configure({
    HTMLAttributes: { class: "mention" },
    renderText: ({ node }) => `@${node.attrs.label}`,
    renderHTML: ({ node, options }) => ["span", { ...options.HTMLAttributes, "data-id": node.attrs.id }, `@${node.attrs.label}`],
    suggestion: {
      items: async ({ query }) => {
        try {
          return await unwrap(api.GET("/api/v1/users", { params: { query: { q: query, project: projectKey, limit: 8 } } }));
        } catch {
          return [];
        }
      },
      render: () => {
        let r = null;
        return {
          onStart: (props) => {
            r = new ReactRenderer(MentionList, { props, editor: props.editor });
            document.body.appendChild(r.element);
          },
          onUpdate: (props) => r?.updateProps(props),
          onKeyDown: (props) => {
            if (props.event.key === "Escape") { r?.destroy(); r?.element.remove(); r = null; return true; }
            return r?.ref?.onKeyDown(props) ?? false;
          },
          onExit: () => { r?.destroy(); r?.element.remove(); r = null; },
        };
      },
    },
  });
}

function extensions(placeholder, projectKey) {
  return [
    StarterKit.configure({
      heading: { levels: [1, 2, 3] },
      link: { openOnClick: false, autolink: true, protocols: ["http", "https", "mailto"],
              HTMLAttributes: { rel: "noopener noreferrer nofollow", target: "_blank" } },
    }),
    TaskList,
    TaskItem.configure({ nested: true }),
    Placeholder.configure({ placeholder }),
    mentionExtension(projectKey),
  ];
}

/* ------------------------------------------------------------------ toolbar */

function Toolbar({ editor }) {
  const btn = (active, onClick, icon, label) => (
    <button type="button" title={label} aria-label={label} onMouseDown={(e) => { e.preventDefault(); onClick(); }}
            className={cn("rounded-[3px] p-1.5 text-fg-subtle hover:bg-bg-hover", active && "bg-bg-selected text-brand")}>
      {icon}
    </button>
  );
  const c = () => editor.chain().focus();
  return (
    <div className="flex flex-wrap items-center gap-0.5 border-b border-line px-1 py-1">
      {btn(editor.isActive("heading", { level: 2 }), () => c().toggleHeading({ level: 2 }).run(), <Heading2 size={16} />, "Título")}
      {btn(editor.isActive("bold"), () => c().toggleBold().run(), <Bold size={16} />, "Negrita")}
      {btn(editor.isActive("italic"), () => c().toggleItalic().run(), <Italic size={16} />, "Cursiva")}
      {btn(editor.isActive("strike"), () => c().toggleStrike().run(), <Strikethrough size={16} />, "Tachado")}
      {btn(editor.isActive("code"), () => c().toggleCode().run(), <Code size={16} />, "Código")}
      <span className="mx-1 h-5 w-px bg-line" />
      {btn(editor.isActive("bulletList"), () => c().toggleBulletList().run(), <List size={16} />, "Lista")}
      {btn(editor.isActive("orderedList"), () => c().toggleOrderedList().run(), <ListOrdered size={16} />, "Lista numerada")}
      {btn(editor.isActive("taskList"), () => c().toggleTaskList().run(), <ListChecks size={16} />, "Lista de tareas")}
      {btn(editor.isActive("blockquote"), () => c().toggleBlockquote().run(), <Quote size={16} />, "Cita")}
      {btn(editor.isActive("codeBlock"), () => c().toggleCodeBlock().run(), <span className="font-mono text-xs">{"{}"}</span>, "Bloque de código")}
      {btn(editor.isActive("link"), () => {
        const prev = editor.getAttributes("link").href;
        const url = window.prompt("URL del enlace", prev ?? "https://");
        if (url === null) return;
        if (!url) c().unsetLink().run();
        else if (/^(https?:\/\/|mailto:)/i.test(url)) c().extendMarkRange("link").setLink({ href: url }).run();
      }, <Link2 size={16} />, "Enlace")}
    </div>
  );
}

/* ------------------------------------------------------------------ public components */

export function isEmptyDoc(doc) {
  if (!doc?.content?.length) return true;
  return doc.content.every((n) => n.type === "paragraph" && !n.content?.length);
}

export function RichEditor({ value, onSave, onCancel, placeholder = "Escribe algo…", projectKey,
                             saveLabel = "Guardar", autoFocus = true, minHeight = 120, saving,
                             hideActions }) {
  const editor = useEditor({
    extensions: extensions(placeholder, projectKey),
    content: value ?? "",
    immediatelyRender: false,
    autofocus: autoFocus ? "end" : false,
    editorProps: {
      attributes: { class: "rt px-3 py-2 text-sm" },
      handleKeyDown: (_v, e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { submit(); return true; }
        if (e.key === "Escape" && onCancel) { onCancel(); return true; }
        return false;
      },
    },
  });
  const submit = () => {
    if (!editor) return;
    const json = editor.getJSON();
    onSave?.(isEmptyDoc(json) ? null : json);
  };
  if (!editor) return <div style={{ minHeight }} className="rounded-[3px] border-2 border-line" />;
  return (
    <div>
      <div className="rounded-[3px] border-2 border-line bg-bg focus-within:border-focus">
        <Toolbar editor={editor} />
        <div style={{ minHeight }} className="cursor-text" onClick={() => editor.commands.focus()}>
          <EditorContent editor={editor} />
        </div>
      </div>
      {!hideActions && (
        <div className="mt-2 flex items-center gap-2">
          <Button variant="primary" loading={saving} onClick={submit}>{saveLabel}</Button>
          {onCancel && <Button variant="subtle" onClick={onCancel}>Cancelar</Button>}
          <span className="ml-auto text-xs text-fg-subtlest">Ctrl+Enter para guardar · @ para mencionar</span>
        </div>
      )}
    </div>
  );
}

/** Controlled editor for forms (create issue). */
export function RichField({ value, onChange, placeholder, projectKey, minHeight = 120 }) {
  const editor = useEditor({
    extensions: extensions(placeholder ?? "", projectKey),
    content: value ?? "",
    immediatelyRender: false,
    editorProps: { attributes: { class: "rt px-3 py-2 text-sm" } },
    onUpdate: ({ editor: e }) => { const j = e.getJSON(); onChange(isEmptyDoc(j) ? null : j); },
  });
  if (!editor) return <div style={{ minHeight }} className="rounded-[3px] border-2 border-line" />;
  return (
    <div className="rounded-[3px] border-2 border-line bg-bg focus-within:border-focus">
      <Toolbar editor={editor} />
      <div style={{ minHeight }} className="cursor-text" onClick={() => editor.commands.focus()}><EditorContent editor={editor} /></div>
    </div>
  );
}

/** Read-only renderer (uses the same schema → unknown/unsafe content never renders). */
export function RichView({ doc, className, meId }) {
  const editor = useEditor({
    extensions: extensions(""),
    content: doc ?? "",
    editable: false,
    immediatelyRender: false,
    editorProps: { attributes: { class: cn("rt text-sm", className) } },
  });
  useEffect(() => {
    if (editor && doc !== undefined) editor.commands.setContent(doc ?? "", { emitUpdate: false });
  }, [editor, doc]);
  useEffect(() => {
    if (!editor || !meId) return;
    editor.view.dom.querySelectorAll(".mention").forEach((el) => {
      el.classList.toggle("me", el.getAttribute("data-id") === String(meId));
    });
  }, [editor, doc, meId]);
  if (!editor) return null;
  return <EditorContent editor={editor} />;
}

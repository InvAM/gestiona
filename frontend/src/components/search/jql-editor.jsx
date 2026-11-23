"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Search, XCircle } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, unwrap } from "@/lib/api/client";
import { cn } from "@/lib/utils";

const KEYWORDS = ["AND", "OR", "NOT", "ORDER BY", "ASC", "DESC", "IN", "NOT IN", "IS", "IS NOT", "EMPTY"];
const OPS = ["=", "!=", "~", "!~", ">", ">=", "<", "<=", "in", "not in", "is", "is not"];
const DIRECTIONS = ["ASC", "DESC"];

/** Index of the "by" of the last top-level ORDER BY among `words`, or -1. */
function orderByAt(words) {
  for (let i = words.length - 1; i > 0; i--) {
    if (words[i].toLowerCase() === "by" && words[i - 1].toLowerCase() === "order") return i;
  }
  return -1;
}

/** Position of the quote that is still open at the end of `text`, or null. */
function openQuote(text) {
  let open = null;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (open) {
      if (c === "\\") i++;
      else if (c === open.char) open = null;
    } else if (c === '"' || c === "'") {
      open = { char: c, index: i };
    }
  }
  return open;
}

/** Very small tokenizer to figure out what the cursor is editing. */
function context(text, pos) {
  const before = text.slice(0, pos);
  // A quote only opens the current token when the quotes before it are unbalanced; otherwise
  // the closing quote of a finished value (`summary ~ "x" `) would be read as a new open string.
  const open = openQuote(before);
  const m = open ? before.slice(open.index).match(/^(.*)$/s) : before.match(/([^\s(),"']*)$/);
  const token = m ? m[1] : "";
  const start = pos - token.length;
  const prev = before.slice(0, start).trim();
  const words = prev.match(/("[^"]*"|'[^']*'|[^\s(),]+|[(),])/g) ?? [];
  const last = (words[words.length - 1] ?? "").toLowerCase();
  const last2 = words.slice(-2).join(" ").toLowerCase();
  // After ORDER BY: a sortable field, then ASC/DESC, then "," and another field.
  const by = orderByAt(words);
  if (by >= 0) {
    if (by === words.length - 1 || last === ",") return { kind: "field", order: true, token, start };
    if (DIRECTIONS.includes(last.toUpperCase())) return { kind: "none", token, start };
    return { kind: "direction", token, start };
  }
  if (!words.length || ["and", "or", "not", "("].includes(last) || last === ",") {
    if (last === ",") {
      const field = findField(words);
      return { kind: "value", field, token, start };
    }
    return { kind: "field", token, start };
  }
  if (OPS.includes(last) || ["not in", "is not"].includes(last2)) {
    const field = findField(words);
    if (last === "is" || last2 === "is not") return { kind: "keyword", token, start };
    return { kind: "value", field, token, start };
  }
  // previous word is a field name → operator expected
  const isValueEnd = words.length >= 3 && OPS.includes((words[words.length - 2] ?? "").toLowerCase());
  if (!isValueEnd && words.length && !KEYWORDS.includes(words[words.length - 1].toUpperCase()) && last !== ")") {
    return { kind: "op", token, start };
  }
  return { kind: "keyword", token, start };
}

function findField(words) {
  for (let i = words.length - 1; i >= 0; i--) {
    const w = words[i].toLowerCase();
    if (OPS.includes(w) || w === "(" || w === ",") continue;
    if (["not", "in", "is"].includes(w)) continue;
    // value tokens before op? find token right before first op
    const next = (words[i + 1] ?? "").toLowerCase();
    if (OPS.includes(next) || next === "not" || next === "in" || next === "is") return words[i].replace(/^["']|["']$/g, "");
  }
  return undefined;
}

export function JqlEditor({ value, onChange, onSubmit, error }) {
  const ref = useRef(null);
  const [cursor, setCursor] = useState(0);
  const [focused, setFocused] = useState(false);
  const [sel, setSel] = useState({ k: "", i: 0 });
  const fields = useQuery({ queryKey: ["jql-fields"], queryFn: () => unwrap(api.GET("/api/v1/search/fields")), staleTime: Infinity });
  const ctx = useMemo(() => context(value, cursor), [value, cursor]);
  const values = useQuery({
    queryKey: ["jql-suggest", ctx.field, ctx.token],
    queryFn: () => unwrap(api.GET("/api/v1/search/suggest", { params: { query: { field: ctx.field, value: ctx.token } } })),
    enabled: focused && ctx.kind === "value" && !!ctx.field,
    staleTime: 10_000,
  });

  const suggestions = useMemo(() => {
    const t = ctx.token.toLowerCase().replace(/^["']/, "");
    if (ctx.kind === "field") {
      // ORDER BY only offers what the backend can sort by; clauses skip sort-only fields (rank)
      const usable = (fields.data?.fields ?? []).filter((f) => (ctx.order ? f.sortable : f.searchable !== false));
      return usable.filter((f) => f.name.toLowerCase().replace(/"/g, "").startsWith(t) || f.label.toLowerCase().includes(t))
        .slice(0, 12).map((f) => ({ value: f.name, label: f.label }));
    }
    if (ctx.kind === "direction") {
      return DIRECTIONS.filter((d) => d.toLowerCase().startsWith(t))
        .map((d) => ({ value: d, label: d === "ASC" ? "Ascendente (vacíos al final)" : "Descendente (vacíos al principio)" }));
    }
    if (ctx.kind === "none") return [];
    if (ctx.kind === "op") return OPS.filter((o) => o.startsWith(t)).map((o) => ({ value: o, label: o }));
    if (ctx.kind === "keyword") return KEYWORDS.filter((k) => k.toLowerCase().startsWith(t)).map((k) => ({ value: k, label: k }));
    return (values.data ?? []).map((v) => ({ value: v.value, label: v.label }));
  }, [ctx, fields.data, values.data]);

  const ctxKey = `${ctx.kind}:${ctx.token}`;
  const index = sel.k === ctxKey ? sel.i : 0;
  const setIndex = (f) => setSel({ k: ctxKey, i: f(index) });

  const apply = (s) => {
    const next = value.slice(0, ctx.start) + s + " " + value.slice(cursor).replace(/^\S*/, "");
    onChange(next);
    const pos = ctx.start + s.length + 1;
    requestAnimationFrame(() => { ref.current?.setSelectionRange(pos, pos); setCursor(pos); ref.current?.focus(); });
  };

  const show = focused && suggestions.length > 0 && (ctx.token.length > 0 || ctx.kind !== "keyword");

  return (
    <div className="relative">
      <div className={cn("flex items-start gap-2 rounded-[3px] border-2 bg-bg px-2 py-1", error ? "border-danger" : "border-line focus-within:border-focus")}>
        <textarea ref={ref} value={value} rows={Math.min(4, Math.max(1, value.split("\n").length))} spellCheck={false}
                  placeholder='project = DEMO AND status = "En curso" ORDER BY created DESC'
                  onChange={(e) => { onChange(e.target.value); setCursor(e.target.selectionStart); }}
                  onSelect={(e) => setCursor(e.target.selectionStart)}
                  onFocus={() => setFocused(true)} onBlur={() => setTimeout(() => setFocused(false), 150)}
                  onKeyDown={(e) => {
                    if (show && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
                      e.preventDefault();
                      setIndex((i) => (i + (e.key === "ArrowDown" ? 1 : -1) + suggestions.length) % suggestions.length);
                    } else if (show && e.key === "Tab") {
                      e.preventDefault(); apply(suggestions[index].value);
                    } else if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      if (show && ctx.token) apply(suggestions[index].value);
                      else { setFocused(false); onSubmit(); }
                    } else if (e.key === "Escape") setFocused(false);
                  }}
                  className="min-h-7 flex-1 resize-none bg-transparent py-0.5 font-mono text-[13px] outline-none" />
        <span className="pt-1">{error ? <XCircle size={16} className="text-danger" /> : value ? <CheckCircle2 size={16} className="text-success" /> : null}</span>
        <Button variant="primary" size="sm" className="mt-0.5" onClick={onSubmit} aria-label="Buscar"><Search size={14} /></Button>
      </div>
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
      {show && (
        <ul className="absolute left-0 top-full z-50 mt-1 max-h-72 w-96 overflow-y-auto rounded-[3px] border border-line bg-bg-overlay py-1 shadow-overlay">
          {suggestions.map((s, i) => (
            <li key={s.value + i}>
              <button type="button" onMouseDown={(e) => { e.preventDefault(); apply(s.value); }}
                      className={cn("flex w-full items-center justify-between gap-3 px-3 py-1 text-left text-sm", i === index && "bg-bg-hover")}>
                <span className="font-mono text-[13px]">{s.value}</span>
                {s.label !== s.value && <span className="truncate text-xs text-fg-subtlest">{s.label}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

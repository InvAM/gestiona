"use client";

// Shared chart primitives (analytics page, project reports and dashboard gadgets).
// Colours: the validated categorical tokens --series-1..8 / --series-other from globals.css
// (light and dark steps). Text always wears text tokens, never the series colour.

import { BarChart3, Download, Table2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn, fmtDate } from "@/lib/utils";

export const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);
export const OTHER = "var(--series-other)";
export const OTHER_KEY = "__other__";
export const MAX_SERIES = 7; // 8th slot is "Otros"

const nf = (digits) => new Intl.NumberFormat("es", { maximumFractionDigits: digits });
const NF0 = nf(0);
const NF1 = nf(1);

export function fmtNum(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return "–";
  return digits === 0 ? NF0.format(n) : digits === 1 ? NF1.format(n) : nf(digits).format(n);
}

/** 0.5 → "30 min", 5 → "5 h", 60 → "2,5 d". */
export function fmtHours(h) {
  if (h === null || h === undefined) return "–";
  if (h < 1) return `${NF0.format(h * 60)} min`;
  if (h < 48) return `${NF1.format(h)} h`;
  return `${NF1.format(h / 24)} d`;
}

/** One unit for a whole axis, so ticks stay comparable. */
export function durationUnit(maxHours) {
  return (maxHours ?? 0) >= 48 ? { div: 24, suffix: "d", label: "días" } : { div: 1, suffix: "h", label: "horas" };
}

export function fmtPeriod(period, interval, short = false) {
  if (!period) return "";
  if (interval === "month") return fmtDate(period, short ? "MMM yy" : "MMMM yyyy");
  if (interval === "week") return short ? fmtDate(period, "d MMM") : `Semana del ${fmtDate(period, "d MMM yyyy")}`;
  return fmtDate(period, short ? "d/M" : "d MMM yyyy");
}

/**
 * Stable colours for groups: the 7 largest (by `weight`) get a series slot, assigned by key
 * order so a colour follows its entity; the rest fold into "Otros".
 */
export function groupPalette(groups, weight) {
  const w = (k) => weight?.get(k) ?? 0;
  const ranked = [...groups].sort((a, b) => w(b.key) - w(a.key) || String(a.label).localeCompare(String(b.label)));
  const shown = ranked.slice(0, MAX_SERIES);
  const rest = ranked.slice(MAX_SERIES);
  const byKey = [...shown].sort((a, b) => String(a.key).localeCompare(String(b.key), undefined, { numeric: true }));
  const color = new Map(byKey.map((g, i) => [g.key, SERIES[i]]));
  const items = shown.map((g) => ({ key: g.key, label: g.label, color: color.get(g.key) }));
  if (rest.length) items.push({ key: OTHER_KEY, label: `Otros (${rest.length})`, color: OTHER });
  const folded = new Set(rest.map((g) => g.key));
  return {
    items,
    slot: (k) => (folded.has(k) ? OTHER_KEY : k),
    color: (k) => color.get(k) ?? OTHER,
  };
}

/* ------------------------------------------------------------------ CSV */

const FORMULA = /^[=+\-@\t\r]/;

function cell(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return String(v);
  let s = String(v);
  if (FORMULA.test(s)) s = `'${s}`; // spreadsheet formula injection
  return /[",\r\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

const valueOf = (c, r) => (typeof c.value === "function" ? c.value(r) : r[c.key]);

export function toCsv(columns, rows) {
  const head = columns.map((c) => cell(c.label)).join(",");
  return [head, ...rows.map((r) => columns.map((c) => cell(valueOf(c, r))).join(","))].join("\r\n");
}

export function downloadCsv(filename, columns, rows) {
  const blob = new Blob(["﻿" + toCsv(columns, rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ------------------------------------------------------------------ table view */

const TABLE_LIMIT = 500;

/** Accessible table of a chart's values. `columns`: [{key|value, label, format?, numeric?, render?}]. */
export function DataTable({ columns, rows, caption, className }) {
  const shown = rows.slice(0, TABLE_LIMIT);
  return (
    <div className={cn("max-h-96 overflow-auto rounded-[3px] border border-line", className)}>
      <table className="w-full text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="sticky top-0 bg-bg-subtle">
          <tr>{columns.map((c, ci) => (
            <th key={ci} scope="col" className={cn("whitespace-nowrap px-2 py-1.5 text-xs font-semibold text-fg-subtle", c.numeric ? "text-right" : "text-left")}>{c.label}</th>
          ))}</tr>
        </thead>
        <tbody>{shown.map((r, i) => (
          <tr key={i} className="border-t border-line">
            {columns.map((c, ci) => {
              const v = valueOf(c, r);
              return (
                <td key={ci} className={cn("px-2 py-1", c.numeric ? "text-right tabular-nums" : "max-w-[24rem] truncate")}>
                  {c.render ? c.render(r) : c.format ? c.format(v, r) : v ?? "–"}
                </td>
              );
            })}
          </tr>
        ))}</tbody>
      </table>
      {rows.length > TABLE_LIMIT && (
        <p className="border-t border-line px-2 py-1.5 text-xs text-fg-subtle">Se muestran {TABLE_LIMIT} de {rows.length} filas. Descarga el CSV para verlas todas.</p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ card */

/**
 * Chart frame: title, chart ⇄ table toggle and CSV export of exactly the data plotted.
 * `busy` keeps the previous render at reduced opacity while refetching (no skeleton flash).
 */
export function ChartCard({ title, subtitle, columns, rows, csvName, empty, busy, actions, legend, className, children }) {
  const [view, setView] = useState("chart");
  const hasData = !empty && rows?.length;
  return (
    <section className={cn("min-w-0 rounded-[3px] border border-line bg-bg p-4", className)} aria-label={title}>
      <header className="mb-3 flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">{title}</h2>
          {subtitle && <p className="text-xs text-fg-subtle">{subtitle}</p>}
        </div>
        {actions}
        {columns && (
          <>
            <Button size="sm" variant="subtle" aria-pressed={view === "table"} disabled={!hasData}
                    onClick={() => setView(view === "table" ? "chart" : "table")}>
              {view === "table" ? <><BarChart3 size={14} />Gráfico</> : <><Table2 size={14} />Tabla</>}
            </Button>
            <Button size="sm" variant="subtle" disabled={!hasData} onClick={() => downloadCsv(csvName ?? title, columns, rows)}
                    aria-label={`Descargar CSV de «${title}»`}>
              <Download size={14} />CSV
            </Button>
          </>
        )}
      </header>
      <div className={cn("transition-opacity", busy && "opacity-60")}>
        {empty ? <p className="py-10 text-center text-sm text-fg-subtle">{empty}</p>
          : view === "table" && columns ? <DataTable columns={columns} rows={rows} caption={title} />
            : <>{legend}{children}</>}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ legend & tooltip */

/** Legend mirrors the mark: line key for lines, square for bars/areas, dot for points. */
export function LegendRow({ items, className }) {
  if (!items?.length) return null;
  return (
    <ul className={cn("mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-subtle", className)}>
      {items.map((it) => (
        <li key={it.key ?? it.label} className="flex items-center gap-1.5">
          <Key color={it.color} kind={it.kind} />
          <span>{it.label}</span>
        </li>
      ))}
    </ul>
  );
}

function Key({ color, kind = "rect" }) {
  if (kind === "line") return <span className="h-0.5 w-4 rounded-full" style={{ background: color }} />;
  if (kind === "dot") return <span className="h-2 w-2 rounded-full" style={{ background: color }} />;
  if (kind === "band") return <span className="h-2.5 w-4 rounded-sm opacity-40" style={{ background: color }} />;
  return <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />;
}

/** Tooltip body: value strong, series name secondary, short line key. */
export function TooltipCard({ title, rows, footer }) {
  return (
    <div className="pointer-events-none max-w-xs rounded-[3px] border border-line bg-bg-overlay px-3 py-2 text-xs shadow-[var(--shadow-overlay)]">
      {title && <div className="mb-1 font-medium text-fg">{title}</div>}
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 py-0.5">
          {r.color && <span className="h-0.5 w-3 shrink-0 rounded-full" style={{ background: r.color }} />}
          <b className="tabular-nums text-fg">{r.value}</b>
          <span className="text-fg-subtle">{r.label}</span>
        </div>
      ))}
      {footer && <div className="mt-1 text-fg-subtlest">{footer}</div>}
    </div>
  );
}

/** Recharts axis/grid presets: recessive hairlines, text tokens. */
export const AXIS = { tick: { fontSize: 11, fill: "var(--text-subtlest)" }, tickLine: false, axisLine: false };
export const GRID = { stroke: "var(--border)", vertical: false };
export const CURSOR = { stroke: "var(--border-strong)", strokeWidth: 1 };
export const BAR_CURSOR = { fill: "var(--bg-hover)" };

/* ------------------------------------------------------------------ stat tile */

export function StatTile({ label, value, hint, className }) {
  return (
    <div className={cn("min-w-0 rounded-[3px] border border-line bg-bg px-3 py-2.5", className)}>
      <div className="truncate text-xs text-fg-subtle">{label}</div>
      <div className="mt-0.5 text-2xl font-semibold text-fg">{value}</div>
      {hint && <div className="mt-0.5 truncate text-xs text-fg-subtlest">{hint}</div>}
    </div>
  );
}

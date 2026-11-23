"use client";

import { ChevronDown, Columns3, Keyboard, RotateCcw, Search } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { Checkbox, Kbd, Popover, PopoverContent, PopoverTrigger } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export function SearchBox({ value, onChange }) {
  return (
    <div className="relative">
      <Search size={14} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-fg-subtlest" />
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="Buscar en la lista" aria-label="Buscar en la lista"
             className="h-8 w-48 rounded-[3px] border-2 border-line bg-bg pl-7 pr-2 text-sm outline-none focus:border-focus" />
    </div>
  );
}

export function QuickFilters({ filters, value, onToggle }) {
  return (
    <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Filtros rápidos">
      {filters.map((q) => {
        const on = value.includes(q.id);
        return (
          <Button key={q.id} size="sm" variant={on ? "selected" : "subtle"} aria-pressed={on} title={q.description || q.jql}
                  onClick={() => onToggle(q.id)}>{q.label}</Button>
        );
      })}
    </div>
  );
}

export function GroupByPicker({ options, value, onChange }) {
  const opts = [{ value: "", label: "Ninguno" }, ...options];
  const cur = opts.find((o) => o.value === (value ?? ""));
  return (
    <Picker value={value ?? ""} options={opts} onSelect={(v) => onChange(v || null)} width={220} placeholder="Agrupar por"
            trigger={<Button variant={value ? "selected" : "subtle"}>Agrupar: {cur?.label ?? "Ninguno"}<ChevronDown size={14} /></Button>} />
  );
}

/** Choose the visible columns (order and widths are set in the header: drag, resize). */
export function ColumnChooser({ all, visible, onToggle, onReset }) {
  const [q, setQ] = useState("");
  const shown = new Set(visible);
  const list = all.filter((c) => !q || c.label.toLowerCase().includes(q.toLowerCase()));
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="subtle"><Columns3 size={16} />Columnas</Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-0">
        <div className="border-b border-line p-2">
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar campos" aria-label="Buscar campos"
                 className="h-8 w-full rounded-[3px] border-2 border-focus bg-bg px-2 text-sm outline-none" />
        </div>
        <div className="max-h-80 overflow-y-auto px-3 py-2">
          {list.map((c) => (
            <div key={c.id} className="py-1">
              <Checkbox checked={shown.has(c.id)} disabled={shown.has(c.id) && shown.size <= 1}
                        onChange={(on) => onToggle(c.id, on)}
                        label={<span className="flex items-center gap-2">{c.label}{c.kind === "custom" && <span className="text-xs text-fg-subtlest">personalizado</span>}</span>} />
            </div>
          ))}
          {!list.length && <p className="py-2 text-sm text-fg-subtlest">Sin resultados</p>}
        </div>
        <div className="border-t border-line p-2 text-xs text-fg-subtlest">
          Arrastra los encabezados para reordenar y su borde para cambiar el ancho.
          <Button size="sm" variant="subtle" className="mt-2 w-full justify-center" onClick={onReset}><RotateCcw size={14} />Restablecer vista</Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

const SHORTCUTS = [
  ["↑ ↓ ← →", "Moverse entre celdas"],
  ["Intro / F2 / doble clic", "Editar la celda (en la clave: abrir la incidencia)"],
  ["Intro · Tab", "Guardar y pasar a la celda siguiente"],
  ["Esc", "Cancelar la edición"],
  ["Mayús + ↑ ↓ / Mayús + clic", "Seleccionar un rango de la columna"],
  ["Ctrl + C · Ctrl + V", "Copiar · pegar en todas las celdas del rango"],
  ["Supr", "Vaciar las celdas del rango"],
  ["Espacio", "Seleccionar la fila (cambio masivo)"],
  ["Alt + → / Alt + ←", "Expandir / contraer hijas"],
  ["Inicio · Fin · AvPág · RePág", "Saltar"],
];

export function ShortcutsHelp() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="subtle" size="icon" aria-label="Atajos de teclado"><Keyboard size={16} /></Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-3">
        <h3 className="mb-2 text-sm font-semibold">Atajos de teclado</h3>
        <dl className="space-y-1.5 text-sm">
          {SHORTCUTS.map(([k, d]) => (
            <div key={k} className="grid grid-cols-[150px_1fr] gap-2">
              <dt className={cn("text-fg-subtle")}><Kbd>{k}</Kbd></dt><dd>{d}</dd>
            </div>
          ))}
        </dl>
      </PopoverContent>
    </Popover>
  );
}

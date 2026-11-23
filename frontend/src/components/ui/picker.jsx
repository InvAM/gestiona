"use client";

import { Command } from "cmdk";
import { Check } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "./primitives";

export function Picker({
  trigger, options, value, onSelect, multiple, placeholder = "Buscar...", onSearch, loading,
  emptyText = "Sin resultados", footer, width = 280, align = "start", open: openProp,
  onOpenChange, creatable, onCreate,
}) {
  const [openState, setOpenState] = useState(false);
  const [q, setQ] = useState("");
  const open = openProp ?? openState;
  const setOpen = (o) => {
    onOpenChange?.(o);
    if (openProp === undefined) setOpenState(o);
    if (!o) {
      setQ("");
      onSearch?.("");
    }
  };
  const selected = new Set(Array.isArray(value) ? value : value != null ? [value] : []);
  const createNode = creatable && q.trim() ? creatable(q.trim()) : null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent align={align} style={{ width }} className="p-0"
                      onOpenAutoFocus={(e) => e.preventDefault()}>
        <Command shouldFilter={!onSearch} loop>
          <div className="border-b border-line p-2">
            <Command.Input autoFocus value={q}
                           onValueChange={(v) => { setQ(v); onSearch?.(v); }}
                           placeholder={placeholder}
                           className="h-8 w-full rounded-[3px] border-2 border-focus bg-bg px-2 text-sm outline-none placeholder:text-fg-subtlest" />
          </div>
          <Command.List className="max-h-72 overflow-y-auto py-1">
            {loading && <Command.Loading><div className="px-3 py-2 text-sm text-fg-subtlest">Buscando…</div></Command.Loading>}
            <Command.Empty className="px-3 py-2 text-sm text-fg-subtlest">{emptyText}</Command.Empty>
            {options.map((o) => (
              <Command.Item key={String(o.value)} value={`${o.label} ${o.description ?? ""} ${o.value}`}
                            onSelect={() => { onSelect(o.value); if (!multiple) setOpen(false); }}
                            className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm data-[selected=true]:bg-bg-hover">
                {o.icon}
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{o.label}</span>
                  {o.description && <span className="block truncate text-xs text-fg-subtlest">{o.description}</span>}
                </span>
                <Check size={14} className={cn("shrink-0 text-brand", !selected.has(o.value) && "invisible")} />
              </Command.Item>
            ))}
            {createNode && (
              <Command.Item value={`__create__ ${q}`} onSelect={() => { onCreate?.(q.trim()); setQ(""); }}
                            className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm data-[selected=true]:bg-bg-hover">
                {createNode}
              </Command.Item>
            )}
          </Command.List>
          {footer && <div className="border-t border-line p-1">{footer}</div>}
        </Command>
      </PopoverContent>
    </Popover>
  );
}

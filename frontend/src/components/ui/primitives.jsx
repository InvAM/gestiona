"use client";

import { Dialog as D, DropdownMenu, Popover as P, Tooltip as T } from "radix-ui";
import { X } from "lucide-react";
import {
  forwardRef,
} from "react";
import { cn } from "@/lib/utils";
import { Button } from "./button";

/* ------------------------------------------------------------------ Avatar */

const AV = { xs: "h-5 w-5 text-[9px]", sm: "h-6 w-6 text-[10px]", md: "h-8 w-8 text-xs",
             lg: "h-10 w-10 text-sm", xl: "h-24 w-24 text-3xl" };

export function Avatar({ user, size = "sm", className, title }) {
  const label = title ?? user?.name ?? "Sin asignar";
  if (!user) {
    return (
      <span title={label} className={cn("inline-flex shrink-0 items-center justify-center rounded-full bg-bg-sunken text-fg-subtlest", AV[size], className)}>
        <svg viewBox="0 0 24 24" className="h-[65%] w-[65%]" fill="currentColor">
          <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm0 2c-4 0-8 2-8 5v1h16v-1c0-3-4-5-8-5Z" />
        </svg>
      </span>
    );
  }
  if (user.avatar_url) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={user.avatar_url} alt={label} title={label} className={cn("shrink-0 rounded-full object-cover", AV[size], className)} />;
  }
  return (
    <span title={label} style={{ backgroundColor: user.color }}
          className={cn("inline-flex shrink-0 select-none items-center justify-center rounded-full font-semibold text-white", AV[size], className)}>
      {user.initials}
    </span>
  );
}

export function AvatarStack({ users, max = 4, onToggle, selected = [] }) {
  const shown = users.slice(0, max);
  return (
    <div className="flex items-center -space-x-1">
      {shown.map((u) => (
        <button key={u.id} type="button" onClick={() => onToggle?.(u.id)}
                className={cn("rounded-full ring-2 ring-bg transition-transform hover:z-10 hover:-translate-y-0.5",
                              selected.includes(u.id) && "ring-brand z-10")}>
          <Avatar user={u} size="md" />
        </button>
      ))}
      {users.length > max && (
        <span className="z-0 inline-flex h-8 w-8 items-center justify-center rounded-full bg-bg-sunken text-xs font-medium text-fg-subtle ring-2 ring-bg">
          +{users.length - max}
        </span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Lozenge */

const LZ = {
  todo: "bg-[var(--lz-todo-bg)] text-[var(--lz-todo-fg)]",
  in_progress: "bg-[var(--lz-progress-bg)] text-[var(--lz-progress-fg)]",
  done: "bg-[var(--lz-done-bg)] text-[var(--lz-done-fg)]",
};

export function Lozenge({ category, children, className }) {
  return (
    <span className={cn("inline-flex max-w-full items-center truncate rounded-[3px] px-1 text-[11px] font-bold uppercase leading-4", LZ[category] ?? LZ.todo, className)}>
      {children}
    </span>
  );
}

export function Badge({ children, className }) {
  return (
    <span className={cn("inline-flex min-w-5 items-center justify-center rounded-full bg-bg-sunken px-1.5 text-xs font-semibold text-fg-subtle", className)}>
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ Inputs */

export const Input = forwardRef(
  function Input({ className, invalid, ...p }, ref) {
    return (
      <input ref={ref} {...p}
             className={cn("h-8 w-full rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-subtlest hover:bg-bg-hover focus:border-focus focus:bg-bg",
                           invalid && "border-danger", className)} />
    );
  },
);

export const Textarea = forwardRef(
  function Textarea({ className, ...p }, ref) {
    return (
      <textarea ref={ref} {...p}
                className={cn("w-full rounded-[3px] border-2 border-line bg-bg-subtle px-2 py-1.5 text-sm outline-none placeholder:text-fg-subtlest hover:bg-bg-hover focus:border-focus focus:bg-bg", className)} />
    );
  },
);

export function Field({ label, required, error, hint, children, className }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1 block text-xs font-semibold text-fg-subtle">
        {label}{required && <span className="ml-0.5 text-danger">*</span>}
      </span>
      {children}
      {error ? <span className="mt-1 block text-xs text-danger">{error}</span>
        : hint ? <span className="mt-1 block text-xs text-fg-subtlest">{hint}</span> : null}
    </label>
  );
}

export function Checkbox({ checked, onChange, label, disabled }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
      <input type="checkbox" className="h-4 w-4 accent-[var(--brand)]" checked={checked}
             disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export function Toggle({ checked, onChange, label, disabled, title }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} title={title}
            onClick={() => onChange(!checked)}
            className={cn("relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                          checked ? "bg-success" : "bg-line-strong")}>
      <span className={cn("inline-block h-4 w-4 rounded-full bg-white shadow transition-transform",
                          checked ? "translate-x-[18px]" : "translate-x-0.5")} />
    </button>
  );
}

/* ------------------------------------------------------------------ Tooltip */

export function Tip({ content, children, side = "top" }) {
  if (!content) return <>{children}</>;
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content side={side} sideOffset={6}
                   className="z-[100] max-w-xs rounded-[3px] bg-[#172b4d] px-2 py-0.5 text-xs text-white shadow-overlay">
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}

/* ------------------------------------------------------------------ Dropdown menu */

export const Menu = DropdownMenu.Root;
export const MenuTrigger = DropdownMenu.Trigger;

export function MenuContent({ children, align = "start", className, ...p }) {
  return (
    <DropdownMenu.Portal>
      <DropdownMenu.Content align={align} sideOffset={4} {...p}
                            className={cn("z-[90] min-w-44 overflow-hidden rounded-[3px] border border-line bg-bg-overlay py-1.5 shadow-overlay", className)}>
        {children}
      </DropdownMenu.Content>
    </DropdownMenu.Portal>
  );
}

export function MenuItem({ children, className, danger, ...p }) {
  return (
    <DropdownMenu.Item {...p}
                       className={cn("flex cursor-pointer select-none items-center gap-2 px-3 py-1.5 text-sm outline-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-bg-hover",
                                     danger && "text-danger", className)}>
      {children}
    </DropdownMenu.Item>
  );
}

export function MenuLabel({ children }) {
  return <DropdownMenu.Label className="px-3 pb-1 pt-2 text-[11px] font-bold uppercase text-fg-subtlest">{children}</DropdownMenu.Label>;
}

export const MenuSeparator = () => <DropdownMenu.Separator className="my-1.5 h-px bg-line" />;

/* ------------------------------------------------------------------ Popover */

export const Popover = P.Root;
export const PopoverTrigger = P.Trigger;
export const PopoverAnchor = P.Anchor;

export function PopoverContent({ children, className, align = "start", ...p }) {
  return (
    <P.Portal>
      <P.Content align={align} sideOffset={4} {...p}
                 className={cn("z-[90] rounded-[3px] border border-line bg-bg-overlay shadow-overlay outline-none", className)}>
        {children}
      </P.Content>
    </P.Portal>
  );
}

/* ------------------------------------------------------------------ Dialog */

export function Modal({ open, onOpenChange, title, children, footer, width = 600, className,
                        hideClose }) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-[80] bg-[#091e427d]" />
        <D.Content style={{ maxWidth: width }}
                   aria-describedby={undefined}
                   className={cn("fixed left-1/2 top-[8vh] z-[80] flex max-h-[84vh] w-[calc(100vw-32px)] -translate-x-1/2 flex-col rounded-[3px] bg-bg-overlay shadow-overlay outline-none", className)}>
          {title !== undefined && (
            <div className="flex items-center justify-between gap-4 px-6 pb-2 pt-5">
              <D.Title className="text-xl font-medium">{title}</D.Title>
              {!hideClose && (
                <D.Close asChild>
                  <Button variant="subtle" size="icon" aria-label="Cerrar"><X size={18} /></Button>
                </D.Close>
              )}
            </div>
          )}
          {title === undefined && <D.Title className="sr-only">Diálogo</D.Title>}
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-2">{children}</div>
          {footer && <div className="flex justify-end gap-2 px-6 pb-5 pt-4">{footer}</div>}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

export function Confirm({ open, onOpenChange, title, body, confirmLabel = "Confirmar", danger,
                          onConfirm, loading }) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={title} width={440} hideClose
           footer={<>
             <Button variant="subtle" onClick={() => onOpenChange(false)}>Cancelar</Button>
             <Button variant={danger ? "danger" : "primary"} loading={loading} onClick={onConfirm}>{confirmLabel}</Button>
           </>}>
      <div className="text-sm text-fg">{body}</div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ Misc */

export function EmptyState({ title, body, action, icon }) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center px-4 py-16 text-center">
      {icon && <div className="mb-4 text-fg-subtlest">{icon}</div>}
      <h3 className="text-xl font-medium">{title}</h3>
      {body && <p className="mt-2 text-fg-subtle">{body}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function Kbd({ children }) {
  return <kbd className="rounded-[3px] border border-line bg-bg-subtle px-1 text-[11px] font-medium text-fg-subtle">{children}</kbd>;
}

export function Tabs({ value, onChange, tabs, className }) {
  return (
    <div role="tablist" className={cn("flex gap-1 border-b-2 border-line", className)}>
      {tabs.map((t) => (
        <button key={t.value} role="tab" aria-selected={value === t.value} type="button"
                onClick={() => onChange(t.value)}
                className={cn("-mb-0.5 border-b-2 px-2 pb-1.5 pt-1 text-sm font-medium transition-colors",
                              value === t.value ? "border-brand text-brand" : "border-transparent text-fg-subtle hover:text-fg")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

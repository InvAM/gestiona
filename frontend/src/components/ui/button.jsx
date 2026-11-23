import { Slot } from "radix-ui";
import { forwardRef } from "react";
import { cn } from "@/lib/utils";

const variants = {
  primary: "bg-brand text-fg-inverse hover:bg-brand-hover active:bg-brand-pressed",
  default: "bg-bg-hover text-fg-subtle hover:bg-bg-pressed active:bg-bg-pressed",
  subtle: "bg-transparent text-fg-subtle hover:bg-bg-hover active:bg-bg-pressed",
  danger: "bg-danger text-fg-inverse hover:opacity-90",
  warning: "bg-warning text-fg-inverse hover:opacity-90",
  link: "bg-transparent text-link hover:underline px-0",
  selected: "bg-bg-selected text-brand",
};

const sizes = {
  sm: "h-6 px-2 text-[13px] gap-1",
  md: "h-8 px-3 gap-1.5",
  icon: "h-8 w-8 justify-center",
  "icon-sm": "h-6 w-6 justify-center",
};

export const Button = forwardRef(function Button(
  { variant = "default", size = "md", asChild, loading, className, children, disabled, ...rest },
  ref,
) {
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      ref={ref}
      type={asChild ? undefined : (rest.type ?? "button")}
      disabled={disabled || loading}
      className={cn(
        "inline-flex shrink-0 select-none items-center rounded-[3px] font-medium transition-colors",
        "disabled:pointer-events-none disabled:opacity-50 whitespace-nowrap",
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {asChild ? children : <>{loading ? <Spinner className="h-4 w-4" /> : null}{children}</>}
    </Comp>
  );
});

export function Spinner({ className }) {
  return (
    <svg className={cn("h-5 w-5 animate-spin text-current", className)} viewBox="0 0 24 24"
         fill="none" aria-label="Cargando">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity=".25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function PageSpinner() {
  return (
    <div className="flex h-full min-h-40 w-full items-center justify-center text-fg-subtlest">
      <Spinner className="h-8 w-8" />
    </div>
  );
}

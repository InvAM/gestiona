import {
  Bookmark, Bug, Check, ChevronDown, ChevronsDown, ChevronsUp, ChevronUp, Equal, Layers, Zap,
  Briefcase, Code2, Rocket, Megaphone, Palette, Database, Shield, Globe, Cpu, Heart, Star, Box,
} from "lucide-react";
import { cn } from "@/lib/utils";

const TYPE_GLYPH = {
  epic: Zap, story: Bookmark, task: Check, bug: Bug, subtask: Layers,
};

/** Square issue-type icon (colored tile + white glyph). */
export function IssueTypeIcon({ type, size = 16, className }) {
  if (!type) return null;
  const Glyph = TYPE_GLYPH[type.icon] ?? Check;
  return (
    <span title={type.name} style={{ backgroundColor: type.color, width: size, height: size }}
          className={cn("inline-flex shrink-0 items-center justify-center rounded-[3px] text-white", className)}>
      <Glyph size={size * 0.68} strokeWidth={3} fill={type.icon === "story" || type.icon === "epic" ? "currentColor" : "none"} />
    </span>
  );
}

const PRIO = {
  highest: ChevronsUp, high: ChevronUp, medium: Equal, low: ChevronDown, lowest: ChevronsDown,
};

export function PriorityIcon({ priority, size = 16, className }) {
  if (!priority) return null;
  const G = PRIO[priority.icon] ?? Equal;
  return (
    <span title={priority.name} className={cn("inline-flex shrink-0", className)} style={{ color: priority.color }}>
      <G size={size} strokeWidth={2.75} />
    </span>
  );
}

const PROJECT_GLYPH = {
  rocket: Rocket, briefcase: Briefcase, code: Code2, megaphone: Megaphone, palette: Palette,
  database: Database, shield: Shield, globe: Globe, cpu: Cpu, heart: Heart, star: Star, box: Box,
};
export const PROJECT_ICONS = Object.keys(PROJECT_GLYPH);
export const PROJECT_COLORS = ["#1D5FD6", "#1F845A", "#C9372C", "#6E5DC6", "#E56910", "#0E7C86",
                               "#AE2E74", "#44546F"];

export function ProjectAvatar({ project, size = 24, className }) {
  if (!project) return null;
  const G = PROJECT_GLYPH[project.avatar] ?? Rocket;
  return (
    <span title={project.name} style={{ backgroundColor: project.color, width: size, height: size }}
          className={cn("inline-flex shrink-0 items-center justify-center rounded-[4px] text-white", className)}>
      <G size={size * 0.6} strokeWidth={2.25} />
    </span>
  );
}

/** Gestiona logo: stacked cards forming a "G" progression. */
export function Logo({ size = 24, withText = true }) {
  return (
    <span className="inline-flex items-center gap-2">
      <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
        <rect x="2" y="2" width="28" height="28" rx="7" fill="var(--brand)" />
        <path d="M21.5 11.2A7 7 0 1 0 23 16h-6.5" fill="none" stroke="#fff" strokeWidth="3.2"
              strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="23" cy="16" r="1.9" fill="#7CE0B8" />
      </svg>
      {withText && <span className="text-[17px] font-bold tracking-tight text-fg">Gestiona</span>}
    </span>
  );
}

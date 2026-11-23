import { clsx } from "clsx";
import { format, formatDistanceToNowStrict, isToday, isYesterday, parseISO } from "date-fns";
import { es } from "date-fns/locale";
import { twMerge } from "tailwind-merge";

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

const toDate = (d) => (typeof d === "string" ? parseISO(d) : d);

export function fmtDate(d, pattern = "d MMM yyyy") {
  if (!d) return "";
  return format(toDate(d), pattern, { locale: es });
}

export function fmtDateTime(d) {
  if (!d) return "";
  return format(toDate(d), "d MMM yyyy, HH:mm", { locale: es });
}

/** "hace 5 minutos", "ayer a las 14:20", "3 de marzo de 2026" — like Jira's relative dates. */
export function fmtRelative(d) {
  if (!d) return "";
  const date = toDate(d);
  const diff = Date.now() - date.getTime();
  if (diff < 60_000) return "justo ahora";
  if (diff < 24 * 3600_000 && isToday(date))
    return `hace ${formatDistanceToNowStrict(date, { locale: es })}`;
  if (isYesterday(date)) return `ayer a las ${format(date, "HH:mm")}`;
  if (diff < 7 * 24 * 3600_000) return format(date, "EEEE 'a las' HH:mm", { locale: es });
  return format(date, "d 'de' MMMM 'de' yyyy", { locale: es });
}

/** Jira duration format: 1w 2d 3h 30m (1d = 8h, 1w = 5d). */
export function fmtDuration(seconds) {
  if (!seconds) return "0m";
  const units = [["w", 5 * 8 * 3600], ["d", 8 * 3600], ["h", 3600], ["m", 60]];
  let rest = seconds;
  const parts = [];
  for (const [u, s] of units) {
    const n = Math.floor(rest / s);
    if (n) {
      parts.push(`${n}${u}`);
      rest -= n * s;
    }
  }
  return parts.join(" ") || "0m";
}

export function parseDuration(input) {
  const s = input.trim().toLowerCase();
  if (!s) return null;
  if (/^\d+(\.\d+)?$/.test(s)) return Math.round(parseFloat(s) * 3600); // bare number = hours
  const re = /(\d+(?:\.\d+)?)\s*([wdhm])/g;
  const mult = { w: 5 * 8 * 3600, d: 8 * 3600, h: 3600, m: 60 };
  let total = 0;
  let matched = "";
  let m;
  while ((m = re.exec(s))) {
    total += parseFloat(m[1]) * mult[m[2]];
    matched += m[0];
  }
  if (matched.replace(/\s/g, "") !== s.replace(/\s/g, "")) return null;
  return Math.round(total);
}

export function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function fmtPoints(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "string" ? parseFloat(v) : v;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

export function pluralize(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

// Swimlane modes the board renders (labels come from GET /meta → board_swimlanes).
export const BOARD_LANES = ["none", "assignee", "epic", "priority"];

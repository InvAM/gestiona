"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api/client";

const PATHS = {
  flow: "/api/v1/analytics/flow",
  control: "/api/v1/analytics/control-chart",
  tis: "/api/v1/analytics/time-in-status",
};

/** GET /analytics/{flow|control-chart|time-in-status}; keeps the previous data while refetching. */
export function useAnalytics(kind, query, enabled = true) {
  return useQuery({
    queryKey: ["analytics", kind, query],
    queryFn: () => unwrap(api.GET(PATHS[kind], { params: { query } })),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: false,
    enabled,
  });
}

const iso = (d) => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
};

/** Inclusive start/end (YYYY-MM-DD) of a filter value, `now` from useNow() (pure render). */
export function dateRange(value, now) {
  if (value.preset) {
    const end = new Date(now);
    const start = new Date(now);
    start.setDate(start.getDate() - (value.preset - 1));
    return { start: iso(start), end: iso(end) };
  }
  return { start: value.start, end: value.end };
}

export function daysBetween(start, end) {
  if (!start || !end) return 0;
  return Math.round((Date.parse(end) - Date.parse(start)) / 86_400_000) + 1;
}

/** API query params for a filter value. `fixedProjects` scopes to a project (reports). */
export function toQuery(value, now, { fixedProjects, metric } = {}) {
  const { start, end } = dateRange(value, now);
  const q = { start, end };
  const projects = fixedProjects ?? (value.source === "projects" ? value.projects.join(",") : "");
  if (projects) q.projects = projects;
  if ((fixedProjects || value.source === "jql") && value.jql?.trim()) q.jql = value.jql.trim();
  if (value.group_by) q.group_by = value.group_by;
  if (value.interval) q.interval = value.interval;
  if (metric) q.metric = metric;
  return q;
}

export const DEFAULT_FILTERS = {
  source: "projects", projects: [], jql: "", preset: 90, start: "", end: "",
  group_by: "", interval: "week", metric: "cycle",
};

/** Filter value ⇄ URL search params (shareable analytics links). */
export function filtersFromParams(params) {
  const v = { ...DEFAULT_FILTERS };
  const get = (k) => params.get(k) ?? "";
  if (get("jql")) { v.source = "jql"; v.jql = get("jql"); }
  if (get("projects")) { v.source = "projects"; v.projects = get("projects").split(",").filter(Boolean); }
  if (get("start") && get("end")) { v.preset = null; v.start = get("start"); v.end = get("end"); }
  else if (Number(get("days")) > 0) v.preset = Number(get("days"));
  if (get("group_by")) v.group_by = get("group_by");
  if (get("interval")) v.interval = get("interval");
  if (get("metric")) v.metric = get("metric");
  return v;
}

export function filtersToParams(v) {
  const p = new URLSearchParams();
  if (v.source === "projects" && v.projects.length) p.set("projects", v.projects.join(","));
  if (v.source === "jql" && v.jql.trim()) p.set("jql", v.jql.trim());
  if (v.preset) { if (v.preset !== DEFAULT_FILTERS.preset) p.set("days", String(v.preset)); }
  else if (v.start && v.end) { p.set("start", v.start); p.set("end", v.end); }
  if (v.group_by) p.set("group_by", v.group_by);
  if (v.interval && v.interval !== DEFAULT_FILTERS.interval) p.set("interval", v.interval);
  if (v.metric && v.metric !== DEFAULT_FILTERS.metric) p.set("metric", v.metric);
  return p;
}

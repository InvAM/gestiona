"use client";

// Flow reports inside a project (Informes): control chart, time in status and throughput.
// Same endpoints as /analytics, scoped to the project and refinable with JQL.

import Link from "next/link";
import { useState } from "react";
import { errorMessage } from "@/lib/api/client";
import { useMeta } from "@/lib/api/hooks";
import { useNow } from "@/lib/use-now";
import { ControlChartCard, CreatedResolvedChart, KpiRow, ThroughputChart, TimeInStatusChart } from "./charts";
import { FiltersBar, MetricToggle, rangeIsValid } from "./filters";
import { DEFAULT_FILTERS, daysBetween, filtersToParams, toQuery, useAnalytics } from "./use-analytics";

const API_KIND = { control: "control", tis: "tis", throughput: "flow" };

export function ProjectFlowReport({ projectKey, kind }) {
  const meta = useMeta();
  const now = useNow();
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const valid = rangeIsValid(filters, now, meta.data?.analytics?.max_range_days);
  const q = toQuery(filters, now, { fixedProjects: projectKey, metric: kind === "control" ? filters.metric : undefined });
  if (kind !== "throughput") delete q.interval;
  if (kind === "tis") delete q.group_by;
  const r = useAnalytics(API_KIND[kind], q, valid);
  const busy = r.isPlaceholderData;
  const d = r.data;
  const globalLink = `/analytics?${filtersToParams({ ...filters, source: "projects", projects: [projectKey], jql: "" })}`;
  return (
    <div className="space-y-4">
      <FiltersBar value={filters} onChange={setFilters} now={now} showSource={false} jqlOnly
                  showGroup={kind !== "tis"} showInterval={kind === "throughput"} />
      {r.error && <p role="alert" className="rounded-[3px] border border-danger bg-danger-subtle px-3 py-2 text-sm">{errorMessage(r.error)}</p>}
      {kind === "control" && (
        <ControlChartCard data={d} busy={busy} height={380}
                          actions={<MetricToggle value={filters.metric} onChange={(m) => setFilters({ ...filters, metric: m })} />} />
      )}
      {kind === "tis" && <TimeInStatusChart data={d} busy={busy} categories={meta.data?.status_categories} />}
      {kind === "throughput" && d && (
        <>
          <KpiRow kpis={d.kpis} days={daysBetween(d.scope.start, d.scope.end)} />
          <ThroughputChart rows={d.throughput} groups={d.groups} groupLabel={d.scope.group_label} interval={d.scope.interval} busy={busy} height={300} />
          <CreatedResolvedChart rows={d.created_vs_resolved} interval={d.scope.interval} busy={busy} />
        </>
      )}
      <p className="text-xs text-fg-subtle">
        {(meta.data?.analytics?.metrics ?? []).map((m) => `${m.label}: ${m.description.charAt(0).toLowerCase()}${m.description.slice(1)}.`).join(" ")}{" "}
        <Link className="text-link hover:underline" href={globalLink}>Abrir en Analíticas</Link>
      </p>
    </div>
  );
}

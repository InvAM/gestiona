"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Spinner } from "@/components/ui/button";
import { errorMessage } from "@/lib/api/client";
import { useMeta } from "@/lib/api/hooks";
import { useNow } from "@/lib/use-now";
import {
  ControlChartCard, CreatedResolvedChart, CycleHistogram, GroupTable, KpiRow, ThroughputChart,
  TimeInStatusChart, WipList,
} from "./charts";
import { FiltersBar, MetricToggle, rangeIsValid } from "./filters";
import { daysBetween, filtersFromParams, filtersToParams, toQuery, useAnalytics } from "./use-analytics";

function withoutKeys(q, keys) {
  const out = { ...q };
  keys.forEach((k) => delete out[k]);
  return out;
}

export function AnalyticsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const meta = useMeta();
  const now = useNow();
  const [filters, setFilters] = useState(() => filtersFromParams(params));
  const update = (next) => {
    setFilters(next);
    const qs = filtersToParams(next).toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  const valid = rangeIsValid(filters, now, meta.data?.analytics?.max_range_days);
  const base = toQuery(filters, now);
  const flow = useAnalytics("flow", base, valid);
  const control = useAnalytics("control", { ...withoutKeys(base, ["interval"]), metric: filters.metric }, valid);
  const tis = useAnalytics("tis", withoutKeys(base, ["interval", "group_by"]), valid);
  const error = flow.error ?? control.error ?? tis.error;
  const f = flow.data;
  const groupLabel = f?.scope.group_label;
  const labels = new Map((f?.groups ?? []).map((g) => [g.key, g.label]));

  return (
    <div className="mx-auto w-full max-w-[1400px] px-6 py-5">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-2xl font-medium">Analíticas</h1>
        <p className="text-sm text-fg-subtle">Flujo de trabajo de las incidencias que puedes ver: tiempos de ciclo y de entrega, throughput y trabajo en curso.</p>
        {(flow.isFetching || control.isFetching || tis.isFetching) && <Spinner className="h-4 w-4" />}
      </div>
      <div className="mt-4 rounded-[3px] border border-line bg-bg-subtle p-3">
        <FiltersBar value={filters} onChange={update} now={now} />
      </div>
      {error && <p role="alert" className="mt-4 rounded-[3px] border border-danger bg-danger-subtle px-3 py-2 text-sm text-fg">{errorMessage(error)}</p>}
      {f && (
        <div className="mt-4 space-y-4">
          <KpiRow kpis={f.kpis} days={daysBetween(f.scope.start, f.scope.end)} />
          <div className="grid gap-4 xl:grid-cols-2">
            <CreatedResolvedChart rows={f.created_vs_resolved} interval={f.scope.interval} busy={flow.isPlaceholderData} />
            <ThroughputChart rows={f.throughput} groups={f.groups} groupLabel={groupLabel} interval={f.scope.interval} busy={flow.isPlaceholderData} />
          </div>
          <ControlChartCard data={control.data} busy={control.isPlaceholderData}
                            actions={<MetricToggle value={filters.metric} onChange={(m) => update({ ...filters, metric: m })} />} />
          <div className="grid gap-4 xl:grid-cols-2">
            <CycleHistogram bins={f.cycle_histogram} busy={flow.isPlaceholderData} />
            <TimeInStatusChart data={tis.data} busy={tis.isPlaceholderData} categories={meta.data?.status_categories} />
          </div>
          {groupLabel && <GroupTable rows={f.by_group} label={groupLabel} busy={flow.isPlaceholderData} />}
          <WipList items={f.wip_oldest} busy={flow.isPlaceholderData} groupLabels={groupLabel ? labels : null} />
        </div>
      )}
      {!f && !error && valid && <div className="flex h-60 items-center justify-center"><Spinner /></div>}
    </div>
  );
}

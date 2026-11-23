"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api/client";

export const planKeys = {
  list: (q) => ["plans", q ?? ""],
  plan: (id) => ["plan", id],
  data: (id) => ["plan-data", id],
  capacity: (id, n) => ["plan-capacity", id, n],
  releases: (id) => ["plan-releases", id],
  versions: (id) => ["plan-versions", id],
  teams: (q) => ["teams", q ?? ""],
};

const path = (pid) => ({ params: { path: { pid } } });

export function usePlans(q) {
  return useQuery({
    queryKey: planKeys.list(q),
    queryFn: () => unwrap(api.GET("/api/v1/plans", { params: { query: { q } } })),
    placeholderData: keepPreviousData,
  });
}

export function usePlan(id) {
  return useQuery({
    queryKey: planKeys.plan(id),
    queryFn: () => unwrap(api.GET("/api/v1/plans/{pid}", path(id))),
    retry: false,
  });
}

/* Timeline: everything lives under planKeys.data(id) so one invalidation refreshes it. */

/** Totals, date range and filter catalogs of the whole plan (no issues). */
export function usePlanTimeline(id) {
  return useQuery({
    queryKey: [...planKeys.data(id), "meta"],
    queryFn: () => unwrap(api.GET("/api/v1/plans/{pid}/timeline", path(id))),
  });
}

/** Groups with their total count, filters applied on the server. */
export function usePlanGroups(id, groupBy, filters, enabled = true) {
  return useQuery({
    queryKey: [...planKeys.data(id), "groups", groupBy, filters],
    queryFn: () => unwrap(api.POST("/api/v1/plans/{pid}/timeline/groups", { ...path(id), body: { group_by: groupBy, filters } })),
    placeholderData: keepPreviousData,
    enabled,
  });
}

/* The viewer's own timeline layout (grouping, filters, scale, collapsed), saved per plan. */
const viewQueryKey = (id) => ["plan-view", id];

export function usePlanView(id) {
  return useQuery({
    queryKey: viewQueryKey(id),
    queryFn: () => unwrap(api.GET("/api/v1/plans/{pid}/view", path(id))),
    staleTime: Infinity,
    retry: 1,
  });
}

export async function savePlanView(qc, id, view) {
  const saved = await unwrap(api.PUT("/api/v1/plans/{pid}/view", { ...path(id), body: view }));
  qc.setQueryData(viewQueryKey(id), saved);
  return saved;
}

/** Date conflicts of every dependency in the plan, computed on the server. */
export function usePlanConflicts(id) {
  return useQuery({
    queryKey: [...planKeys.data(id), "conflicts"],
    queryFn: () => unwrap(api.GET("/api/v1/plans/{pid}/conflicts", path(id))),
  });
}

export const planRowsKey = (id) => [...planKeys.data(id), "rows"];

/** At most `max` requests at a time, the rest wait in order (FIFO = viewport order). */
function createLimiter(max) {
  let active = 0;
  const queue = [];
  const next = () => {
    if (active >= max || !queue.length) return;
    const { task, resolve, reject } = queue.shift();
    active += 1;
    Promise.resolve().then(task).then(resolve, reject).finally(() => { active -= 1; next(); });
  };
  return (task) => new Promise((resolve, reject) => { queue.push({ task, resolve, reject }); next(); });
}
const rowsLimiter = createLimiter(4);

/** One page of one hierarchy node (group roots or an issue's children). */
export function planRowsQuery(id, body) {
  return {
    queryKey: [...planRowsKey(id), body],
    queryFn: ({ signal }) => rowsLimiter(() => {
      // skipped if nobody needs it any more by the time its turn comes
      if (signal?.aborted) throw new DOMException("Cancelada", "AbortError");
      return unwrap(api.POST("/api/v1/plans/{pid}/timeline/rows", { ...path(id), body, signal }));
    }),
    staleTime: 30_000,
  };
}

export function usePlanCapacity(id, iterations) {
  return useQuery({
    queryKey: planKeys.capacity(id, iterations),
    queryFn: () => unwrap(api.GET("/api/v1/plans/{pid}/capacity", { params: { path: { pid: id }, query: { iterations } } })),
    placeholderData: keepPreviousData,
  });
}

export function usePlanReleases(id) {
  return useQuery({
    queryKey: planKeys.releases(id),
    queryFn: () => unwrap(api.GET("/api/v1/plans/{pid}/releases", path(id))),
  });
}

export function usePlanVersionOptions(id, enabled = true) {
  return useQuery({
    queryKey: planKeys.versions(id),
    queryFn: () => unwrap(api.GET("/api/v1/plans/{pid}/versions", path(id))),
    enabled,
  });
}

export function useTeams(q) {
  return useQuery({
    queryKey: planKeys.teams(q),
    queryFn: () => unwrap(api.GET("/api/v1/teams", { params: { query: { q } } })),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

/** Everything derived from a plan's issues (data, capacity, releases) goes stale together. */
export function invalidatePlanViews(qc, id) {
  qc.invalidateQueries({ queryKey: planKeys.data(id) });
  qc.invalidateQueries({ queryKey: ["plan-capacity", id] });
  qc.invalidateQueries({ queryKey: planKeys.releases(id) });
}

export function useSavePlan(plan) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => plan
      ? unwrap(api.PATCH("/api/v1/plans/{pid}", { ...path(plan.id), body }))
      : unwrap(api.POST("/api/v1/plans", { body })),
    onSuccess: (p) => {
      qc.setQueryData(planKeys.plan(p.id), p);
      qc.invalidateQueries({ queryKey: ["plans"] });
      invalidatePlanViews(qc, p.id);
    },
  });
}

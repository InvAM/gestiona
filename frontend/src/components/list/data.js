"use client";

import { keepPreviousData, useInfiniteQuery, useQueries, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api/client";

export const PAGE = 200;

// Every query of the view lives under ["list", projectKey, ...] so cache patches and
// invalidations never touch the board/backlog/search caches (and vice versa).
export const lk = {
  all: (p) => ["list", p],
  meta: (p) => ["list", p, "meta"],
  config: (p) => ["list", p, "config"],
  pages: (p, jql, groupBy) => ["list", p, "pages", jql, groupBy ?? ""],
  groups: (p, jql, groupBy) => ["list", p, "groups", jql, groupBy ?? ""],
  children: (p, parentId) => ["list", p, "children", parentId],
};

export function useListMeta(projectKey) {
  return useQuery({
    queryKey: lk.meta(projectKey),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{key}/list/meta", { params: { path: { key: projectKey } } })),
    staleTime: 60_000,
  });
}

export function useListConfig(projectKey) {
  return useQuery({
    queryKey: lk.config(projectKey),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{key}/list/config", { params: { path: { key: projectKey } } })),
    staleTime: Infinity,
    retry: 1,
  });
}

export function saveListConfig(projectKey, config) {
  return unwrap(api.PUT("/api/v1/projects/{key}/list/config", { params: { path: { key: projectKey } }, body: config }));
}

export function resetListConfig(projectKey) {
  return unwrap(api.DELETE("/api/v1/projects/{key}/list/config", { params: { path: { key: projectKey } } }));
}

function fetchPage(projectKey, body) {
  return unwrap(api.POST("/api/v1/projects/{key}/list", { params: { path: { key: projectKey } }, body }));
}

export function useListPages(projectKey, jql, groupBy, enabled) {
  return useInfiniteQuery({
    queryKey: lk.pages(projectKey, jql, groupBy),
    queryFn: ({ pageParam }) => fetchPage(projectKey, { jql, start: pageParam, limit: PAGE, group_by: groupBy || null }),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.start + last.rows.length < last.total && last.rows.length ? last.start + last.rows.length : undefined),
    placeholderData: keepPreviousData,
    retry: false,
    enabled,
  });
}

export function useListGroups(projectKey, jql, groupBy, enabled) {
  return useQuery({
    queryKey: lk.groups(projectKey, jql, groupBy),
    queryFn: () => unwrap(api.POST("/api/v1/projects/{key}/list/groups", { params: { path: { key: projectKey } }, body: { jql, group_by: groupBy } })),
    enabled: enabled && !!groupBy,
    placeholderData: keepPreviousData,
    retry: false,
  });
}

/** Children of every expanded row, keyed by parent id. */
export function useChildren(projectKey, parentIds) {
  const results = useQueries({
    queries: parentIds.map((id) => ({
      queryKey: lk.children(projectKey, id),
      queryFn: () => fetchPage(projectKey, { parent_id: id, start: 0, limit: 500 }),
      staleTime: 30_000,
    })),
  });
  const map = new Map();
  parentIds.forEach((id, i) => map.set(id, results[i]));
  return map;
}

export function fetchRows(projectKey, ids, groupBy) {
  return unwrap(api.POST("/api/v1/projects/{key}/list/rows", {
    params: { path: { key: projectKey } }, body: { ids, group_by: groupBy || null },
  }));
}

/* ------------------------------------------------------------------ cache patching */

function mapRows(data, fn) {
  if (!data) return data;
  if (Array.isArray(data.pages)) {
    let changed = false;
    const pages = data.pages.map((p) => {
      const rows = fn(p.rows);
      if (rows !== p.rows) changed = true;
      return rows === p.rows ? p : { ...p, rows };
    });
    return changed ? { ...data, pages } : data;
  }
  if (Array.isArray(data.rows)) {
    const rows = fn(data.rows);
    return rows === data.rows ? data : { ...data, rows };
  }
  return data;
}

function rowQueries(qc, projectKey) {
  return qc.getQueriesData({ queryKey: lk.all(projectKey) })
    .filter(([key]) => key[2] === "pages" || key[2] === "children");
}

/** Apply `fn(row) → row` to every cached copy of the issues in `ids`. */
export function patchRows(qc, projectKey, ids, fn) {
  const set = new Set(ids);
  for (const [key, data] of rowQueries(qc, projectKey)) {
    const next = mapRows(data, (rows) => {
      let changed = false;
      const out = rows.map((r) => {
        if (!set.has(r.id)) return r;
        const n = fn(r);
        if (n !== r) changed = true;
        return n;
      });
      return changed ? out : rows;
    });
    if (next !== data) qc.setQueryData(key, next);
  }
}

/** Replace cached rows with fresh ones from the server; ids missing from `fresh` (deleted,
 *  moved, archived out of the top-level list) are removed. */
export function replaceRows(qc, projectKey, ids, fresh, users) {
  const byId = new Map(fresh.map((r) => [r.id, r]));
  const asked = new Set(ids);
  for (const [key, data] of rowQueries(qc, projectKey)) {
    const children = key[2] === "children";
    let next = mapRows(data, (rows) => {
      let changed = false;
      const out = [];
      for (const r of rows) {
        if (!asked.has(r.id)) { out.push(r); continue; }
        const f = byId.get(r.id);
        changed = true;
        if (!f || (f.is_archived && !children)) continue;
        // keep the group the row was loaded under unless the server says otherwise
        out.push(key[2] === "pages" ? f : { ...f, group: r.group });
      }
      return changed ? out : rows;
    });
    if (next && users && Object.keys(users).length) {
      if (Array.isArray(next.pages) && next.pages.length) {
        const [first, ...rest] = next.pages;
        next = { ...next, pages: [{ ...first, users: { ...first.users, ...users } }, ...rest] };
      } else if (next.rows) {
        next = { ...next, users: { ...next.users, ...users } };
      }
    }
    if (next !== data) qc.setQueryData(key, next);
  }
}

/** Remove rows (by key) from every cached list. */
export function dropRows(qc, projectKey, keys) {
  const set = new Set(keys);
  for (const [key, data] of rowQueries(qc, projectKey)) {
    const next = mapRows(data, (rows) => {
      const out = rows.filter((r) => !set.has(r.key));
      return out.length === rows.length ? rows : out;
    });
    if (next !== data) qc.setQueryData(key, next);
  }
}

/** Find the cached rows (any list) whose key is in `keys`. */
export function findRows(qc, projectKey, pred) {
  const out = new Map();
  for (const [, data] of rowQueries(qc, projectKey)) {
    const lists = Array.isArray(data?.pages) ? data.pages.map((p) => p.rows) : data?.rows ? [data.rows] : [];
    for (const rows of lists) for (const r of rows) if (pred(r)) out.set(r.id, r);
  }
  return Array.from(out.values());
}

/** Append freshly created rows to the end of the loaded top-level list. */
export function appendRows(qc, projectKey, pagesKey, rows) {
  qc.setQueryData(pagesKey, (data) => {
    if (!data?.pages?.length) return data;
    const pages = [...data.pages];
    const last = pages[pages.length - 1];
    const known = new Set(pages.flatMap((p) => p.rows.map((r) => r.id)));
    const add = rows.filter((r) => !known.has(r.id));
    if (!add.length) return data;
    pages[pages.length - 1] = { ...last, rows: [...last.rows, ...add] };
    return { ...data, pages: pages.map((p) => ({ ...p, total: p.total + add.length })) };
  });
}

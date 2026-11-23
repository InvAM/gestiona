"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api, errorMessage, rawFetch, unwrap } from "./client";

export const qk = {
  me: ["me"],
  authConfig: ["auth-config"],
  appMeta: (project) => (project ? ["meta", project] : ["meta"]),
  projects: (params) => ["projects", params ?? {}],
  project: (key) => ["project", key],
  meta: (key) => ["project-meta", key],
  fieldRules: (key) => ["field-rules", key],
  members: (key) => ["members", key],
  issue: (key) => ["issue", key],
  comments: (key) => ["comments", key],
  history: (key) => ["history", key],
  worklogs: (key) => ["worklogs", key],
  transitions: (key) => ["transitions", key],
  board: (id, f) => ["board", id, f ?? {}],
  backlog: (id, f) => ["backlog", id, f ?? {}],
  search: (jql, start, limit) => ["search", jql, start, limit],
  filters: (p) => ["filters", p ?? {}],
  notifications: ["notifications"],
  unread: ["notifications-count"],
  recent: (kind) => ["recent", kind ?? "all"],
  users: (q, project, assignable) =>
    ["users", q, project ?? "", !!assignable],
};

/* ------------------------------------------------------------------ session */

export function useMe() {
  return useQuery({
    queryKey: qk.me,
    queryFn: () => unwrap(api.GET("/api/v1/me")),
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useAuthConfig() {
  return useQuery({
    queryKey: qk.authConfig,
    queryFn: () => unwrap(api.GET("/api/v1/auth/config")),
    staleTime: Infinity,
  });
}

/* ------------------------------------------------------------------ app metadata */

/**
 * Server-owned vocabularies (automation triggers/actions/fields, gadget kinds, group-by
 * fields, form fields, audit categories…). The backend is the single source of truth;
 * enums change only on deploy, so the global result is cached for the whole session.
 * With `project` the automation templates are built from that project's real types and
 * statuses, which admins can edit, so that variant goes stale sooner.
 */
export function useMeta(project) {
  return useQuery({
    queryKey: qk.appMeta(project),
    queryFn: () => unwrap(api.GET("/api/v1/meta", { params: { query: project ? { project } : {} } })),
    staleTime: project ? 60_000 : 60 * 60_000,
    gcTime: project ? undefined : Infinity,
  });
}

/** Label of `value` in a /meta choice list (falls back to the raw value while loading). */
export function choiceLabel(choices, value) {
  return choices?.find((c) => c.value === value)?.label ?? value;
}

/* ------------------------------------------------------------------ projects */

export function useProjects(params = {}) {
  return useQuery({
    queryKey: qk.projects(params),
    queryFn: () => unwrap(api.GET("/api/v1/projects", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });
}

export function useProjectMeta(key) {
  return useQuery({
    queryKey: qk.meta(key ?? ""),
    queryFn: () =>
      unwrap(api.GET("/api/v1/projects/{key}/meta", { params: { path: { key: key } } })),
    enabled: !!key,
    staleTime: 60_000,
  });
}

/**
 * Screens and field configuration of a project, resolved per issue type and transition
 * (GET /projects/{key}/field-rules). On an older backend without the endpoint the query
 * resolves to null and the forms fall back to every field.
 */
export function fieldRulesQuery(key) {
  return {
    queryKey: qk.fieldRules(key ?? ""),
    queryFn: async () => {
      try {
        return await unwrap(api.GET("/api/v1/projects/{key}/field-rules", { params: { path: { key } } }));
      } catch (e) {
        if (e instanceof ApiError && e.status === 404 && e.code !== "not_found") return null;
        throw e;
      }
    },
    enabled: !!key,
    staleTime: 60_000,
  };
}

export function useFieldRules(key) {
  return useQuery(fieldRulesQuery(key));
}

export function useMembers(key) {
  return useQuery({
    queryKey: qk.members(key),
    queryFn: () =>
      unwrap(api.GET("/api/v1/projects/{key}/members", { params: { path: { key } } })),
  });
}

export function useUsers(q, project, assignable = false) {
  return useQuery({
    queryKey: qk.users(q, project, assignable),
    queryFn: () =>
      unwrap(api.GET("/api/v1/users", { params: { query: { q, project, assignable } } })),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useStarProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, starred }) =>
      starred
        ? unwrap(api.POST("/api/v1/projects/{key}/star", { params: { path: { key } } }))
        : unwrap(api.DELETE("/api/v1/projects/{key}/star", { params: { path: { key } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

/* ------------------------------------------------------------------ issues */

export function useIssue(key) {
  return useQuery({
    queryKey: qk.issue(key ?? ""),
    queryFn: () => unwrap(api.GET("/api/v1/issues/{key}", { params: { path: { key: key } } })),
    enabled: !!key,
  });
}

export function invalidateIssueViews(qc, key) {
  if (key) {
    qc.invalidateQueries({ queryKey: qk.issue(key) });
    qc.invalidateQueries({ queryKey: qk.history(key) });
    qc.invalidateQueries({ queryKey: qk.transitions(key) });
  }
  qc.invalidateQueries({ queryKey: ["board"] });
  qc.invalidateQueries({ queryKey: ["backlog"] });
  qc.invalidateQueries({ queryKey: ["search"] });
  qc.invalidateQueries({ queryKey: ["your-work"] });
}

export function useUpdateIssue(key) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch) =>
      unwrap(api.PATCH("/api/v1/issues/{key}", { params: { path: { key } }, body: patch })),
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: qk.issue(key) });
      const prev = qc.getQueryData(qk.issue(key));
      if (prev && patch.summary !== undefined) {
        qc.setQueryData(qk.issue(key), { ...prev, summary: patch.summary ?? prev.summary });
      }
      return { prev };
    },
    onError: (e, _p, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.issue(key), ctx.prev);
      toast.error(errorMessage(e));
    },
    onSuccess: (data) => {
      qc.setQueryData(qk.issue(key), data);
      invalidateIssueViews(qc, key);
    },
  });
}

export function useTransitions(key, enabled = true) {
  return useQuery({
    queryKey: qk.transitions(key),
    queryFn: () =>
      unwrap(api.GET("/api/v1/issues/{key}/transitions", { params: { path: { key } } })),
    enabled,
  });
}

export function useTransition(key) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) =>
      unwrap(api.POST("/api/v1/issues/{key}/transitions", { params: { path: { key } }, body })),
    onSuccess: (data) => {
      qc.setQueryData(qk.issue(key), data);
      invalidateIssueViews(qc, key);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
}

export function useCreateIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => unwrap(api.POST("/api/v1/issues", { body })),
    onSuccess: (issue) => {
      qc.setQueryData(qk.issue(issue.key), issue);
      invalidateIssueViews(qc, issue.parent?.key);
    },
  });
}

export function useDeleteIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key) =>
      unwrap(api.DELETE("/api/v1/issues/{key}", { params: { path: { key } } })),
    onSuccess: () => invalidateIssueViews(qc),
    onError: (e) => toast.error(errorMessage(e)),
  });
}

export function useComments(key) {
  return useQuery({
    queryKey: qk.comments(key),
    queryFn: () =>
      unwrap(api.GET("/api/v1/issues/{key}/comments", { params: { path: { key } } })),
  });
}

export function useHistory(key, enabled = true) {
  return useQuery({
    queryKey: qk.history(key),
    queryFn: () =>
      unwrap(api.GET("/api/v1/issues/{key}/history", { params: { path: { key } } })),
    enabled,
  });
}

export function useWorklogs(key, enabled = true) {
  return useQuery({
    queryKey: qk.worklogs(key),
    queryFn: () =>
      unwrap(api.GET("/api/v1/issues/{key}/worklogs", { params: { path: { key } } })),
    enabled,
  });
}

export async function uploadAttachments(key, files) {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  return rawFetch(`/api/v1/issues/${key}/attachments`, {
    method: "POST",
    body: form,
  });
}

/* ------------------------------------------------------------------ boards */

export function useBoardData(id, f) {
  return useQuery({
    queryKey: qk.board(id, f),
    queryFn: () =>
      unwrap(api.GET("/api/v1/boards/{board_id}/data", {
        params: { path: { board_id: id }, query: f },
      })),
    placeholderData: keepPreviousData,
  });
}

export function useBacklog(id, f) {
  return useQuery({
    queryKey: qk.backlog(id, f),
    queryFn: () =>
      unwrap(api.GET("/api/v1/boards/{board_id}/backlog", {
        params: { path: { board_id: id }, query: f },
      })),
    placeholderData: keepPreviousData,
  });
}

/* ------------------------------------------------------------------ notifications */

export function useUnreadCount() {
  return useQuery({
    queryKey: qk.unread,
    queryFn: () => unwrap(api.GET("/api/v1/notifications/count")),
    refetchInterval: 120_000,
  });
}

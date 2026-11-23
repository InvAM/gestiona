"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { invalidateIssueViews, qk } from "./api/hooks";

const Ctx = createContext(null);

function wsUrl() {
  const explicit = process.env.NEXT_PUBLIC_WS_URL;
  if (explicit) return explicit;
  const { protocol, hostname, port } = window.location;
  const scheme = protocol === "https:" ? "wss" : "ws";
  // dev: Next runs on 3000, Django ASGI on 8000. Prod: reverse proxy serves /ws on same host.
  const host = port === "3000" ? `${hostname}:8000` : window.location.host;
  return `${scheme}://${host}/ws/`;
}

/**
 * Single WebSocket per tab. Reconnects with backoff, re-subscribes projects,
 * and turns server events into React Query invalidations.
 */
export function RealtimeProvider({ userId, children }) {
  const qc = useQueryClient();
  const ws = useRef(null);
  const projects = useRef(new Map()); // projectId -> refcount
  const listeners = useRef(new Set());
  const [api] = useState(() => {
    const send = (msg) => {
      if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(msg));
    };
    return {
      subscribeProject(projectId) {
        const n = projects.current.get(projectId) ?? 0;
        projects.current.set(projectId, n + 1);
        if (n === 0) send({ action: "subscribe_project", project_id: projectId });
        return () => {
          const c = (projects.current.get(projectId) ?? 1) - 1;
          if (c <= 0) {
            projects.current.delete(projectId);
            send({ action: "unsubscribe_project", project_id: projectId });
          } else projects.current.set(projectId, c);
        };
      },
      on(fn) {
        listeners.current.add(fn);
        return () => listeners.current.delete(fn);
      },
    };
  });

  useEffect(() => {
    if (!userId) return;
    let closed = false;
    let retry = 0;
    let timer;
    let ping;

    const handle = (event, payload) => {
      const key = typeof payload.key === "string" ? payload.key : undefined;
      switch (event) {
        case "issue.created":
        case "issue.updated":
        case "issue.deleted":
        case "issue.ranked":
          invalidateIssueViews(qc, key);
          break;
        case "comment.created":
        case "comment.updated":
        case "comment.deleted":
          qc.invalidateQueries({ queryKey: ["comments"] });
          qc.invalidateQueries({ queryKey: ["history"] });
          break;
        case "sprint.changed":
          qc.invalidateQueries({ queryKey: ["board"] });
          qc.invalidateQueries({ queryKey: ["backlog"] });
          break;
        case "project.updated":
          qc.invalidateQueries({ queryKey: ["project-meta"] });
          qc.invalidateQueries({ queryKey: ["field-rules"] });
          qc.invalidateQueries({ queryKey: ["projects"] });
          break;
        case "notification.created":
          qc.invalidateQueries({ queryKey: qk.unread });
          qc.invalidateQueries({ queryKey: qk.notifications });
          break;
      }
      listeners.current.forEach((fn) => fn(event, payload));
    };

    const connect = () => {
      const sock = new WebSocket(wsUrl());
      ws.current = sock;
      sock.onopen = () => {
        retry = 0;
        for (const pid of projects.current.keys())
          sock.send(JSON.stringify({ action: "subscribe_project", project_id: pid }));
        ping = setInterval(() => sock.readyState === 1 && sock.send('{"action":"ping"}'), 25_000);
      };
      sock.onmessage = (m) => {
        try {
          const { event, payload } = JSON.parse(m.data);
          // ignore echoes of our own actions: the mutation already updated the cache
          if (payload?.actor_id && payload.actor_id === userId && event !== "notification.created")
            return;
          handle(event, payload ?? {});
        } catch {
          /* ignore malformed */
        }
      };
      sock.onclose = (e) => {
        clearInterval(ping);
        if (closed || e.code === 4401) return;
        retry = Math.min(retry + 1, 6);
        timer = setTimeout(connect, 500 * 2 ** retry);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      clearInterval(ping);
      ws.current?.close();
    };
  }, [userId, qc]);

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function useRealtime() {
  const c = useContext(Ctx);
  if (!c) throw new Error("RealtimeProvider missing");
  return c;
}

/** Subscribe the socket to a project's events while the component is mounted. */
export function useProjectChannel(projectId) {
  const rt = useRealtime();
  useEffect(() => {
    if (!projectId) return;
    return rt.subscribeProject(projectId);
  }, [rt, projectId]);
}

"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

const Ctx = createContext(null);

export function AppProvider({ me, children }) {
  const [createState, setCreate] = useState({
    open: false, defaults: {},
  });
  const [lastProjectKey, setLast] = useState(() => {
    if (typeof window === "undefined") return undefined;
    try { return localStorage.getItem("gestiona-last-project") ?? undefined; } catch { return undefined; }
  });
  const setLastProjectKey = useCallback((k) => {
    setLast(k);
    try { localStorage.setItem("gestiona-last-project", k); } catch { /* ignore */ }
  }, []);
  const openCreate = useCallback((d = {}) => setCreate({ open: true, defaults: d }), []);
  const closeCreate = useCallback(() => setCreate((s) => ({ ...s, open: false })), []);

  // Global shortcut: "c" opens create (like Jira), "/" focuses search.
  useEffect(() => {
    const onKey = (e) => {
      const t = e.target;
      if (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (document.querySelector("[role=dialog]")) return;
      if (e.key === "c") {
        e.preventDefault();
        openCreate({ projectKey: lastProjectKey });
      } else if (e.key === "/") {
        e.preventDefault();
        document.getElementById("global-search")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openCreate, lastProjectKey]);

  return (
    <Ctx.Provider value={{ me, openCreate, createState, closeCreate, lastProjectKey, setLastProjectKey }}>
      {children}
    </Ctx.Provider>
  );
}

export function useApp() {
  const c = useContext(Ctx);
  if (!c) throw new Error("AppProvider missing");
  return c;
}

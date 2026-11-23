"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { use, useMemo, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { ProjectFlowReport } from "@/components/analytics/project-reports";
import { IssueTypeIcon } from "@/components/icons";
import { Button, PageSpinner } from "@/components/ui/button";
import { EmptyState, Lozenge, Tabs } from "@/components/ui/primitives";
import { Picker } from "@/components/ui/picker";
import { api, unwrap } from "@/lib/api/client";
import { choiceLabel, useMeta, useProjectMeta } from "@/lib/api/hooks";
import { fmtDate, fmtPoints } from "@/lib/utils";
import { useNow } from "@/lib/use-now";

const C = { brand: "#1D5FD6", success: "#1F845A", grey: "#8590A2", warn: "#E56910" };
const CFD_COLORS = ["#8590A2", "#1D5FD6", "#6E5DC6", "#1F845A", "#E56910", "#0E7C86", "#AE2E74"];
const axis = { fontSize: 12, fill: "var(--text-subtle)" };

function Burndown({ boardId }) {
  const meta = useMeta();
  const sprints = useQuery({
    queryKey: ["sprints", boardId, "report"],
    queryFn: () => unwrap(api.GET("/api/v1/boards/{board_id}/sprints", { params: { path: { board_id: boardId }, query: { state: "active,closed" } } })),
  });
  const [sid, setSid] = useState(null);
  const sprintId = sid ?? sprints.data?.find((s) => s.state === "active")?.id ?? sprints.data?.[0]?.id;
  const report = useQuery({
    queryKey: ["sprint-report", sprintId],
    queryFn: () => unwrap(api.GET("/api/v1/sprints/{sid}/report", { params: { path: { sid: sprintId } } })),
    enabled: !!sprintId,
  });
  const nowTs = useNow();
  const chart = useMemo(() => {
    const r = report.data;
    if (!r?.sprint.start) return [];
    const start = new Date(r.sprint.start).getTime();
    const end = new Date(r.sprint.completed_at ?? r.sprint.end ?? nowTs).getTime();
    const pts = [{ t: start, remaining: r.initial, guide: r.initial }];
    r.timeline.forEach((p) => pts.push({ t: new Date(p.at).getTime(), remaining: p.remaining, guide: null }));
    const last = pts[pts.length - 1].remaining;
    const now = Math.min(nowTs, end);
    if (now > pts[pts.length - 1].t) pts.push({ t: now, remaining: last, guide: null });
    pts.push({ t: new Date(r.sprint.end ?? end).getTime(), remaining: null, guide: 0 });
    return pts;
  }, [report.data, nowTs]);
  if (sprints.isPending) return <PageSpinner />;
  if (!sprints.data?.length) return <EmptyState title="Aún no hay sprints iniciados" body="El burndown aparece cuando inicias un sprint." />;
  const r = report.data;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <Picker value={sprintId} onSelect={setSid} width={280}
                options={sprints.data.map((s) => ({ value: s.id, label: s.name, description: [choiceLabel(meta.data?.sprint_states, s.state), s.completed_at && fmtDate(s.completed_at)].filter(Boolean).join(" ") }))}
                trigger={<Button>{sprints.data.find((s) => s.id === sprintId)?.name}<ChevronDown size={14} /></Button>} />
        {r && <span className="text-sm text-fg-subtle">{fmtDate(r.sprint.start)} – {fmtDate(r.sprint.end)} · {choiceLabel(meta.data?.board_estimations, r.estimation)}</span>}
      </div>
      {r?.goal && <p className="mt-2 text-sm"><b>Objetivo:</b> {r.goal}</p>}
      <div className="mt-4 h-80">
        <ResponsiveContainer>
          <LineChart data={chart}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} scale="time" tick={axis}
                   tickFormatter={(t) => fmtDate(new Date(t), "d MMM")} />
            <YAxis tick={axis} allowDecimals={false} />
            <Tooltip labelFormatter={(t) => fmtDate(new Date(Number(t)), "d MMM HH:mm")} contentStyle={{ background: "var(--bg-overlay)", border: "1px solid var(--border)" }} />
            <Legend />
            <Line name="Guía" dataKey="guide" stroke={C.grey} strokeDasharray="5 5" connectNulls dot={false} />
            <Line name="Trabajo restante" dataKey="remaining" stroke={C.warn} strokeWidth={2} type="stepAfter" connectNulls dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {r && (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <IssueList title={`Completadas (${r.completed.length})`} cards={r.completed} />
          <IssueList title={`No completadas (${r.incomplete.length})`} cards={r.incomplete} />
        </div>
      )}
    </div>
  );
}

function IssueList({ title, cards }) {
  return (
    <div>
      <h3 className="mb-2 font-semibold">{title}</h3>
      <div className="overflow-hidden rounded-[3px] border border-line">
        {cards.length ? cards.map((c) => (
          <Link key={c.id} href={`/browse/${c.key}`} className="flex items-center gap-2 border-b border-line px-3 py-1.5 text-sm last:border-0 hover:bg-bg-hover">
            <IssueTypeIcon type={c.type} /><span className="text-link">{c.key}</span>
            <span className="min-w-0 flex-1 truncate">{c.summary}</span>
            <Lozenge category={c.status.category}>{c.status.name}</Lozenge>
            <span className="w-8 text-right text-fg-subtle">{fmtPoints(c.story_points) ?? "–"}</span>
          </Link>
        )) : <div className="px-3 py-3 text-sm text-fg-subtlest">Ninguna</div>}
      </div>
    </div>
  );
}

function Velocity({ boardId }) {
  const v = useQuery({ queryKey: ["velocity", boardId], queryFn: () => unwrap(api.GET("/api/v1/boards/{board_id}/velocity", { params: { path: { board_id: boardId } } })) });
  if (v.isPending) return <PageSpinner />;
  if (!v.data?.sprints.length) return <EmptyState title="Sin sprints completados" body="La velocidad se calcula con los sprints cerrados." />;
  const avg = v.data.sprints.reduce((s, x) => s + x.completed, 0) / v.data.sprints.length;
  return (
    <div>
      <p className="text-sm text-fg-subtle">Velocidad promedio: <b className="text-fg">{fmtPoints(avg)}</b> por sprint (últimos {v.data.sprints.length})</p>
      <div className="mt-4 h-80">
        <ResponsiveContainer>
          <BarChart data={v.data.sprints}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" tick={axis} />
            <YAxis tick={axis} allowDecimals={false} />
            <Tooltip contentStyle={{ background: "var(--bg-overlay)", border: "1px solid var(--border)" }} />
            <Legend />
            <Bar name="Compromiso" dataKey="committed" fill={C.grey} radius={[3, 3, 0, 0]} />
            <Bar name="Completado" dataKey="completed" fill={C.success} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function CumulativeFlow({ boardId }) {
  const [days, setDays] = useState(30);
  const d = useQuery({ queryKey: ["cfd", boardId, days], queryFn: () => unwrap(api.GET("/api/v1/boards/{board_id}/cumulative-flow", { params: { path: { board_id: boardId }, query: { days } } })) });
  const rows = useMemo(() => d.data?.series.map((s) => ({ date: s.date, ...s.counts })) ?? [], [d.data]);
  if (d.isPending) return <PageSpinner />;
  const cols = [...(d.data?.columns ?? [])].reverse();
  return (
    <div>
      <div className="flex gap-1">{[14, 30, 90].map((n) => <Button key={n} size="sm" variant={days === n ? "selected" : "subtle"} onClick={() => setDays(n)}>{n} días</Button>)}</div>
      <div className="mt-4 h-96">
        <ResponsiveContainer>
          <AreaChart data={rows}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={axis} tickFormatter={(t) => fmtDate(t, "d MMM")} />
            <YAxis tick={axis} allowDecimals={false} />
            <Tooltip labelFormatter={(t) => fmtDate(String(t))} contentStyle={{ background: "var(--bg-overlay)", border: "1px solid var(--border)" }} />
            <Legend />
            {cols.map((c, i) => (
              <Area key={c.id} name={c.name} dataKey={String(c.id)} stackId="1" type="monotone"
                    stroke={CFD_COLORS[(cols.length - 1 - i) % CFD_COLORS.length]} fill={CFD_COLORS[(cols.length - 1 - i) % CFD_COLORS.length]} fillOpacity={0.6} />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

const FLOW_TABS = [
  { value: "control", label: "Gráfico de control" },
  { value: "tis", label: "Tiempo en estado" },
  { value: "throughput", label: "Throughput" },
];

export default function ReportsPage({ params }) {
  const { key } = use(params);
  const projectKey = key.toUpperCase();
  const meta = useProjectMeta(projectKey);
  const board = meta.data?.boards[0];
  const isScrum = board?.kind === "scrum";
  const boardTabs = !board ? [] : [
    ...(isScrum ? [{ value: "burndown", label: "Burndown / Informe del sprint" }, { value: "velocity", label: "Velocidad" }] : []),
    { value: "cfd", label: "Flujo acumulado" },
  ];
  const tabs = [...boardTabs, ...FLOW_TABS];
  const [tab, setTab] = useState(null);
  const current = tabs.some((t) => t.value === tab) ? tab : tabs[0].value;
  return (
    <div className="flex-1 overflow-y-auto px-6 py-5">
      <h1 className="text-2xl font-medium">Informes</h1>
      {meta.data && !board && (
        <p className="mt-1 text-sm text-fg-subtle">Este proyecto no tiene tableros: los informes de sprint, velocidad y flujo acumulado aparecen al crear uno.</p>
      )}
      <Tabs className="mt-4" value={current} onChange={setTab} tabs={tabs} />
      <div className="mt-6 max-w-[1100px]">
        {current === "burndown" && <Burndown boardId={board.id} />}
        {current === "velocity" && <Velocity boardId={board.id} />}
        {current === "cfd" && <CumulativeFlow boardId={board.id} />}
        {FLOW_TABS.some((t) => t.value === current) && <ProjectFlowReport key={current} projectKey={projectKey} kind={current} />}
      </div>
    </div>
  );
}

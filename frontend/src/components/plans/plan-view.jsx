"use client";

import { ArrowLeft, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { useCatalogActions } from "@/components/settings/catalog";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, EmptyState, Tabs } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/client";
import { choiceLabel, useMeta } from "@/lib/api/hooks";
import { usePlan } from "./api";
import { PlanCapacity } from "./capacity";
import { PlanForm } from "./plan-form";
import { PlanReleases } from "./releases";
import { PlanTimeline } from "./timeline";

export function PlanView({ id }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const meta = useMeta();
  const plan = usePlan(id);
  const actions = useCatalogActions({ path: "/api/v1/plans", queryKey: "plans",
                                      softBody: "Las incidencias, equipos y versiones no se tocan.",
                                      onDeleted: () => router.push("/plans") });
  const tabs = [
    { value: "timeline", label: "Cronograma" },
    { value: "capacity", label: "Capacidad" },
    { value: "releases", label: "Versiones" },
    ...(plan.data?.can_edit ? [{ value: "settings", label: "Configuración" }] : []),
  ];
  const tab = tabs.some((t) => t.value === params.get("tab")) ? params.get("tab") : "timeline";
  const setTab = (v) => {
    const p = new URLSearchParams(params.toString());
    if (v === "timeline") p.delete("tab"); else p.set("tab", v);
    p.delete("selectedIssue");
    router.replace(`${pathname}${p.size ? `?${p}` : ""}`, { scroll: false });
  };

  if (plan.isPending) return <PageSpinner />;
  if (plan.error) {
    return <EmptyState title="No se puede abrir el plan" body={plan.error.status === 404 ? "No existe o no tienes acceso." : errorMessage(plan.error)}
                       action={<Button asChild><Link href="/plans">Volver a los planes</Link></Button>} />;
  }
  const p = plan.data;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-6 pt-4">
        <Link href="/plans" className="inline-flex items-center gap-1 text-sm text-fg-subtle hover:underline"><ArrowLeft size={14} />Planes</Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-medium">{p.name}</h1>
          <span className="inline-flex items-center gap-1 text-xs text-fg-subtle">
            <Users size={12} />{choiceLabel(meta.data?.plans.access, p.access)}
          </span>
          <span className="ml-auto inline-flex items-center gap-2 text-sm text-fg-subtle"><Avatar user={p.owner} size="xs" />{p.owner.name}</span>
        </div>
        {p.description && <p className="mt-1 max-w-3xl whitespace-pre-wrap text-sm text-fg-subtle">{p.description}</p>}
        <Tabs className="mt-3" value={tab} onChange={setTab} tabs={tabs} />
      </div>
      <div className="flex min-h-0 flex-1 flex-col pt-3">
        {tab === "timeline" && <PlanTimeline plan={p} />}
        {tab === "capacity" && <PlanCapacity plan={p} />}
        {tab === "releases" && <PlanReleases plan={p} />}
        {tab === "settings" && (
          <div className="min-h-0 flex-1 overflow-y-auto px-6">
            <div className="max-w-3xl">
              <PlanForm key={p.updated_at} plan={p} onSaved={() => toast.success("Plan guardado")} />
              <div className="mb-8 mt-4 flex items-center gap-3 rounded-[3px] border border-line p-4">
                <div className="flex-1"><div className="font-medium">Eliminar plan</div><p className="text-sm text-fg-subtle">Va a «Eliminados» y se puede restaurar desde la lista de planes.</p></div>
                <Button variant="danger" onClick={() => actions.askDelete(p)}><Trash2 size={16} />Eliminar</Button>
              </div>
            </div>
          </div>
        )}
      </div>
      {actions.dialog}
    </div>
  );
}

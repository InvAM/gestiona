"use client";

import { use } from "react";
import { ProjectSidebar } from "@/components/shell/project-sidebar";
import { PageSpinner } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/primitives";
import { useProjectMeta } from "@/lib/api/hooks";
import { useProjectChannel } from "@/lib/realtime";

export default function ProjectLayout({ children, params }) {
  const { key } = use(params);
  const projectKey = key.toUpperCase();
  const meta = useProjectMeta(projectKey);
  useProjectChannel(meta.data?.project.id);
  if (meta.isPending) return <PageSpinner />;
  if (!meta.data) {
    return <EmptyState title="Proyecto no encontrado" body="No existe o no tienes acceso a este proyecto." />;
  }
  return (
    <>
      <ProjectSidebar projectKey={projectKey} />
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">{children}</main>
    </>
  );
}

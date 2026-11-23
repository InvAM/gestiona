"use client";

import { useRouter } from "next/navigation";
import { use, useEffect } from "react";
import { PageSpinner } from "@/components/ui/button";
import { useProjectMeta } from "@/lib/api/hooks";

export default function ProjectHome({ params }) {
  const { key } = use(params);
  const router = useRouter();
  const meta = useProjectMeta(key.toUpperCase());
  useEffect(() => {
    const b = meta.data?.boards[0];
    if (b) router.replace(`/projects/${key.toUpperCase()}/boards/${b.id}${b.kind === "scrum" ? "/backlog" : ""}`);
    else if (meta.data) router.replace(`/projects/${key.toUpperCase()}/issues`);
  }, [meta.data, key, router]);
  return <PageSpinner />;
}

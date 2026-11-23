"use client";

import { use } from "react";
import { AdminSettings } from "@/components/settings/admin";

export default function WorkflowEditPage({ params }) {
  const { id } = use(params);
  return <AdminSettings section="workflows" workflowId={Number(id)} />;
}

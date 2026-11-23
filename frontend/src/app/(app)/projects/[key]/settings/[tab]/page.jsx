"use client";

import { notFound } from "next/navigation";
import { use } from "react";
import { ProjectSettings } from "@/components/settings/project-settings";

const VALID = ["details", "members", "issue-types", "fields", "board", "workflow", "automation", "forms", "archived"];

export default function SettingsTabPage({ params }) {
  const { key, tab } = use(params);
  if (!VALID.includes(tab)) notFound();
  return <ProjectSettings projectKey={key.toUpperCase()} tab={tab} />;
}

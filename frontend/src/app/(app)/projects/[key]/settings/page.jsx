"use client";

import { use } from "react";
import { ProjectSettings } from "@/components/settings/project-settings";

export default function SettingsPage({ params }) {
  const { key } = use(params);
  return <ProjectSettings projectKey={key.toUpperCase()} tab="details" />;
}

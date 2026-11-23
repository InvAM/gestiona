"use client";

import { notFound } from "next/navigation";
import { use } from "react";
import { DashboardView } from "@/components/dashboards/dashboard-view";

export default function DashboardPage({ params }) {
  const { id } = use(params);
  const n = Number(id);
  if (!Number.isInteger(n) || n <= 0) notFound();
  return <main className="flex min-w-0 flex-1 flex-col"><DashboardView id={n} /></main>;
}

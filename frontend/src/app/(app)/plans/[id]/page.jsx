"use client";

import { notFound } from "next/navigation";
import { Suspense, use } from "react";
import { PlanView } from "@/components/plans/plan-view";
import { PageSpinner } from "@/components/ui/button";

export default function PlanPage({ params }) {
  const { id } = use(params);
  const n = Number(id);
  if (!Number.isInteger(n) || n <= 0) notFound();
  return (
    <main className="flex min-w-0 flex-1 flex-col">
      <Suspense fallback={<PageSpinner />}><PlanView id={n} /></Suspense>
    </main>
  );
}

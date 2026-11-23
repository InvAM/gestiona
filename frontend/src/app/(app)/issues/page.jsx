"use client";

import { Suspense } from "react";
import { IssueSearch } from "@/components/search/issue-search";
import { PageSpinner } from "@/components/ui/button";

export default function IssuesPage() {
  return (
    <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <Suspense fallback={<PageSpinner />}><IssueSearch /></Suspense>
    </main>
  );
}

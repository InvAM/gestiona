"use client";

import { Suspense, use } from "react";
import { IssueSearch } from "@/components/search/issue-search";
import { PageSpinner } from "@/components/ui/button";

export default function ProjectIssuesPage({ params }) {
  const { key } = use(params);
  return <Suspense fallback={<PageSpinner />}><IssueSearch projectKey={key.toUpperCase()} /></Suspense>;
}

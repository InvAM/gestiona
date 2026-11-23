"use client";

import { Suspense, use } from "react";
import { ListView } from "@/components/list/list-view";
import { PageSpinner } from "@/components/ui/button";

export default function ProjectListPage({ params }) {
  const { key } = use(params);
  return <Suspense fallback={<PageSpinner />}><ListView projectKey={key.toUpperCase()} /></Suspense>;
}

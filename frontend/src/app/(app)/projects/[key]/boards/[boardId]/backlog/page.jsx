"use client";

import { Suspense, use } from "react";
import { BacklogView } from "@/components/backlog/backlog-view";
import { PageSpinner } from "@/components/ui/button";

export default function BacklogPage({ params }) {
  const { key, boardId } = use(params);
  return (
    <Suspense fallback={<PageSpinner />}>
      <BacklogView boardId={Number(boardId)} projectKey={key.toUpperCase()} />
    </Suspense>
  );
}

"use client";

import { Suspense, use } from "react";
import { BoardView } from "@/components/board/board-view";
import { PageSpinner } from "@/components/ui/button";

export default function BoardPage({ params }) {
  const { key, boardId } = use(params);
  return (
    <Suspense fallback={<PageSpinner />}>
      <BoardView boardId={Number(boardId)} projectKey={key.toUpperCase()} />
    </Suspense>
  );
}

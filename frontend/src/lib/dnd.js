"use client";

import { combine } from "@atlaskit/pragmatic-drag-and-drop/combine";
import {
  draggable, dropTargetForElements, monitorForElements,
} from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { attachClosestEdge } from "@atlaskit/pragmatic-drag-and-drop-hitbox/closest-edge/attach-closest-edge";
import { extractClosestEdge } from "@atlaskit/pragmatic-drag-and-drop-hitbox/closest-edge/extract-closest-edge";
import { autoScrollForElements } from "@atlaskit/pragmatic-drag-and-drop-auto-scroll/element";
import { useEffect, useState } from "react";

export { combine, monitorForElements, extractClosestEdge, autoScrollForElements };

export function isCard(d) {
  return d.type === "issue";
}

/** Make an element a draggable card that is also a drop target (for ordering). */
export function useCardDnd(
  ref,
  data,
  opts = {},
) {
  const [dragging, setDragging] = useState(false);
  const [edge, setEdge] = useState(null);
  const key = data.issueIds.join(",") + data.sourceList;
  useEffect(() => {
    const el = ref.current;
    if (!el || opts.disabled) return;
    return combine(
      draggable({
        element: el,
        getInitialData: () => data,
        onDragStart: () => setDragging(true),
        onDrop: () => setDragging(false),
      }),
      dropTargetForElements({
        element: el,
        canDrop: ({ source }) => isCard(source.data) && !source.data.issueIds.includes(data.issueId),
        getData: ({ input, element }) =>
          attachClosestEdge({ type: "card-target", issueId: data.issueId, list: data.sourceList }, {
            input, element, allowedEdges: ["top", "bottom"],
          }),
        onDrag: ({ self }) => setEdge(extractClosestEdge(self.data)),
        onDragLeave: () => setEdge(null),
        onDrop: () => setEdge(null),
      }),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, key, opts.disabled]);
  return { dragging, edge };
}

/** A list/column drop zone. */
export function useListDrop(
  ref,
  listId,
  opts = {},
) {
  const [over, setOver] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    return dropTargetForElements({
      element: el,
      canDrop: ({ source }) => isCard(source.data) && (opts.canDrop ? opts.canDrop(source.data) : true),
      getData: () => ({ type: "list-target", list: listId }),
      onDragEnter: () => setOver(true),
      onDragLeave: () => setOver(false),
      onDrop: () => setOver(false),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, listId, opts.canDrop]);
  return over;
}

/** Listen to all card drops in the page; resolves the innermost target. */
export function useCardMonitor(onDrop, onStart,
                               onEnd) {
  useEffect(() => {
    return monitorForElements({
      canMonitor: ({ source }) => isCard(source.data),
      onDragStart: ({ source }) => onStart?.(source.data),
      onDrop: ({ source, location }) => {
        onEnd?.();
        const targets = location.current.dropTargets;
        if (!targets.length) return;
        const data = source.data;
        const card = targets.find((t) => t.data.type === "card-target");
        const list = targets.find((t) => t.data.type === "list-target");
        if (card) {
          onDrop({ data, list: String(card.data.list), targetIssueId: Number(card.data.issueId),
                   edge: extractClosestEdge(card.data) });
        } else if (list) {
          onDrop({ data, list: String(list.data.list) });
        }
      },
    });
  }, [onDrop, onStart, onEnd]);
}

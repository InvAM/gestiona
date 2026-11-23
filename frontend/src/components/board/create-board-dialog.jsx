"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Columns3, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { EmptyState, Field, Input, Modal } from "@/components/ui/primitives";
import { Picker } from "@/components/ui/picker";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, useMeta } from "@/lib/api/hooks";

const sel = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";

// Queries that show boards (navigation, selectors, board/backlog views, plan form…).
export const BOARD_VIEWS = ["project-meta", "board-config", "board", "backlog", "recent", "plan-form-boards"];

export function boardHref(projectKey, b) {
  return `/projects/${projectKey}/boards/${b.id}${b.kind === "scrum" ? "/backlog" : ""}`;
}

/** «Crear tablero» dialog (project administrators). `onCreated(board)` after the POST. */
export function CreateBoardDialog({ projectKey, open, onOpenChange, onCreated }) {
  const appMeta = useMeta();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [kind, setKind] = useState("scrum");
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/projects/{key}/boards", { params: { path: { key: projectKey } }, body: { name: name.trim(), kind } })),
    onSuccess: (b) => {
      toast.success(`Tablero «${b.name}» creado`);
      for (const k of BOARD_VIEWS) qc.invalidateQueries({ queryKey: [k] });
      setName("");
      onOpenChange(false);
      onCreated?.(b);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Crear tablero" width={480}
           footer={<>
             <Button variant="subtle" onClick={() => onOpenChange(false)}>Cancelar</Button>
             <Button variant="primary" disabled={!name.trim()} loading={create.isPending} onClick={() => create.mutate()}>Crear</Button>
           </>}>
      <div className="space-y-4 pb-2">
        <Field label="Nombre" required>
          <Input autoFocus value={name} maxLength={80} onChange={(e) => setName(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) create.mutate(); }} />
        </Field>
        <Field label="Tipo" hint="Las columnas se crean a partir del flujo de trabajo del proyecto.">
          <Picker value={kind} width={420} onSelect={setKind} options={appMeta.data?.board_kinds ?? []}
                  trigger={<button type="button" className={sel}>{choiceLabel(appMeta.data?.board_kinds, kind)}</button>} />
        </Field>
      </div>
    </Modal>
  );
}

/** «Crear tablero» button that opens the dialog and then goes to the new board. */
export function CreateBoardButton({ projectKey, children = "Crear tablero", ...buttonProps }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button {...buttonProps} onClick={() => setOpen(true)}><Plus size={16} />{children}</Button>
      <CreateBoardDialog projectKey={projectKey} open={open} onOpenChange={setOpen}
                         onCreated={(b) => router.push(boardHref(projectKey, b))} />
    </>
  );
}

/**
 * Empty state for a board route that has no board: the board was deleted (404) or the project
 * has none. Offers another active board, «Crear tablero» (project admins) or the issues.
 */
export function BoardMissing({ projectKey, meta, backlog = false, gone = true }) {
  const boards = meta?.boards ?? [];
  const other = boards[0];
  const isAdmin = !!meta?.permissions.includes("administer");
  const title = gone ? "Tablero no encontrado" : "Este proyecto no tiene tableros";
  const body = [
    gone ? "Puede que lo hayan eliminado." : "Las incidencias siguen disponibles en la Lista y en Incidencias.",
    isAdmin && gone ? "Puedes restaurarlo desde Configuración del proyecto › Tableros." : null,
    !other && !isAdmin ? "Pide a un administrador del proyecto que cree uno." : null,
  ].filter(Boolean).join(" ");
  return (
    <EmptyState icon={<Columns3 size={40} />} title={title} body={body}
                action={(
                  <div className="flex flex-wrap justify-center gap-2">
                    {other && (
                      <Button variant="primary" asChild>
                        <Link href={backlog && other.kind === "scrum" ? `/projects/${projectKey}/boards/${other.id}/backlog` : `/projects/${projectKey}/boards/${other.id}`}>Ir a «{other.name}»</Link>
                      </Button>
                    )}
                    {isAdmin && <CreateBoardButton projectKey={projectKey} variant={other ? "default" : "primary"} />}
                    <Button variant="subtle" asChild><Link href={`/projects/${projectKey}/issues`}>Ver incidencias</Link></Button>
                  </div>
                )} />
  );
}

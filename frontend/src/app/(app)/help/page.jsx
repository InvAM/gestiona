import { Kbd } from "@/components/ui/primitives";

const SHORTCUTS = [
  ["c", "Crear incidencia"], ["/", "Ir a la búsqueda"], ["m", "Comentar (en una incidencia)"],
  ["Ctrl + Enter", "Guardar comentario o descripción"], ["Esc", "Cerrar diálogo o cancelar edición"],
  ["Ctrl/⌘ + clic", "Seleccionar varias incidencias en el backlog"], ["Shift + clic", "Seleccionar un rango en el backlog"],
];

const JQL = [
  ["project = DEMO AND statusCategory != Done", "Incidencias abiertas de un proyecto"],
  ["assignee = currentUser() AND resolution = Unresolved", "Mis pendientes"],
  ["sprint in openSprints() AND assignee is EMPTY", "Sin asignar en el sprint activo"],
  ['labels in (backend, infra) AND priority >= Alta', "Por etiquetas y prioridad"],
  ['text ~ "factura" AND created >= -2w', "Texto libre en las últimas 2 semanas"],
  ["parent = DEMO-1", "Hijas de una épica"],
  ['due < now() AND resolution = Unresolved ORDER BY due ASC', "Vencidas"],
  ['fixVersion = "v1.0" ORDER BY rank', "Alcance de una versión"],
];

export default function HelpPage() {
  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[860px] space-y-10 px-8 py-8">
        <h1 className="text-2xl font-medium">Ayuda</h1>
        <section>
          <h2 className="text-lg font-medium">Atajos de teclado</h2>
          <table className="mt-3 w-full text-sm">
            <tbody>{SHORTCUTS.map(([k, d]) => <tr key={k} className="border-b border-line"><td className="w-48 py-2"><Kbd>{k}</Kbd></td><td className="py-2">{d}</td></tr>)}</tbody>
          </table>
        </section>
        <section>
          <h2 className="text-lg font-medium">Búsqueda avanzada (JQL)</h2>
          <p className="mt-1 text-sm text-fg-subtle">
            Campos: project, key, summary, description, text, comment, type, status, statusCategory, priority, resolution, assignee,
            reporter, labels, component, fixVersion, affectedVersion, sprint, parent, created, updated, resolved, due, startDate,
            &quot;story points&quot;, watcher, flagged, cf[ID]. Operadores: = != ~ !~ &gt; &gt;= &lt; &lt;= IN, NOT IN, IS EMPTY, IS NOT EMPTY.
            Funciones: currentUser(), openSprints(), futureSprints(), closedSprints(), now(), startOfDay/Week/Month/Year(), endOf…(),
            unreleasedVersions(). Fechas relativas: -1d, -2w, 4h.
          </p>
          <table className="mt-3 w-full text-sm">
            <tbody>{JQL.map(([q, d]) => <tr key={q} className="border-b border-line"><td className="py-2 pr-4"><code className="rounded bg-bg-sunken px-1.5 py-0.5 text-xs">{q}</code></td><td className="py-2 text-fg-subtle">{d}</td></tr>)}</tbody>
          </table>
        </section>
        <section>
          <h2 className="text-lg font-medium">Conceptos</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-fg-subtle">
            <li><b className="text-fg">Épica</b>: agrupa historias, tareas y errores. <b className="text-fg">Subtarea</b>: divide una incidencia estándar.</li>
            <li><b className="text-fg">Backlog</b>: lista priorizada; arrastra para ordenar o mover a sprints.</li>
            <li><b className="text-fg">Sprint</b>: periodo de trabajo. Solo uno activo por tablero; al completarlo, lo pendiente pasa al backlog o al siguiente sprint.</li>
            <li><b className="text-fg">Flujo de trabajo</b>: estados y transiciones permitidas. Las columnas del tablero agrupan estados.</li>
            <li><b className="text-fg">Roles</b>: Administrador, Miembro y Observador controlan qué puede hacer cada persona por proyecto.</li>
          </ul>
        </section>
      </div>
    </main>
  );
}

# Gestiona

Gestión de proyectos y trabajo del equipo, de uso interno y self-hosted. Ofrece las funciones
principales de un gestor tipo Jira: proyectos Scrum/Kanban, backlog, sprints, tableros con
drag & drop, flujos de trabajo configurables, búsqueda avanzada (JQL), informes y notificaciones
en tiempo real.

- **Backend:** Django 6.1 + Django Ninja (API REST tipada / OpenAPI), PostgreSQL, Redis,
  Django Channels (WebSockets), Celery (notificaciones y correos), django-allauth (login + SSO).
- **Frontend:** Next.js 16 (App Router) + React 19 en JavaScript (JS/JSX), TanStack Query, Tailwind CSS 4, TipTap
  (editor), pragmatic-drag-and-drop, Recharts.
- **Despliegue:** Docker Compose + Caddy (HTTPS automático).

## Funcionalidades

| Área | Incluye |
|---|---|
| Proyectos | Plantillas Scrum / Kanban / Tareas, clave e índice de incidencias, acceso abierto/limitado/privado, componentes, versiones, categorías, tipo de incidencia por defecto |
| Roles y permisos | Roles personalizados con matriz de permisos; los roles del sistema se marcan en la base de datos (se pueden renombrar sin perder su protección) |
| Incidencias | Épicas, historias, tareas, errores, subtareas; descripción enriquecida con @menciones; comentarios; adjuntos (arrastrar y soltar); vínculos entre incidencias y enlaces web; observadores y votos; registro de trabajo y estimaciones; historial completo; clonar; mover entre proyectos (la clave antigua redirige); archivar/restaurar (archivada = solo lectura); campos personalizados; marcar como impedimento |
| Cambio masivo | Editar campos, etiquetas, transicionar, mover de proyecto (con mapeo de tipos y estados según el flujo destino), observar, archivar o eliminar muchas incidencias a la vez |
| Backlog | Orden manual por arrastre, selección múltiple, sprints futuros, creación rápida inline, totales por estado |
| Sprints | Crear, iniciar (duración y objetivo), editar, completar moviendo pendientes al backlog o a otro sprint, seguimiento de cambios de alcance |
| Tablero | Columnas mapeadas a estados, transiciones por arrastre (validadas por el flujo), límites WIP, carriles por responsable/épica/prioridad, filtros rápidos JQL, filtros por persona, épica y tipo |
| Flujos | Editor de estados y transiciones: origen/destino, solo responsable, roles requeridos, pedir comentario o resolución, fijar/limpiar resolución, autoasignar |
| Búsqueda | JQL con autocompletado (campos, operadores, funciones, fechas relativas), filtros guardados y destacados, exportación CSV, búsqueda en lenguaje natural con IA (opcional) |
| Automatización | Reglas «cuando → si → entonces» por proyecto o globales: disparadores (creada, transición, actualizada, asignada, comentario, programada, manual), condiciones JQL, acciones (transicionar, asignar, editar, comentar, subtareas, notificar, observar, webhook), plantillas, registro de ejecuciones |
| Paneles | Paneles personales o compartidos con gadgets: resultados de filtro, gráfico circular, estadísticas, tabla 2D, creadas vs resueltas, asignadas a mí, actividad, burndown, texto |
| Calendario | Incidencias por fecha de vencimiento; arrastrar para cambiarla |
| Formularios | Formularios públicos o internos que crean incidencias (sin necesidad de permiso de creación) |
| IA (opcional) | Resumen de incidencias, redacción de descripción y criterios de aceptación, JQL desde una pregunta. Se activa con `ANTHROPIC_API_KEY` |
| Informes | Burndown e informe de sprint, velocidad, flujo acumulado |
| Cronograma | Épicas en línea de tiempo con barras arrastrables (mover/redimensionar) |
| Planes | Planificación entre proyectos: cronograma jerárquico con dependencias (y aviso de conflictos de fechas), equipos, capacidad por sprint o iteración, versiones entre proyectos con progreso conjunto |
| Lista | Vista tipo hoja de cálculo por proyecto: columnas configurables (incluye campos personalizados), edición en línea por celda con teclado, pegar en rango, agrupar, jerarquía expandible, configuración guardada por usuario |
| Analíticas | Tiempo de ciclo y de entrega (p50/p85/p95), gráfico de control, tiempo en cada estado, throughput, WIP; entre proyectos o por JQL, con exportación CSV; también como pestañas de Informes y gadgets de panel |
| Personas | Invitaciones por correo, SSO Google/Microsoft/OpenID Connect opcional, aprovisionamiento SCIM 2.0, restricción por dominio, perfil, avatar, preferencias de notificación |
| Administración | Catálogos (estados, tipos, prioridades, resoluciones, campos, vínculos, flujos) con papelera y restauración; lo que está en uso no se puede borrar; registro de auditoría; importador desde Jira Cloud/Server |
| Tiempo real | Tableros, backlog e incidencias se actualizan solos al cambiar en otra sesión; campana de notificaciones |
| Atajos | `c` crear, `/` buscar, `m` comentar, `Ctrl+Enter` guardar |

## Desarrollo local

Requisitos: Docker, Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 24 + pnpm.

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d      # Postgres (5433), Redis, Mailpit (8025)

cd backend
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser             # tu cuenta de administrador
uv run python manage.py seed_demo --password "<clave>"   # opcional: proyecto DEMO con datos
uv run uvicorn config.asgi:application --port 8010 --reload

cd ../frontend
pnpm install
printf 'BACKEND_INTERNAL_URL=http://localhost:8010\nNEXT_PUBLIC_WS_URL=ws://localhost:8010/ws/\n' > .env.local
pnpm dev                                            # http://localhost:3000
```

Correos de desarrollo: http://localhost:8025 (Mailpit).

### Calidad

```bash
cd backend  && uv run ruff check . && uv run pytest
cd frontend && pnpm exec eslint src && pnpm build
```

La documentación interactiva de la API está en `/api/v1/docs` (requiere sesión).

## Producción

1. Servidor Linux con Docker y un dominio (o nombre interno) apuntando a él.
2. Configura las variables:
   ```bash
   cp .env.production.example .env.production   # completa SECRET_KEY, POSTGRES_PASSWORD, dominio, SMTP…
   ```
   En una red sin dominio público, cambia en `deploy/Caddyfile` a `tls internal`.
3. Levanta todo:
   ```bash
   docker compose --env-file .env.production up -d --build
   docker compose --env-file .env.production exec backend python manage.py createsuperuser
   ```
4. Entra con el superusuario, ve a **Administración → Usuarios** e invita al equipo.
5. Respaldos diarios: `deploy/backup.sh` (base de datos + adjuntos) vía cron.

### SSO (opcional)

- **Google:** crea un OAuth Client (Web) con callback `https://<dominio>/accounts/google/login/callback/`.
- **Microsoft Entra ID:** registra la app con callback `https://<dominio>/accounts/microsoft/login/callback/`.

- **OpenID Connect** (Okta, Keycloak, Authentik, Entra ID, Auth0…): callback
  `https://<dominio>/accounts/oidc/login/callback/`; variables `OIDC_SERVER_URL`, `OIDC_CLIENT_ID`,
  `OIDC_CLIENT_SECRET`, `OIDC_NAME`.

Activa con `SSO_GOOGLE_ENABLED=true` / `SSO_MICROSOFT_ENABLED=true` / `SSO_OIDC_ENABLED=true` y sus credenciales.
`ALLOWED_SIGNUP_DOMAINS=tu-empresa.com` permite que cualquiera del dominio entre sin invitación;
vacío = solo usuarios invitados.

### SCIM (aprovisionamiento de usuarios)

En **Administración → SSO y SCIM** crea un token y configura en tu proveedor de identidad la URL
`https://<dominio>/scim/v2` con ese token. Altas, cambios y bajas se sincronizan solos (una baja
desactiva la cuenta, no la borra). El token solo se muestra una vez y se guarda como hash.

### Otras variables

| Variable | Para qué |
|---|---|
| `ANTHROPIC_API_KEY`, `AI_MODEL`, `AI_EFFORT` | Activa el asistente de IA. Sin clave, sus botones no aparecen. Al usarlo se envía el texto de la incidencia a la API de Anthropic |
| `AUDIT_RETENTION_DAYS` | Días que se conserva el registro de auditoría (365 por defecto) |
| `AUTOMATION_WEBHOOK_ALLOW_PRIVATE` | Permite webhooks de automatización hacia IPs internas (bloqueado por defecto) |
| `IMPORTS_ALLOW_PRIVATE` | Permite importar desde un Jira en la red interna (bloqueado por defecto) |

### Entorno de pruebas (sandbox)

Para probar cambios de configuración o automatizaciones sin tocar producción, levanta una segunda
instancia con su propio `.env` (otro dominio, otra base de datos) restaurando un respaldo de
`deploy/backup.sh`. Hazlo en otro servidor: en el mismo, Caddy ya ocupa los puertos 80/443.

```bash
docker compose -p gestiona-staging --env-file .env.staging up -d --build
```

## Arquitectura

```
Navegador ──HTTPS──▶ Caddy ─┬─ /api, /ws, /_allauth, /admin ─▶ backend (Django ASGI, uvicorn)
                            ├─ /media/avatars ─▶ archivos           │
                            └─ resto ─▶ frontend (Next.js)          ├─ PostgreSQL
                                                                     ├─ Redis (Channels, cache, broker)
                                            worker (Celery) ◀────────┘  (notificaciones, emails)
```

- Toda la lógica de negocio vive en `backend/apps/*/services.py`; la API solo valida y serializa.
- Los permisos se resuelven en `apps/projects/permissions.py` (único punto de verdad).
- El orden manual (backlog/tablero) usa *fractional indexing* (`apps/core/ranking.py`):
  mover una incidencia actualiza una sola fila.
- Los adjuntos se descargan siempre a través de la API, que verifica permisos.
- El contenido enriquecido se sanea en el servidor con una lista blanca de nodos, marcas y
  atributos (`apps/core/richtext.py`).
#   g e s t i o n a  
 #   g e s t i o n a  
 
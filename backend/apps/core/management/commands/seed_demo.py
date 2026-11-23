"""Create demo users, a Scrum project with epics/stories/bugs and an active sprint.

    python manage.py seed_demo --password "una-clave-segura"

Idempotent: does nothing if project DEMO already exists. For development / evaluation only.
"""

import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.boards import services as boards
from apps.issues import services as issues
from apps.issues.models import IssueType
from apps.projects.models import Project
from apps.projects.services import create_project, set_member
from apps.workflows.models import Status

PEOPLE = [
    ("ana.torres@demo.local", "Ana Torres", "Product Owner"),
    ("bruno.diaz@demo.local", "Bruno Díaz", "Backend"),
    ("carla.rios@demo.local", "Carla Ríos", "Frontend"),
    ("diego.salas@demo.local", "Diego Salas", "QA"),
]

EPICS = {
    "Portal de clientes": [
        ("Historia", "Como cliente quiero iniciar sesión con mi correo"),
        ("Historia", "Como cliente quiero ver el estado de mis pedidos"),
        ("Tarea", "Configurar CDN para recursos estáticos"),
        ("Error", "El botón de recuperar contraseña no envía el correo"),
    ],
    "Facturación electrónica": [
        ("Historia", "Generar comprobantes en formato XML"),
        ("Historia", "Enviar comprobantes por correo al cliente"),
        ("Error", "El total no redondea a dos decimales"),
    ],
    "Panel de métricas": [
        ("Historia", "Gráfico de ventas por semana"),
        ("Tarea", "Definir KPIs con el área comercial"),
    ],
}


class Command(BaseCommand):
    help = "Carga datos de demostración"

    def add_arguments(self, parser):
        parser.add_argument("--password", default=None)
        parser.add_argument("--admin-email", default="admin@demo.local")

    @transaction.atomic
    def handle(self, *args, password=None, admin_email=None, **opts):
        User = get_user_model()
        if Project.objects.filter(key="DEMO").exists():
            self.stdout.write("DEMO ya existe; nada que hacer.")
            return
        if not password:
            self.stderr.write("Indica --password para las cuentas demo")
            return
        admin, created = User.objects.get_or_create(
            email=admin_email, defaults={"full_name": "Administrador", "is_staff": True,
                                         "is_superuser": True})
        if created:
            admin.set_password(password)
            admin.save()
        people = []
        for email, name, title in PEOPLE:
            u, c = User.objects.get_or_create(email=email,
                                              defaults={"full_name": name, "job_title": title})
            if c:
                u.set_password(password)
                u.save()
            people.append(u)
        p = create_project(admin, name="Proyecto Demo", key="DEMO", template="scrum",
                           description="Proyecto de ejemplo para explorar Gestiona")
        for u in people:
            set_member(admin, p, u.id, None)  # default role
        types = {t.name: t for t in IssueType.objects.all()}
        board = p.boards.get()
        s1 = boards.create_sprint(admin, board, goal="Login y facturación básica")
        boards.create_sprint(admin, board)
        rnd = random.Random(7)
        statuses = {s.name: s for s in Status.objects.all()}
        created_issues = []
        for epic_name, items in EPICS.items():
            epic = issues.create_issue(admin, p, issues.IssueInput(
                issue_type_id=types["Épica"].id, summary=epic_name))
            for tname, summary in items:
                i = issues.create_issue(rnd.choice(people), p, issues.IssueInput(
                    issue_type_id=types[tname].id, summary=summary, parent_id=epic.id,
                    assignee_id=rnd.choice(people).id, story_points=rnd.choice([1, 2, 3, 5, 8]),
                    labels=rnd.sample(["backend", "frontend", "ux", "infra"], k=rnd.randint(0, 2)),
                    priority_id=None))
                created_issues.append(i)
        sub_parent = created_issues[0]
        for s in ["Diseñar formulario", "Validar correo", "Pruebas end-to-end"]:
            issues.create_issue(admin, p, issues.IssueInput(
                issue_type_id=types["Subtarea"].id, summary=s, parent_id=sub_parent.id))
        boards.move_issues_to_sprint(admin, board, [i.id for i in created_issues[:6]], s1)
        boards.start_sprint(admin, s1, start_date=timezone.now() - timedelta(days=3),
                            end_date=timezone.now() + timedelta(days=11))
        for i, st in zip(created_issues[:6], ["Listo", "En curso", "En revisión", "En curso",
                                              "Por hacer", "Listo"], strict=False):
            if st != "Por hacer":
                issues.transition_issue(admin, i, to_status_id=statuses[st].id)
        issues.add_comment(people[0], created_issues[1],
                           "Revisemos el diseño con el equipo antes de implementarlo.")
        self.stdout.write(self.style.SUCCESS(
            f"Listo. Admin: {admin_email} · Usuarios: {', '.join(e for e, _, _ in PEOPLE)}"))

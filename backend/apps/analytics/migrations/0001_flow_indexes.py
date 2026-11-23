"""Indexes for the flow analytics queries (apps/analytics/metrics.py).

They live on `issues` tables but are created here, so this app owns them and no migration
numbering has to be coordinated in `issues`. Built CONCURRENTLY: no write lock on big tables.
"""

from django.db import migrations

STATUS_ITEMS = """'[{"field": "status"}]'::jsonb"""

INDEXES = [
    # Status-change events per issue: the source of every flow metric.
    ("analytics_ih_status_idx", "issues_issuehistory (issue_id, created_at)",
     f"WHERE items @> {STATUS_ITEMS}"),
    # Resolved-in-range scans (throughput, cycle/lead time, control chart).
    ("analytics_issue_resolved_idx", "issues_issue (project_id, resolved_at)",
     "WHERE resolved_at IS NOT NULL"),
    # Created-in-range scans (created vs resolved).
    ("analytics_issue_created_idx", "issues_issue (project_id, created_at)", ""),
]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("issues", "0006_type_and_project_defaults"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {target} {where}",
            reverse_sql=f"DROP INDEX CONCURRENTLY IF EXISTS {name}",
        )
        for name, target, where in INDEXES
    ]

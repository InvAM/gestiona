from django.contrib import admin

from .models import Plan, PlanRelease, PlanView, Team

for m in (Plan, Team, PlanRelease, PlanView):
    admin.site.register(m)

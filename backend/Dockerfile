FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
ENV PATH="/app/.venv/bin:$PATH" DJANGO_SETTINGS_MODULE=config.settings
RUN SECRET_KEY=build-only-not-secret DEBUG=true python manage.py collectstatic --noinput

RUN useradd --system --uid 1001 gestiona && mkdir -p /app/media && chown -R gestiona /app/media /app/staticfiles
USER gestiona
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers ${WEB_WORKERS:-2} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 10"]

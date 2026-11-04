FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ZPERMIT_PUBLIC_DEMO=true PYTHONPATH=/app/backend
WORKDIR /app
COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/app ./backend/app
RUN pip install --no-cache-dir ./backend && useradd --uid 10001 --create-home zpermit
COPY --from=frontend /build/dist ./frontend/dist
USER zpermit
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.public_demo:create_demo_app --factory --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --limit-concurrency 64 --timeout-keep-alive 5 --no-access-log"]

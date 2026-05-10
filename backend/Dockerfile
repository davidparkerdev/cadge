# syntax=docker/dockerfile:1.7
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /repo
COPY domains/agentic-development/cadge/backend/requirements.txt /repo/domains/agentic-development/cadge/backend/requirements.txt
WORKDIR /repo/domains/agentic-development/cadge/backend
RUN pip install --no-cache-dir -r requirements.txt
COPY domains/agentic-development/cadge/backend /repo/domains/agentic-development/cadge/backend
ENV PORT=33401
EXPOSE 33401
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:33401/api/health || exit 1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]

FROM python:3.13-slim AS python-build

WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM node:22-slim AS node-build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM python:3.13-slim

ENV PATH=/home/appuser/.local/bin:${PATH} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# MCP subprocesses need Node.js. curl supplies a lightweight container health check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

COPY --from=python-build /root/.local /home/appuser/.local
COPY --from=node-build /app/node_modules /app/node_modules
COPY . .

RUN mkdir -p /app/workspace \
    && chown -R appuser:appuser /app /home/appuser/.local

USER appuser
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail http://127.0.0.1:${PORT}/health || exit 1

CMD ["python", "main.py"]

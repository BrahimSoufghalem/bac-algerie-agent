FROM node:24-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY frontend/ frontend/
COPY vite.config.js tsconfig.json ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt \
    && useradd --create-home --uid 10001 bac
COPY bac/ bac/
COPY migrations/ migrations/
COPY config/ config/
COPY --from=frontend /build/dist/ dist/
RUN mkdir -p /app/data && chown bac:bac /app/data
USER bac
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3)"
CMD ["uvicorn","bac.api.main:app","--host","0.0.0.0","--port","8090"]

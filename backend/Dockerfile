# Build from the repo root:  docker build -f backend/Dockerfile -t gridwise-api .
# Run:                        docker run --env-file .env -p 8000:8000 gridwise-api
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/ backend/
# auto-sync (backend/app/refresh.py) runs `python -m db.sync`, which reads ingestion/config.py
COPY db/ db/
COPY ingestion/__init__.py ingestion/config.py ingestion/

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]

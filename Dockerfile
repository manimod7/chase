# Build from the repository root: docker build -t chase .  (gcloud run deploy --source . uses this file)
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY web web
# The model, matches and calibration report live in web/data, so the API and the site share one source.
USER nobody
EXPOSE 8080
CMD exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT}

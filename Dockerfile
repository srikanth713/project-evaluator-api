FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as an unprivileged user; /app/data holds the SQLite database.
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/data && chown -R appuser /app
USER appuser

EXPOSE 8000

# Render injects $PORT; default to 8000 for local `docker run`.
# --proxy-headers lets rate limiting see the real client IP behind Render's proxy.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]

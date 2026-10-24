FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# PERSISTENCE: bookings/orders/conversations live in SQLite (or PostgreSQL if
# DATABASE_URL is set). The container filesystem is wiped on every redeploy, so in
# Coolify add a Storage "Volume Mount" with destination /app/data and set the env var
#   AMVERIO_DB_PATH=/app/data/amverio.db
# (not baked in here on purpose: the live deployment is configured in Coolify).

# OPENAI_API_KEY is provided at runtime via Coolify's environment variables,
# never baked into the image.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

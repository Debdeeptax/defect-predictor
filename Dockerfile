# Optional container image. NOTE: written without a local Docker install, so it has not
# been built/tested by the author — see README "Docker (optional, untested)".
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=5000

# git: needed for "analyse a Git URL"
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn==23.0.0

COPY . .
RUN useradd --create-home sdp && mkdir -p instance logs && chown -R sdp:sdp instance logs models
USER sdp

EXPOSE 5000
# SECRET_KEY must be provided at runtime. SEED_DEMO_DATA=1 creates the demo accounts
# (known passwords: demo only, never in production).
CMD ["sh", "-c", "if [ \"$SEED_DEMO_DATA\" = \"1\" ]; then python scripts/seed.py; fi && exec gunicorn 'run:app' --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 300"]

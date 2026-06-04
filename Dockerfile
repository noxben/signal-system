FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2 and spaCy
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# spaCy model — non-fatal if download fails at build time
RUN python -m spacy download en_core_web_sm || echo "spaCy model download failed — will retry at runtime"

COPY . .

# Verify the package is importable before container starts
RUN python -c "import signal_system; print('signal_system package OK')"

CMD ["python", "-m", "signal_system.scheduler"]

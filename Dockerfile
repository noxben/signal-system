FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2 and spaCy
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt# --- STEP 6: FIX SPA_CY DOWNLOAD BREAKAGE ---
# Swap out 'RUN python -m spacy download en_core_web_sm' with the direct wheel:
RUN pip install --no-cache-dir https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

COPY . .

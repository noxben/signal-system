FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2 and spaCy
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# spaCy model — small English model for NER (Week 2)
RUN python -m spacy download en_core_web_sm

COPY . .

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Verify imports before starting
RUN python -c "import signal_system; import spacy; spacy.load('en_core_web_sm'); print('startup checks passed')"

CMD ["python", "-m", "signal_system.scheduler"]

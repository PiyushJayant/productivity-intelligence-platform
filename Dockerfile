FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (Docker layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY productivity_intelligence ./agents/productivity_intelligence

EXPOSE 8080

# Use PORT env var injected by Cloud Run (defaults to 8080)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]

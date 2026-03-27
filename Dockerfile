FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if any (none needed for basic FastAPI)
# RUN apt-get update && apt-get install -y --no-install-recommends ... && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Environment variables
ENV MESH_MONITOR_API_BASE_URL=https://domain.com
ENV MESH_MONITOR_API_TOKEN=
ENV POLL_INTERVAL_SECONDS=10
ENV MESSAGE_LIMIT=50

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

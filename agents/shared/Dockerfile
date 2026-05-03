FROM python:3.12-slim

WORKDIR /app

# Install system deps for psycopg + cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc \
      libpq-dev \
      && rm -rf /var/lib/apt/lists/*

COPY agents/requirements.txt /app/agents/requirements.txt
RUN pip install --no-cache-dir -r /app/agents/requirements.txt

# Copy the agents tree + contracts (for ABI access) + demo seeds
COPY agents /app/agents
COPY orchestrator /app/orchestrator
COPY contracts /app/contracts
COPY demo /app/demo

# Each service overrides CMD via docker-compose
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "agents.shared.research_app_factory:build_research_app", "--host", "0.0.0.0", "--port", "7000"]

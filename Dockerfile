FROM python:3.12-slim

# Install uv and curl (curl needed for healthcheck)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps via uv
COPY pyproject.toml ./
RUN uv pip install --system --break-system-packages \
    nicegui sqlalchemy aiosqlite apscheduler httpx python-dotenv

COPY . .

EXPOSE 8090

CMD ["python", "main.py"]

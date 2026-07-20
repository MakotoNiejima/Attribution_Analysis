FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN pip install --upgrade pip && pip install uv && uv sync --frozen --no-dev
COPY app ./app
COPY datacompose ./datacompose

ENV PATH="/app/.venv/bin:${PATH}" \
    APP_STORAGE_ROOT=/app/runtime_data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

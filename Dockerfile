FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV APP_TARGET=api

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md QUICKSTART.md /app/
COPY src /app/src
RUN mkdir -p /app/data/operations

ENV UV_CONCURRENT_BUILDS=1
ENV UV_LINK_MODE=copy
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir uv \
    && uv pip install --system --no-cache .

EXPOSE 8000 8501

CMD ["/bin/sh", "-c", "if [ \"$APP_TARGET\" = \"ui\" ]; then streamlit run src/agentic_tour_planner/app/streamlit_app.py --server.port=${STREAMLIT_SERVER_PORT:-8501} --server.address=0.0.0.0; else tour-planner-api; fi"]

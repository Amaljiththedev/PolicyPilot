# PolicyPilot API image: Python + CPU-only PyTorch + both models baked in.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

# 1. CPU-only torch first (~200MB instead of ~2.5GB of CUDA wheels)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# 2. Python deps (own layer: only rebuilt when requirements.txt changes)
COPY requirements.txt .
RUN pip install -r requirements.txt

# 3. Download the models at build time, so the container starts offline and fast
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
ARG RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('${EMBEDDING_MODEL}'); CrossEncoder('${RERANK_MODEL}')"

# 4. App code last (changes most often)
COPY . .

# run as a non-root user
RUN useradd --create-home appuser && chown -R appuser /app /models
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

CMD ["python", "docker/start.py"]

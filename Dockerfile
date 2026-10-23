FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml ./
COPY pharma_scope/ ./pharma_scope/
RUN python -m pip install ".[ai,search]" \
    && groupadd --gid 10001 pharma \
    && useradd --uid 10001 --gid pharma --create-home pharma \
    && mkdir -p /data \
    && chown pharma:pharma /data

USER pharma
ENTRYPOINT ["pharma", "--data-dir", "/data"]
CMD ["doctor"]

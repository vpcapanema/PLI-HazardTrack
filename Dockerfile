# ============================================================================
# PLI-HazardTrack - imagem de producao
# Inclui libeccodes (C) para o pacote Python eccodes funcionar.
# ============================================================================
FROM python:3.11-slim

# --- Sistema -----------------------------------------------------------------
# libeccodes0:        runtime da biblioteca C do ECMWF
# libeccodes-tools:   utilitarios (debug)
# curl + ca-certs:    healthcheck e fetch HTTPS confiavel
# build-essential:    so para compilar wheels nativas se necessario; depois removemos
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libeccodes0 \
        libeccodes-tools \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --- App ---------------------------------------------------------------------
WORKDIR /app

# Instala deps primeiro para aproveitar cache de layer
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copia o codigo
COPY . ./

# Boas praticas de runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5050 \
    SAMAEG_WORKERS=4

EXPOSE 5050

# Healthcheck no nivel do container (Render tambem usa /api/health)
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

# CMD em shell para expandir $PORT
CMD ["sh", "-c", "exec gunicorn app:app --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 180 --graceful-timeout 30 --access-logfile - --error-logfile -"]

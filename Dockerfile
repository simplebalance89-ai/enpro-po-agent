FROM python:3.11-slim

LABEL maintainer="EnPro PO Automation"
LABEL description="Ariba/Coupa PO automation agent with P21 CISM integration"
LABEL version="1.0"

RUN groupadd -r enpro && useradd -r -g enpro -d /app -s /sbin/nologin enpro

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libxml2-dev \
    libxslt1-dev \
    curl \
    gnupg \
    ca-certificates \
    apt-transport-https \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
       | gpg --dearmor -o /etc/apt/keyrings/microsoft-prod.gpg \
    && chmod a+r /etc/apt/keyrings/microsoft-prod.gpg \
    && . /etc/os-release \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/${VERSION_ID}/prod ${VERSION_CODENAME} main" \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data/cism_output /app/data/cism_so_output /app/data/crosswalks \
    /app/data/po_store /app/data/p21_data /app/data/quote_data /app/logs /app/test_data \
    && chown -R enpro:enpro /app

USER enpro

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",8000)}/health')" || exit 1

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]


FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TDX_AUTH=github \
    FASTMCP_HOME=/data/fastmcp

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py ./
COPY app ./app
COPY config ./config
COPY specs ./specs
RUN mkdir -p /data/fastmcp


# Cloud Run sets $PORT (8080); server.py reads it.
EXPOSE 8080
CMD ["python", "server.py", "--http"]

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY deals ./deals
RUN pip install --no-cache-dir . && useradd -r -u 10001 mnat && mkdir -p /data && chown mnat /data
USER mnat
ENV MNAT_DB=/data/mnat.db MNAT_OUT=/data/out MNAT_DEALS=/app/deals
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["sh", "-c", "mnat demo --db /data/mnat.db --out /data/out --serve --port 8080"]

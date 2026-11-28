FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
WORKDIR /app
COPY packs/it_ops/v0.1/practice/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/src/slotagent/common/hashing.py /app/slotagent/common/hashing.py
COPY packs/it_ops/v0.1/practice/server.py packs/it_ops/v0.1/practice/pilot_server.py /app/
COPY packs/it_ops/v0.1/practice/servers.json packs/it_ops/v0.1/practice/pilot_manifest.json packs/it_ops/v0.1/practice/pilot_fixture.json /app/
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
ENTRYPOINT ["python", "/app/pilot_server.py", "--manifest", "/app/pilot_manifest.json", "--data-dir", "/data"]

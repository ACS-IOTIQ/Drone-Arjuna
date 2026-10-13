# TLS / production frontend

Production serves the built SPA from nginx over TLS 1.2/1.3 and proxies `/api` (REST + WebSockets)
to the backend, which is no longer published on the host.

```
# 1. certificate (use your CA; for an internal test, a self-signed one)
mkdir certs
openssl req -x509 -newkey rsa:4096 -nodes -days 365 -keyout certs/tls.key -out certs/tls.crt \
  -subj "/CN=gcs.local" -addext "subjectAltName=DNS:gcs.local,DNS:localhost,IP:127.0.0.1"

# 2. .env: PUBLIC_ORIGIN=https://gcs.local   (becomes the CORS origin)
# 3. start
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

`certs/` is git-ignored. Mount a CA-issued certificate for real deployments.

## Not yet covered
- Data-store TLS (PostgreSQL, Redis, RabbitMQ, Elasticsearch) and MinIO `secure=True`: these links stay on
  the private Docker network; enabling them needs per-service certificates.
- Presigned MinIO URLs are built from `MINIO_PUBLIC_ENDPOINT`. For an HTTPS page they must be https
  (browsers block mixed content), so front MinIO with TLS and add its host to the CSP
  `img-src`/`media-src` in `frontend/nginx/security-headers.inc`.

## MAVLink signing
Set `MAVLINK_SIGNING_KEY` (64 hex chars) and configure the same key on each autopilot
(ArduPilot: MAVProxy `signing setup`, or Mission Planner "MAVLink signing"). Once set, unsigned frames
(other than RADIO_STATUS) are dropped and outgoing frames are signed. The app runs pymavlink in
MAVLink 2 mode, which signing requires.

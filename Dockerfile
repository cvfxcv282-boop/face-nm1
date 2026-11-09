# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium git ca-certificates fonts-noto-core fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home appuser
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements.txt
COPY cloud_app.py mobile.html mobile.js docker_entrypoint.py ./
RUN mkdir /app/data && chown -R appuser:appuser /app
ENV PORT=10000 COOKIE_SECURE=1 FB_MANAGER_DATA=/app/data BROWSER_EXECUTABLE=/usr/bin/chromium
EXPOSE 10000
CMD ["python", "docker_entrypoint.py"]

# kyc — build from the repository root:
#   docker build -f services/kyc/Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv
RUN groupadd --system app && useradd --system --gid app app

COPY libs/zeo-common /tmp/zeo-common
RUN pip install /tmp/zeo-common && rm -rf /tmp/zeo-common

COPY services/kyc/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Face models (YuNet + SFace, ~39 MB) are downloaded and checksummed at build time, not committed.
COPY services/kyc/scripts/fetch_face_models.py /tmp/fetch_face_models.py
RUN python /tmp/fetch_face_models.py /srv/models && rm /tmp/fetch_face_models.py
ENV KYC_FACE_MODELS_DIR=/srv/models

COPY services/kyc/app ./app

USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
# Render injects PORT; locally it defaults to 8000.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

# escrow-sweep — build from the repository root:
#   docker build -f services/escrow-sweep/Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv
RUN groupadd --system app && useradd --system --gid app app

COPY libs/zeo-common /tmp/zeo-common
RUN pip install /tmp/zeo-common && rm -rf /tmp/zeo-common

COPY services/escrow-sweep/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY services/escrow-sweep/app ./app

USER app
CMD ["python", "-m", "app.sweep"]

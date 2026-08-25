FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt /app/requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install -r /app/requirements.txt && \
    python -c "from PIL import Image, ImageOps; print('[Build] Pillow OK')"

COPY . /app

RUN test -f /app/app.py && \
    test -f /app/models.py && \
    test -f /app/wsgi.py && \
    test -f /app/scripts/start_render.sh && \
    chmod +x /app/scripts/start_render.sh && \
    python -m py_compile /app/app.py /app/models.py /app/config.py /app/wsgi.py && \
    python /app/scripts/check_models.py

CMD ["bash", "/app/scripts/start_render.sh"]

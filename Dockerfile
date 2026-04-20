FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY bot.py downloader.py ./

RUN useradd --create-home --shell /usr/sbin/nologin botuser \
    && mkdir -p /app/downloads \
    && chown -R botuser:botuser /app

USER botuser

CMD ["python", "bot.py"]

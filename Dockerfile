FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NTC_TEMPLATES_DIR=/usr/local/lib/python3.13/site-packages/ntc_templates/templates

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        libyaml-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /usr/local/lib/python3.13/site-packages/ntc_templates/templates

# Copy custom NTC templates into the site-packages path used by ntc_templates
COPY ntc-template/ /usr/local/lib/python3.13/site-packages/ntc_templates/templates/

COPY app ./app
COPY custom_tasks ./custom_tasks
COPY main.py ./main.py
COPY .env .env

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

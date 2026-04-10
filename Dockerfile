ARG PYTHON_BASE_IMAGE=python:3.11-slim@sha256:ad65166ad2583036804a3f772ec8f1cad733cf77d631c6840ab1ea9231b6b350
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    krb5-user \
    libkrb5-dev \
    ldap-utils \
    libsasl2-modules \
    libsasl2-modules-gssapi-mit \
    curl \
    libgl1 \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.lock

COPY . .

RUN addgroup --system app && adduser --system --ingroup app app && \
    chown -R app:app /app

USER app

EXPOSE 8000

CMD ["python", "start_app.py"]

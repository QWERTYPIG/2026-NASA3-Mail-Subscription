# Use a lightweight Python base image
FROM python:3.11-slim-bookworm

ARG PG_MAJOR=15

# Prevent Python from writing .pyc files to disc
ENV PYTHONDONTWRITEBYTECODE 1
# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED 1

# Set the working directory
WORKDIR /app

# Install system dependencies required for LDAP and PostgreSQL.
# apt-get upgrade patches stale base-image packages (e.g. libgnutls30, libkrb5*)
# that apt-get install alone leaves untouched — required to clear fixable OS CVEs.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libldap2-dev \
        libsasl2-dev \
        postgresql-client-${PG_MAJOR} \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies.
# Upgrade setuptools/wheel too: their bundled copies (e.g. jaraco.context, wheel)
# carry fixable HIGH CVEs that Trivy flags even though they are build-time only.
COPY requirements.txt /app/
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# The code will be mounted via volumes in docker-compose during development,
# but we copy it here for a production-ready image.
COPY . /app/

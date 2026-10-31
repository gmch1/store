FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp/store-home
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jdk-headless aapt apksigner libmagic1 git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY store ./store
COPY LICENSE ./LICENSE
USER 1000:1000
ENTRYPOINT ["python", "-m", "store"]
CMD ["api"]

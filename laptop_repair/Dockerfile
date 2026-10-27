FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /opt/laptop-repair
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

# Supervisor supplies the io.hass.* architecture/type/version labels at build time.
LABEL org.opencontainers.image.title="Laptop Repair Manager" \
      org.opencontainers.image.description="Laptop repair inventory and resale tracking" \
      org.opencontainers.image.version="1.2.0"

EXPOSE 8099
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8099/health', timeout=3)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099", "--no-proxy-headers"]

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 DASHBOARD_AUTH_REQUIRED=1
COPY requirements.txt ./
RUN pip install -r requirements.txt && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin dashboard
COPY src/ src/
USER 10001:10001
EXPOSE 8770
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8770/healthz',timeout=3)"
CMD ["python", "src/server.py", "--host", "0.0.0.0", "--port", "8770"]

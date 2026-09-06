FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=5000 BIND_HOST=0.0.0.0
WORKDIR /app
RUN useradd --create-home --uid 10001 agenda
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scheduler ./scheduler
COPY run.py .
RUN mkdir -p /app/data && chown -R agenda:agenda /app
USER agenda
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3)"
CMD ["waitress-serve", "--call", "--listen=0.0.0.0:5000", "scheduler.app:create_app"]

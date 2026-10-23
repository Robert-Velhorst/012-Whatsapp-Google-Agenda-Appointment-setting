FROM python:3.15.1-slim-trixie@sha256:08275f764e022331c6d3e3ca55d8cce01fa4684b02111adf0445d71806fe7941 AS sqlite-build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY tools/prepare_sqlite_runtime.py ./tools/prepare_sqlite_runtime.py
RUN python tools/prepare_sqlite_runtime.py
RUN mkdir -p /opt/sqlite/lib && python -c "import json,pathlib,shutil; d=json.loads(pathlib.Path('.runtime/sqlite-runtime.json').read_text()); shutil.copy2(pathlib.Path(d['library_directory'])/'libsqlite3.so.0','/opt/sqlite/lib/libsqlite3.so.0')"

FROM python:3.15.1-slim-trixie@sha256:08275f764e022331c6d3e3ca55d8cce01fa4684b02111adf0445d71806fe7941 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=5000 BIND_HOST=0.0.0.0 APP_ENV=production LD_LIBRARY_PATH=/opt/sqlite/lib
COPY --from=sqlite-build /opt/sqlite/lib /opt/sqlite/lib
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN python -c "import sqlite3; assert sqlite3.sqlite_version=='3.54.1'"
WORKDIR /app
RUN useradd --create-home --uid 10001 agenda
COPY requirements-runtime.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements-runtime.lock \
    && python -c "import importlib.util; assert importlib.util.find_spec('pytest') is None, 'pytest must not ship in the production image'"
COPY scheduler ./scheduler
COPY run.py .
RUN mkdir -p /app/data && chown -R agenda:agenda /app
USER agenda
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3)"
CMD ["waitress-serve", "--call", "--listen=0.0.0.0:5000", "scheduler.app:create_app"]

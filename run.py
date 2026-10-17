import os

from scheduler.app import create_app
from scheduler.config import validate_bind_host

app = create_app()

if __name__ == "__main__":
    settings = app.extensions["settings"]
    host = validate_bind_host(os.getenv("BIND_HOST", "127.0.0.1"), settings.is_production)
    port = int(os.getenv("PORT", "5000"))
    if settings.is_production:
        from waitress import serve
        serve(app, host=host, port=port, threads=8, url_scheme="https")
    else:
        app.run(host=host, port=port, debug=False, use_reloader=False)

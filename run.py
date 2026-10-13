import os

from scheduler.app import create_app
from scheduler.config import Settings, validate_server_bind

if __name__ == "__main__":
    settings = Settings.from_env()
    host = os.getenv("BIND_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    validate_server_bind(settings.app_env, host)
    app = create_app()
    if settings.is_production:
        from waitress import serve
        serve(app, host=host, port=port, threads=8, url_scheme="https")
    else:
        app.run(host=host, port=port, debug=False, use_reloader=False)

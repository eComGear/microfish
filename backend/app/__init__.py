import logging
import os
from flask import Flask, jsonify
from flask_cors import CORS

logger = logging.getLogger(__name__)

OPTIONAL_BLUEPRINTS = [
    ("app.api.simulation", "simulation_bp", "/api/simulation"),
    ("app.api.report",     "report_bp",     "/api/report"),
    ("app.api.upload",     "upload_bp",     "/api/upload"),
    ("app.api.task",       "task_bp",       "/api/task"),
    ("app.api.chat",       "chat_bp",       "/api/chat"),
    ("app.api.project",    "project_bp",    "/api/project"),
]

def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64MB upload
    CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=False)

    @app.get("/")
    def root():
        return jsonify({"service": "microfish", "status": "ok"})

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    # Required: graph blueprint
    from app.api.graph import graph_bp
    app.register_blueprint(graph_bp, url_prefix="/api/graph")

    # Optional blueprints (skip silently if missing)
    for module_path, bp_name, url_prefix in OPTIONAL_BLUEPRINTS:
        try:
            mod = __import__(module_path, fromlist=[bp_name])
            bp = getattr(mod, bp_name, None)
            if bp is not None:
                app.register_blueprint(bp, url_prefix=url_prefix)
                logger.info("registered blueprint %s at %s", bp_name, url_prefix)
        except Exception as e:
            logger.warning("skip blueprint %s: %s", module_path, e)

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"success": False, "error": "not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        logger.exception("500: %s", e)
        return jsonify({"success": False, "error": "internal error"}), 500

    return app

app = create_app()


# Gunicorn entrypoint: `gunicorn "app:create_app()"`


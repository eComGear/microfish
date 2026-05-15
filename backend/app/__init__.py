"""Flask application factory for MiroFish backend."""
import os
from flask import Flask, jsonify
from flask_cors import CORS


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 MB uploads

    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        supports_credentials=False,
        expose_headers=["Content-Type", "Authorization"],
    )

    # ---- Health endpoints ----
    @app.route("/", methods=["GET"])
    def root():
        return jsonify({"service": "microfish", "status": "ok"})

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"})

    # ---- Blueprints ----
    from app.api.graph import graph_bp
    app.register_blueprint(graph_bp, url_prefix="/api/graph")

    # Register the rest only if they exist (don't crash boot if a module is missing)
    _optional_blueprints = [
        ("app.api.simulation", "simulation_bp", "/api/simulation"),
        ("app.api.report", "report_bp", "/api/report"),
        ("app.api.upload", "upload_bp", "/api/upload"),
        ("app.api.project", "project_bp", "/api/project"),
        ("app.api.task", "task_bp", "/api/task"),
        ("app.api.chat", "chat_bp", "/api/chat"),
    ]
    for module_path, attr, prefix in _optional_blueprints:
        try:
            module = __import__(module_path, fromlist=[attr])
            bp = getattr(module, attr, None)
            if bp is not None:
                app.register_blueprint(bp, url_prefix=prefix)
        except Exception as exc:  # noqa: BLE001
            app.logger.warning(f"skip blueprint {module_path}: {exc}")

    # ---- Global error handlers (always JSON) ----
    @app.errorhandler(404)
    def _404(_e):
        return jsonify({"success": False, "error": "not found"}), 404

    @app.errorhandler(500)
    def _500(_e):
        return jsonify({"success": False, "error": "internal server error"}), 500

    return app


# Gunicorn entrypoint: `gunicorn "app:create_app()"`


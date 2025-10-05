from flask import Flask
from app.config import load_configurations, configure_logging
from .views import webhook_blueprint


def create_app():
    app = Flask(__name__)

    # Load configurations and logging settings
    load_configurations(app)
    configure_logging()

    # Register blueprints
    app.register_blueprint(webhook_blueprint)

    # Optional root route for debugging
    @app.route("/")
    def home():
        return "✅ Flask is running!"

    return app

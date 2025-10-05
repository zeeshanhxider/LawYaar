import logging
from app import create_app

# Configure root logging (to console)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = create_app()

if __name__ == "__main__":
    logging.info("=" * 80)
    logging.info("🚀 Flask app starting...")
    logging.info(f"📍 Registered routes: {[str(rule) for rule in app.url_map.iter_rules()]}")
    logging.info("=" * 80)
    app.run(host="0.0.0.0", port=8000, debug=False)  # Debug=False to avoid reloader issues

# /home/ec2-user/namwoo_app/__init__.py
# FULLY CORRECTED VERSION (incorporating the fix for battery_bp import)

import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

# Database utility module manages its own engine/session outside of Flask-SQLAlchemy
from utils import db_utils

# Import application configuration
from config.config import Config, basedir

# Initialize Flask extensions
db = SQLAlchemy()
migrate = Migrate()

def create_app(config_class=Config):
    """
    Application factory function.
    Configures and returns the Flask application instance.
    """
    app = Flask(__name__)

    # 1. Load Configuration
    app.config.from_object(config_class)
    app.logger.info(f"NamFulgor application configured with '{config_class.__name__}'.")

    # 2. Initialize Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    app.logger.info("Flask extensions (SQLAlchemy, Migrate) initialized.")

    # Initialize standalone DB utilities (engine and scoped session factory)
    if not db_utils.init_db(app):
        app.logger.error("Database utilities failed to initialize. DB operations will fail.")

    # 3. Configure Logging
    if not app.debug and not app.testing:
        log_dir = os.path.join(basedir, 'logs')
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
            except OSError as e:
                app.logger.error(f"Error creating log directory {log_dir}: {e}")
        if os.path.exists(log_dir) and os.access(log_dir, os.W_OK):
            log_file_path = os.path.join(log_dir, 'namfulgor_app.log')
            file_handler = RotatingFileHandler(log_file_path, maxBytes=1024 * 1024 * 10, backupCount=5)
            file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
            file_handler.setLevel(logging.INFO)
            app.logger.addHandler(file_handler)
            app.logger.setLevel(logging.INFO)
            app.logger.info('NamFulgor application logging to file configured.')
        else:
            app.logger.warning(f"Log directory {log_dir} does not exist or is not writable. File logging disabled.")
    else:
        app.logger.setLevel(logging.DEBUG) # In debug mode, logs go to stderr by default
        app.logger.info("NamFulgor application running in DEBUG mode. Using default stderr logger.")

    # 4. Register Blueprints
    try:
        # Import 'api_bp' from the 'api' package's __init__.py file.
        # This is the blueprint instance that api/routes.py uses.
        from api import api_bp as main_api_bp
        app.register_blueprint(main_api_bp, url_prefix='/api')
        app.logger.info("Registered main API blueprint at /api.")

        # CORRECTED IMPORT FOR BATTERY BLUEPRINT:
        # Import 'battery_api_bp' (the actual name of the Blueprint instance
        # in battery_api_routes.py) and alias it to 'battery_bp' for consistency here.
        from api.battery_api_routes import battery_api_bp as battery_bp
        app.register_blueprint(battery_bp)
        app.logger.info("Registered battery API blueprint at /api/battery.")

    except ImportError as e:
        app.logger.error(f"Error importing or registering blueprints: {e}", exc_info=True)
        # Consider re-raising or exiting if blueprint registration is critical for app startup.

    # 5. Define Shell Context
    @app.shell_context_processor
    def make_shell_context():
        # These imports are fine for the shell context.
        from models.product import Product, VehicleBatteryFitment
        from models.conversation_pause import ConversationPause
        return {
            'db': db,
            'Product': Product,
            'VehicleBatteryFitment': VehicleBatteryFitment,
            'ConversationPause': ConversationPause
        }

    # Debugging aid: log all registered routes
    with app.app_context():
        app.logger.info("--- CURRENTLY REGISTERED FLASK ROUTES ---")
        for rule in app.url_map.iter_rules():
            app.logger.info(
                f"Endpoint: {rule.endpoint}, Methods: {list(rule.methods)}, Path: {str(rule)}"
            )
        app.logger.info("---------------------------------------")

    app.logger.info(f"NamFulgor Flask application instance ({app.name}) fully created and configured.")
    return app

# --- ADD THIS LINE AT THE VERY END OF THE FILE ---
# This creates the 'app' instance that Gunicorn is looking for.
app = create_app()
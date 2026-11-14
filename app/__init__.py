
import os
from flask import Flask

from app.extensions import db, login_manager, csrf


def create_app():
    application = Flask(
        __name__,
        instance_relative_config=True
    )

    os.makedirs(application.instance_path, exist_ok=True)

    application.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY",
        "dev-only-change-this-key"
    )

    application.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///" +
        os.path.join(application.instance_path, "examination.db")
    )

    application.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Initialize Flask extensions
    db.init_app(application)
    login_manager.init_app(application)
    csrf.init_app(application)

    login_manager.login_view = "main.index"

    # Import models so SQLAlchemy can create their tables
    from app import models

    # Load logged-in users for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(models.User, int(user_id))
        except (ValueError, TypeError):
            return None

    # Register routes
    from app.routes import main
    application.register_blueprint(main)

    # Create database tables
    with application.app_context():
        db.create_all()

        # Add any columns that older database files are missing.
        from app.schema_upgrade import upgrade_schema
        upgrade_schema(db)

    return application
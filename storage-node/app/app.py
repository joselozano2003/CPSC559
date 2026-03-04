import os
from flask import Flask
from .extensions import db
from .routes import bp

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    with app.app_context():
        from .models import Chunk
        db.create_all()

    app.register_blueprint(bp)

    @app.route('/health')
    def health():
        return "Connected to PostgreSQL!"

    return app
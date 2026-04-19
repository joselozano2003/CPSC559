import os
from flask import Flask
from flask_cors import CORS
from .extensions import db
from .routes import bp, send_heartbeat

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    CORS(app)
    db.init_app(app)

    with app.app_context():
        from .models import Chunk
        db.create_all()

    app.register_blueprint(bp)

    send_heartbeat()

    @app.route('/health')
    def health():
        return "Connected to PostgreSQL!"

    return app
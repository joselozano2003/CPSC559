import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from .routes import bp

load_dotenv()

app = Flask(__name__)

# Use the environment variable we set in docker-compose
app.register_blueprint(bp)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
db = SQLAlchemy(app)


@app.route('/health')
def index():
    return "Connected to PostgreSQL!"
    

if __name__ == "__main__":
    with app.app_context():
        db.create_all() # This creates the tables automatically
    app.run(host="0.0.0.0", port=5000)
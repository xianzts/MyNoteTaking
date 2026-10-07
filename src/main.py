import os
import sys
# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, send_from_directory
from flask_cors import CORS
from sqlalchemy.engine import make_url
from src.models.user import db
from src.routes.user import user_bp
from src.routes.note import note_bp
from src.routes.translate import translate_bp
from src.models.note import Note

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), 'static'))
app.config['SECRET_KEY'] = 'asdf#FGSgvasgf$5$WGT'

# Enable CORS for all routes
CORS(app)

# register blueprints
app.register_blueprint(user_bp, url_prefix='/api')
app.register_blueprint(note_bp, url_prefix='/api')
app.register_blueprint(translate_bp, url_prefix='/api')
# Use Neon/PostgreSQL on Vercel and retain SQLite only for local development.
ROOT_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
DB_PATH = os.path.join(ROOT_DIR, 'database', 'app.db')
IS_VERCEL = os.getenv('VERCEL') == '1'
database_url = os.getenv('DATABASE_URL')

if not database_url:
    if IS_VERCEL:
        raise RuntimeError('DATABASE_URL must be configured on Vercel.')
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    database_url = f'sqlite:///{DB_PATH}'
else:
    parsed_database_url = make_url(database_url)
    if parsed_database_url.drivername in {'postgres', 'postgresql'}:
        parsed_database_url = parsed_database_url.set(drivername='postgresql+psycopg')
    if parsed_database_url.drivername.startswith('postgresql') and not parsed_database_url.query.get('sslmode'):
        parsed_database_url = parsed_database_url.update_query_dict({'sslmode': 'require'})
    database_url = parsed_database_url.render_as_string(hide_password=False)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
if database_url.startswith('postgresql'):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 1 if IS_VERCEL else 5,
        'max_overflow': 0 if IS_VERCEL else 10,
    }
db.init_app(app)
with app.app_context():
    db.create_all()

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    static_folder_path = app.static_folder
    if static_folder_path is None:
            return "Static folder not configured", 404

    if path != "" and os.path.exists(os.path.join(static_folder_path, path)):
        return send_from_directory(static_folder_path, path)
    else:
        index_path = os.path.join(static_folder_path, 'index.html')
        if os.path.exists(index_path):
            return send_from_directory(static_folder_path, 'index.html')
        else:
            return "index.html not found", 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)

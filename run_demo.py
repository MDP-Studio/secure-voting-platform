from app import create_app
from app.init_db import init_database
import os


if __name__ == '__main__':
    init_database()
    app = create_app()
    # Disable the reloader to avoid multiple processes when running in background
    port = int(os.environ.get('PORT', '5000'))
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

from app import create_app
from app.init_db import init_database
import os
from dotenv import load_dotenv

load_dotenv()

app = create_app()
init_database(app)

if __name__ == '__main__':
    # Disable the reloader to avoid multiple processes when running in background
    port = int(os.environ.get('PORT', '5000'))
    print("MAIL USER:", os.environ.get("MAIL_USERNAME"))
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

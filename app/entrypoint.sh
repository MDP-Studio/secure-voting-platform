#!/bin/bash
# Initialize database (db should be ready due to depends_on in docker-compose)
export PYTHONPATH=/
python init_db.py

# Start the application
exec "$@"
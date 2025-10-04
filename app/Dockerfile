FROM python:3.11-slim

WORKDIR /app

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set Python path
ENV PYTHONPATH=/

# Copy app code
COPY . .

EXPOSE 8000

ENTRYPOINT ["sh", "-c", "export PYTHONPATH=/ && python init_db.py && exec gunicorn --pythonpath / -b 0.0.0.0:8000 wsgi:app --workers 2 --threads 4 --timeout 60"]
CMD ["gunicorn", "--pythonpath", "/", "-b", "0.0.0.0:8000", "wsgi:app", "--workers", "2", "--threads", "4", "--timeout", "60"]

FROM python:3.11-slim

WORKDIR /app

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Set Python path so app module can be found
ENV PYTHONPATH=/

EXPOSE 8000

CMD ["gunicorn", "-b", "0.0.0.0:8000", "--pythonpath", "/", "wsgi:app", "--workers", "2", "--threads", "4", "--timeout", "60"]
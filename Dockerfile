FROM python:3.11-slim

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Expose app port
EXPOSE 8000

# Run Flask with Gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:8000", "main:app", "--workers", "2", "--threads", "4", "--timeout", "60"]
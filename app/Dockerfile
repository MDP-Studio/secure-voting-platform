FROM python:3.11-slim

WORKDIR /workspace

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set Python path
ENV PYTHONPATH=/workspace

# Copy app code
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts

EXPOSE 8000

CMD ["gunicorn", "-b", "0.0.0.0:8000", "app.wsgi:app", "--workers", "2", "--threads", "4", "--timeout", "60"]

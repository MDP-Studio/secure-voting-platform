FROM python:3.11-slim

WORKDIR /app

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set Python path
ENV PYTHONPATH=/

# Copy app code
COPY . .

# Copy and set entrypoint
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "--pythonpath", "/", "-b", "0.0.0.0:8000", "wsgi:app", "--workers", "2", "--threads", "4", "--timeout", "60"]

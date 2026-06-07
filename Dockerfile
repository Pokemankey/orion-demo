FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer is cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Default command runs the pipeline — override submission path via docker-compose
ENTRYPOINT ["python", "main.py"]
CMD ["--submission", "fixtures/submission.json"]

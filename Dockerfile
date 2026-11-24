FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ scripts/
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

CMD ["python3", "scripts/otp_sync.py", "--daemon"]

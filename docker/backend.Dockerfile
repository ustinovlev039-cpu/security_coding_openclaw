FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/challenge_app

WORKDIR /app

COPY challenge_app/requirements.txt /app/challenge_app/requirements.txt
RUN pip install --no-cache-dir -r /app/challenge_app/requirements.txt

COPY challenge_app /app/challenge_app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


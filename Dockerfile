FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/mydealz.db

EXPOSE 5102

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5102"]

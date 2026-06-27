FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/data"]

ENV STATE_FILE=/data/state.json

CMD ["python", "watcher.py"]

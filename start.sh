#!/bin/sh
# Start the background worker in the background
python -m app.workers.fare_worker &

# Start the web server in the foreground
uvicorn app.main:app --host 0.0.0.0 --port $PORT

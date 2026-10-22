# People Counting System

## Run locally
    python -m venv venv
    venv\Scripts\activate          # Windows  (Mac/Linux: source venv/bin/activate)
    pip install -r requirements.txt
    uvicorn app:app --host 0.0.0.0 --port 8000
Open http://localhost:8000

## Run with Docker
    docker build -t people-counting .
    docker run -p 8000:8000 people-counting

## Layout
    app.py          FastAPI server (API + serves the frontend)
    counting.py     Detection, tracking and in/out counting (from the notebook)
    yolov8s.pt      Model weights
    static/         index.html, style.css, script.js

## API
    POST /api/process   multipart: video, direction, position (0.05-0.95), invert
                        -> {"job_id": "..."}
    GET  /api/jobs/ID   -> {status, progress, result{entries, exits, occupancy, output_url}}
    GET  /api/health

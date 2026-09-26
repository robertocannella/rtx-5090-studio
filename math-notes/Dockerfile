# One image, two services (see compose.yaml: math-notes runs public_app, math-notes-api
# runs admin_app) -- both are plain FastAPI apps now, dynamically querying a shared
# SQLite database (db.py) on every request, rather than a build-time static site.
FROM python:3.12-slim
WORKDIR /app
COPY src/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./
CMD ["uvicorn", "public_app:app", "--host", "0.0.0.0", "--port", "8000"]

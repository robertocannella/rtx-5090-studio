FROM python:3.12-slim

WORKDIR /app

# Standard library only -- no requirements to install.
COPY src/ ./

ENTRYPOINT ["python3", "sync.py"]

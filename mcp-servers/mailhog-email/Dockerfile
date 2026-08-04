FROM python:3.12-slim

WORKDIR /app
COPY server.py .

# No pip installs - server.py uses only the Python standard library.
CMD ["python", "server.py"]

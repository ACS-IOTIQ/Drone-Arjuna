FROM python:3.11-slim
RUN pip install --no-cache-dir pyserial
WORKDIR /app
COPY com_bridge.py .
CMD ["python", "-u", "com_bridge.py", "auto", "115200", "5762"]

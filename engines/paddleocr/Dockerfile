FROM python:3.10-slim
RUN apt-get update && apt-get install -y libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir paddlepaddle && pip install --no-cache-dir paddleocr fastapi uvicorn python-multipart Pillow
COPY main.py .
HEALTHCHECK --interval=60s --timeout=30s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

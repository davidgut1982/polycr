FROM python:3.10-slim
RUN apt-get update && apt-get install -y libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV DOCTR_CACHE_DIR=/models
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
VOLUME ["/models"]
HEALTHCHECK --interval=60s --timeout=30s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM ubuntu:22.04
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-eng python3 python3-pip && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY main.py .
HEALTHCHECK --interval=30s --timeout=10s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

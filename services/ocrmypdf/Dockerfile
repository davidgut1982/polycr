FROM python:3.11-slim
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-lav \
    ghostscript \
    unpaper \
    pngquant \
    && pip install ocrmypdf fastapi uvicorn python-multipart \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server.py .
EXPOSE 8001
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]

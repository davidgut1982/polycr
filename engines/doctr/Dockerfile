FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip libgomp1 libglib2.0-0 libgl1 \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip3 install --no-cache-dir \
    torch==2.1.0+cu121 torchvision==0.16.0+cu121 \
    --index-url https://download.pytorch.org/whl/cu121

RUN pip3 install --no-cache-dir \
    python-doctr[torch]==0.8.1 \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    python-multipart==0.0.6

ENV DOCTR_CACHE_DIR=/app/models
RUN python3 -c "\
from doctr.models import ocr_predictor; \
model = ocr_predictor(det_arch='db_resnet50', reco_arch='crnn_vgg16_bn', pretrained=True); \
print('docTR models cached')"

COPY main.py /app/main.py

EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

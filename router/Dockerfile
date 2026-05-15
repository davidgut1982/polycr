FROM 192.168.1.4:5000/polycr-router:latest

RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir docaligner-docsaid onnxruntime

RUN ln -sf /usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf /usr/local/lib/python3.10/site-packages/capybara/vision/visualization/NotoSansMonoCJKtc-VF.ttf

RUN python3 -c "from capybara.vision.visualization.draw import draw_box; print('capybara verify OK')"

COPY main.py /app/main.py

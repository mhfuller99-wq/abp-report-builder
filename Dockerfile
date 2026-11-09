FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt && useradd -r -u 10001 abp
# Process start imports every abp_*.py module. Copy the set so a new module is not left out.
COPY abp_*.py .
COPY abp_ui.js .
COPY 03_Workbooks_and_Master_Templates/ 03_Workbooks_and_Master_Templates/
COPY 04_Company_Branding/ 04_Company_Branding/
RUN mkdir -p /var/tmp/abp && chown abp /var/tmp/abp && chmod 700 /var/tmp/abp
ENV ABP_SCAN_TMPDIR=/var/tmp/abp
USER abp
EXPOSE 10000
CMD ["sh", "-c", "exec python abp_server.py ${PORT:-10000} --lan"]

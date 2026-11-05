FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -r -u 10001 abp
COPY abp_server.py .
COPY abp_reference.py .
COPY abp_design.py .
COPY abp_job.py .
COPY abp_ui.js .
COPY 03_Workbooks_and_Master_Templates/ 03_Workbooks_and_Master_Templates/
COPY 04_Company_Branding/ 04_Company_Branding/
USER abp
EXPOSE 10000
CMD ["sh", "-c", "exec python abp_server.py ${PORT:-10000} --lan"]

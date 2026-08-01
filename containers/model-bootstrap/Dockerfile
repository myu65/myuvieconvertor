FROM python:3.12-slim
WORKDIR /app
COPY containers/model-bootstrap/bootstrap_models.py /app/bootstrap_models.py
RUN pip install --no-cache-dir huggingface-hub==0.34.3 PyYAML==6.0.2
ENV HF_HOME=/scratch/huggingface HF_HUB_DISABLE_XET=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/app/bootstrap_models.py"]

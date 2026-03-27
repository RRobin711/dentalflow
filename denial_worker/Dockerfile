FROM python:3.12-slim

WORKDIR /app

COPY denial_worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/
COPY denial_worker/main.py /app/main.py
COPY ml/model.joblib /app/ml/model.joblib

CMD ["python", "main.py"]

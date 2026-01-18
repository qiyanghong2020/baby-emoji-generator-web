FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend

ENV PYTHONUNBUFFERED=1 \
    GENERATED_DIR=/app/backend/generated \
    FONT_PATH=/app/backend/assets/fonts/NotoSansSC-Regular.otf \
    FRONTEND_DIR=/app/frontend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]


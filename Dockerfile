FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir '.[production]' && mkdir -p /app/data
COPY data ./data
EXPOSE 8000
CMD ["uvicorn", "aegis_rag.api:app", "--host", "0.0.0.0", "--port", "8000"]

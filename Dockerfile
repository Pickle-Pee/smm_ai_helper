FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --upgrade pip

COPY pyproject.toml ./
RUN pip install "poetry==1.8.3"
RUN poetry config virtualenvs.create false

COPY . .
RUN poetry install --no-dev

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

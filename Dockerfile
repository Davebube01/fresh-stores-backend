FROM python:3.12-slim

WORKDIR /app

# build-essential + libpq-dev: needed to build psycopg2 / bcrypt / cryptography wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p uploads

EXPOSE 8000

CMD ["python", "main.py"]

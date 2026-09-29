FROM python:3.12-slim

WORKDIR /app

# build-essential + libpq-dev: needed to build psycopg2 / bcrypt / cryptography wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

COPY . .

RUN mkdir -p uploads

EXPOSE 8000

# Bring the schema up to date first (creates it on an empty database).
CMD ["sh", "-c", "python -m app.db_migrate && python main.py"]

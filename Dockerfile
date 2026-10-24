FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt psycopg[binary]==3.2.9

COPY . .
RUN mkdir -p data staticfiles && DJANGO_DEBUG=1 python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn lowbid.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 4"]

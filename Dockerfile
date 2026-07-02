# Image de base Python 3.11 légère
FROM python:3.11-slim

# Variables d'environnement pour Python
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Répertoire de travail
WORKDIR /app

# Installation des dépendances système nécessaires (ex: psycopg2)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Installation des dépendances Python
COPY requirements.txt /app/
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copie du code source
COPY . /app/

# Collecte des fichiers statiques (WhiteNoise s'en chargera via Nginx/Gunicorn)
# RUN python manage.py collectstatic --noinput

# Le port d'écoute de Gunicorn
EXPOSE 8000

# Lancement avec Gunicorn (par défaut, surchargeable via docker-compose)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "wagan_project.wsgi:application"]

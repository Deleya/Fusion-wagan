"""
WSGI config for wagan_project project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wagan_project.settings.local')

application = get_wsgi_application()

# Préchauffage : force l'import de toutes les URLs et vues dès le démarrage
# (combiné à gunicorn --preload). Sans ça, Django ne charge les vues qu'au
# PREMIER appel HTTP (~20s d'imports lourds), ce qui faisait échouer la
# vérification du webhook Meta (timeout côté Facebook, erreur 499 nginx).
from django.urls import get_resolver
get_resolver().url_patterns

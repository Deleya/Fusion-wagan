from .base import *
import dj_database_url

DEBUG = False
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",")

# Strict DB for Prod (Postgres)
DATABASES = {
    'default': dj_database_url.parse(os.getenv('DATABASE', 'postgres://user:pass@localhost/db'))
}

CORS_ALLOW_CREDENTIALS = True
cors_env = os.getenv("CORS_ALLOWED_ORIGINS", "")
if cors_env:
    CORS_ALLOWED_ORIGINS = cors_env.split(",")
else:
    CORS_ALLOWED_ORIGINS = []

# Cookies sécurisés uniquement si le serveur tourne en HTTPS (vrai déploiement).
# En démo Docker locale (HTTP), on désactive pour ne pas bloquer la connexion.
# En prod réelle : ajouter HTTPS_ENABLED=true dans les variables d'env du serveur.
_https_enabled = os.getenv("HTTPS_ENABLED", "false").lower() == "true"
SESSION_COOKIE_SAMESITE = "None"
SESSION_COOKIE_SECURE = _https_enabled
CSRF_COOKIE_SAMESITE = "None"
CSRF_COOKIE_SECURE = _https_enabled

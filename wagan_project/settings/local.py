from .base import *

DEBUG = True
ALLOWED_HOSTS = ["*"]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Allow CORS for dev frontend
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = True # Simplified for pure dev

SESSION_COOKIE_SAMESITE = "None"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SAMESITE = "None"
CSRF_COOKIE_SECURE = False

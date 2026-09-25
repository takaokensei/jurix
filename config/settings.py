"""
Django settings for Jurix project.
"""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

if not os.getenv('DJANGO_SKIP_DOTENV'):
    load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean from the environment ('1', 'true', 'yes', 'on', any case)."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


# Secure by default: DEBUG must be enabled explicitly (docker-compose and
# .env.example do it for local development). A forgotten variable used to mean
# DEBUG=True with ALLOWED_HOSTS=['*'] and a publicly known SECRET_KEY.
DEBUG = env_bool('DEBUG', False)

_DEV_SECRET_KEY = 'django-insecure-dev-key-change-in-production'
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY') or (_DEV_SECRET_KEY if DEBUG else None)
if not SECRET_KEY or (SECRET_KEY == _DEV_SECRET_KEY and not DEBUG):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is not set (or is the public development key). "
        "Set a private DJANGO_SECRET_KEY, or DEBUG=True for local development only."
    )


allowed_hosts_env = os.getenv('ALLOWED_HOSTS')
ALLOWED_HOSTS = [h.strip() for h in allowed_hosts_env.split(',') if h.strip()] if allowed_hosts_env else ['*'] if DEBUG else ['localhost', '127.0.0.1']


# HTTPS hardening. Secure cookies default to ON whenever DEBUG is off, and each
# switch can be overridden for deployments that still serve plain HTTP.
# CSRF_COOKIE_HTTPONLY must stay False: chat.js reads the csrftoken cookie to send
# X-CSRFToken. HSTS and the HTTPS redirect are opt-in because both are sticky.
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_HTTPONLY = False  # required: chat.js reads this cookie (do not change)
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', False)
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', False)
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]
if env_bool('TRUST_X_FORWARDED_PROTO', False):
    # Only enable behind a proxy that overwrites X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third Party
    'django_htmx',

    # Local Apps
    'src.apps.core',
    'src.apps.legislation',
    'src.apps.ingestion',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'config.middleware.ContentSecurityPolicyMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

database_url = os.getenv('DATABASE_URL', '')
use_sqlite = os.getenv('USE_SQLITE', 'False').lower() in ('1', 'true', 'yes')

if use_sqlite or database_url.startswith('sqlite'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
elif database_url:
    parsed_db = urlparse(database_url)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': unquote(parsed_db.path.lstrip('/')) or os.getenv('POSTGRES_DB', 'jurix'),
            'USER': unquote(parsed_db.username or '') or os.getenv('POSTGRES_USER', 'jurix_user'),
            'PASSWORD': unquote(parsed_db.password or '') or os.getenv('POSTGRES_PASSWORD', 'jurix_pass_dev'),
            'HOST': parsed_db.hostname or os.getenv('DB_HOST', 'db'),
            'PORT': str(parsed_db.port or os.getenv('DB_PORT', '5432')),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('POSTGRES_DB', 'jurix'),
            'USER': os.getenv('POSTGRES_USER', 'jurix_user'),
            'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'jurix_pass_dev'),
            'HOST': os.getenv('DB_HOST', 'db'),
            'PORT': os.getenv('DB_PORT', '5432'),
        }
    }


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'pt-br'

TIME_ZONE = 'America/Fortaleza'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'src' / 'apps' / 'core' / 'static',
]

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Celery Configuration
CELERY_BROKER_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.getenv('REDIS_URL', 'redis://redis:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    'expire-chat-attachments': {
        'task': 'ingestion.cleanup_chat_attachments',
        'schedule': 1800.0,
    },
}

# Cache Configuration (Redis with LocMem fallback for local development)
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
CACHE_REDIS_URL = os.getenv(
    'CACHE_REDIS_URL',
    REDIS_URL.rsplit('/', 1)[0] + '/1' if REDIS_URL.rsplit('/', 1)[-1] == '0' else REDIS_URL,
)
USE_LOCMEM_CACHE = os.getenv('USE_LOCMEM_CACHE', 'False').lower() in ('1', 'true', 'yes')

if USE_LOCMEM_CACHE or use_sqlite or REDIS_URL in ('locmem', 'locmem://', ''):
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'jurix-local-cache',
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': CACHE_REDIS_URL,
        }
    }



# Ollama Configuration
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3')
OLLAMA_EMBEDDING_MODEL = os.getenv('OLLAMA_EMBEDDING_MODEL', 'nomic-embed-text')

# Models a client may request. The default (OLLAMA_MODEL) is always allowed;
# add more with a comma-separated OLLAMA_ALLOWED_MODELS.
OLLAMA_ALLOWED_MODELS = sorted({
    OLLAMA_MODEL,
    *(m.strip() for m in os.getenv('OLLAMA_ALLOWED_MODELS', '').split(',') if m.strip()),
})

# Limits for LLM-backed endpoints (each request costs an embedding + a generation).
LLM_MAX_K = int(os.getenv('LLM_MAX_K', '20'))
LLM_MAX_QUESTION_LENGTH = int(os.getenv('LLM_MAX_QUESTION_LENGTH', '2000'))
LLM_RATE_LIMIT_REQUESTS = int(os.getenv('LLM_RATE_LIMIT_REQUESTS', '20'))  # 0 disables
LLM_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv('LLM_RATE_LIMIT_WINDOW_SECONDS', '60'))

# Reverse proxies in front of the app (0 = use REMOTE_ADDR). Behind one nginx/ALB
# set 1; otherwise every visitor appears to share the proxy's IP and one rate-limit
# bucket.
NUM_PROXIES = int(os.getenv('NUM_PROXIES', '0'))

# SAPL Configuration
SAPL_BASE_URL = os.getenv('SAPL_BASE_URL', 'https://sapl.natal.rn.leg.br/api')


# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': os.getenv('JURIX_LOG_FILE', str(BASE_DIR / 'data' / 'logs' / 'jurix.log')),
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'src': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}


# Data directories
DATA_DIR = BASE_DIR / 'data'
RAW_DATA_DIR = DATA_DIR / 'raw'
LOGS_DIR = DATA_DIR / 'logs'

for directory in [DATA_DIR, RAW_DATA_DIR, LOGS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)


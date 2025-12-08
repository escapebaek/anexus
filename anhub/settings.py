from pathlib import Path
import os
from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

ALLOWED_HOSTS = ['.vercel.app', 'www.anexus.cloud', 'anexus.cloud', '127.0.0.1']

# Application definition
INSTALLED_APPS = [
    # my apps
    'land.apps.LandConfig',
    'coag.apps.CoagConfig',
    'board.apps.BoardConfig',
    'accounts.apps.AccountsConfig',
    'exam.apps.ExamConfig',
    'drugdictionary.apps.DrugdictionaryConfig',
    'schedule.apps.ScheduleConfig',
    'record.apps.RecordConfig',
    # django default
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # backend
    'storages',
    # ckeditor
    'ckeditor',
    'ckeditor_uploader',
    # chat setting for django
    'channels',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'anhub.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],  # 프로젝트 템플릿 디렉토리 설정
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

WSGI_APPLICATION = 'anhub.wsgi.application'

# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'HOST': config('DB_HOST'),
        'PASSWORD': config('DB_PASSWORD'),
        'PORT': config('DB_PORT'),
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

# Privelleges for accounts
AUTH_USER_MODEL = 'accounts.CustomUser'

# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/
LANGUAGE_CODE = 'en-us'

# Set the time zone to Korean Standard Time (KST)
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')  # collectstatic 시 파일이 모일 곳
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),  # 프로젝트 루트의 static 폴더 추가
    os.path.join(BASE_DIR, 'schedule', 'static'),  # schedule 앱의 static 폴더
]
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

############################################################################
# Media files, Media 설정
# MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
DEFAULT_FILE_STORAGE = 'anhub.storage_backends.SupabaseStorage'

# Supabase 설정
SUPABASE_URL = config('SUPABASE_URL')
SUPABASE_KEY = config('SUPABASE_KEY')
SUPABASE_JWT_SECRET = config('SUPABASE_JWT_SECRET')
SUPABASE_STORAGE_BUCKET = config('SUPABASE_STORAGE_BUCKET')

# Supabase - media storage
MEDIA_URL = f'{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/'

############################################################################
# CKEditor
CKEDITOR_UPLOAD_PATH = "uploads/"
CKEDITOR_CONFIGS = {
    'default': {
        'toolbar': 'full',
        'height': 300,
        'width': '100%',
        'toolbar_Custom': [
            ['Bold', 'Italic', 'Underline'],
            ['NumberedList', 'BulletedList'],
            ['Link', 'Unlink'],
            ['RemoveFormat', 'Source']
        ],
    },
}

############################################################################
LOGOUT_REDIRECT_URL = '/'

# for password change e-mail
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# 세션 만료 시간 설정 (예: 30분)
SESSION_COOKIE_AGE = 1800  # 30분(1800초) 후에 세션 만료
SESSION_SAVE_EVERY_REQUEST = True  # 각 요청마다 세션의 만료 시간을 갱신

# 브라우저 닫을 때 세션 삭제
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# 로그인 페이지 설정
LOGIN_URL = '/login/'

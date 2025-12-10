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
    'anhub.middleware.RemoveGoogleAdSenseMiddleware',
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

############################################################################
# Security Settings (프로덕션 보안 설정)
############################################################################

# XSS 방지 - 브라우저의 XSS 필터 활성화
SECURE_BROWSER_XSS_FILTER = True

# Content-Type 스니핑 방지
SECURE_CONTENT_TYPE_NOSNIFF = True

# Clickjacking 방지 - iframe 임베딩 차단
X_FRAME_OPTIONS = 'DENY'

# HTTPS 관련 설정
# 주의: Vercel은 자체적으로 HTTPS를 처리하므로 SECURE_SSL_REDIRECT를 True로 설정하면
# 무한 리디렉션 루프가 발생할 수 있습니다. Vercel에서는 False로 유지합니다.
SECURE_SSL_REDIRECT = False

# 프록시 뒤에서 HTTPS 감지 (Vercel/로드밸런서 환경용)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# HTTPS에서만 세션 쿠키 전송 (프로덕션에서 보안 강화)
SESSION_COOKIE_SECURE = True

# HTTPS에서만 CSRF 쿠키 전송
CSRF_COOKIE_SECURE = True

# HSTS (HTTP Strict Transport Security) - 브라우저가 HTTPS만 사용하도록 강제
# Vercel은 자체 HSTS를 설정하므로 Django에서는 짧은 시간으로 설정
SECURE_HSTS_SECONDS = 3600  # 1시간 (Vercel이 이미 HSTS 처리)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False  # Vercel 환경에서는 비활성화 권장

# CSRF 신뢰 도메인 설정 (Vercel 배포용)
CSRF_TRUSTED_ORIGINS = [
    'https://*.vercel.app',
    'https://www.anexus.cloud',
    'https://anexus.cloud',
]

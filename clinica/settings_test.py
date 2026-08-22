"""
Settings usadas SOLO durante la ejecución de pruebas (local y en Jenkins).

Hereda todo de `clinica.settings` (incluida la conexión MySQL, tomada de
variables de entorno vía python-decouple). No se usa SQLite porque la
migración `accounts/0002_traducir_tablas_django.py` ejecuta SQL crudo
específico de MySQL (`RENAME TABLE ...`) y no correría en otro motor.

En Jenkins, las variables DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD deben
apuntar a un MySQL desechable levantado solo para la build (ver Jenkinsfile).
Django crea y destruye automáticamente una base `test_<DB_NAME>` en cada
corrida, así que no toca la base de datos real del proyecto.
"""

from .settings import *  # noqa: F401,F403

DEBUG = False

# Hasher de contraseñas más rápido: las pruebas no necesitan seguridad real.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Los archivos subidos durante las pruebas (imágenes de estudio, informes)
# se guardan en una carpeta temporal separada de `media/` para no ensuciar
# el proyecto real ni el workspace de Jenkins entre builds.
MEDIA_ROOT = BASE_DIR / 'media_test'  # noqa: F405 (definida en settings.py)

EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

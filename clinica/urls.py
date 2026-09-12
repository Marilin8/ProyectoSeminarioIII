"""
URL configuration for clinica project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from decouple import config
from django.conf import settings
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve as servir_archivo_media

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('accounts.urls')),
    path('', include('pacientes.urls')),
]

# El helper static() de Django trae un candado interno: no agrega nada si
# DEBUG=False, sin importar cómo se lo envuelva. Por eso, al poner
# DEBUG=False para exponer esto a internet, /media/... empezó a dar 404 y
# las imágenes de estudios y los informes en PDF dejaron de verse (los
# archivos siguen en disco, solo dejaron de servirse). Esta instalación no
# tiene Nginx delante de Waitress, así que se sirve con la vista real
# (serve) en vez del wrapper static(). Confirmado con el usuario: sin
# control de acceso adicional, igual que en desarrollo — cualquiera con la
# URL exacta puede ver el archivo. Se activa con SERVIR_MEDIA=True en el
# .env, a propósito, en vez de quedar prendido siempre.
if settings.DEBUG or config('SERVIR_MEDIA', default=False, cast=bool):
    urlpatterns += [
        re_path(
            r'^%s(?P<path>.*)$' % settings.MEDIA_URL.lstrip('/'),
            servir_archivo_media,
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]

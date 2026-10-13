"""Admin de Django (/admin/) protegido con la verificación en dos pasos.

El admin trae su propio login, que solo pide usuario y contraseña: con él,
quien robara la contraseña de un superusuario entraba sin el código OTP.
Este sitio no tiene login propio (manda al login de la clínica, que sí pide
el código) y solo deja pasar a una sesión que verificó el código OTP
(`request.user.is_verified()`, de django_otp). Además hace falta is_staff:
hoy solo lo tiene la cuenta del administrador de TI."""

from django.contrib import admin
from django.contrib.admin.apps import AdminConfig
from django.shortcuts import redirect


class AdminSiteConMFA(admin.AdminSite):

    def has_permission(self, request):
        return super().has_permission(request) and request.user.is_verified()

    def login(self, request, extra_context=None):
        return redirect('login')


class AdminConMFAConfig(AdminConfig):
    default_site = 'clinica.admin_site.AdminSiteConMFA'

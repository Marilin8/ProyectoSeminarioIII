"""Límite de intentos fallidos de inicio de sesión y de código MFA.

Cuenta solo los FALLOS (no los accesos correctos): en la clínica todo el
personal sale por la misma IP pública, así que limitar todas las peticiones
por IP bloquearía a todos a la vez. Se limita por (IP, usuario) y, con un tope
más alto, por IP sola. Los contadores viven en la caché de Django (en memoria
del servidor): se reinician si se reinicia Waitress, lo cual es aceptable
para frenar fuerza bruta.
"""
import hashlib
import math
import threading
import time

from django.core.cache import cache

_candado = threading.Lock()


class LimiteIntentos:
    def __init__(self, nombre, maximo, ventana_segundos):
        self.nombre = nombre
        self.maximo = maximo
        self.ventana = ventana_segundos

    def _clave(self, partes, sufijo=''):
        huella = hashlib.sha256('|'.join(str(p) for p in partes).encode('utf-8')).hexdigest()[:32]
        return f'limite:{self.nombre}{sufijo}:{huella}'

    def espera(self, *partes):
        """Segundos que faltan para poder reintentar (0 si no está bloqueado)."""
        estado = cache.get(self._clave(partes))
        if not estado or estado['n'] < self.maximo:
            return 0
        return max(0, math.ceil(estado['inicio'] + self.ventana - time.time()))

    def fallo(self, *partes):
        clave = self._clave(partes)
        ahora = time.time()
        with _candado:
            estado = cache.get(clave)
            if not estado or ahora >= estado['inicio'] + self.ventana:
                estado = {'n': 0, 'inicio': ahora}
            estado['n'] += 1
            cache.set(clave, estado, self.ventana)
        return estado['n']

    def limpiar(self, *partes):
        cache.delete(self._clave(partes))

    def primera_vez(self, *partes):
        """True solo la primera vez dentro de la ventana (para registrar el
        bloqueo una vez en la bitácora y no inundarla)."""
        return cache.add(self._clave(partes, ':aviso'), 1, self.ventana)


MINUTOS = 10
LOGIN_USUARIO = LimiteIntentos('login_usuario', 5, MINUTOS * 60)
LOGIN_IP = LimiteIntentos('login_ip', 30, MINUTOS * 60)
CODIGO_MFA = LimiteIntentos('codigo_mfa', 5, MINUTOS * 60)


def espera_login(ip, usuario):
    return max(LOGIN_USUARIO.espera(ip, usuario), LOGIN_IP.espera(ip))


def fallo_login(ip, usuario):
    LOGIN_USUARIO.fallo(ip, usuario)
    LOGIN_IP.fallo(ip)


def exito_login(ip, usuario):
    LOGIN_USUARIO.limpiar(ip, usuario)


def minutos_de_espera(segundos):
    return max(1, math.ceil(segundos / 60))

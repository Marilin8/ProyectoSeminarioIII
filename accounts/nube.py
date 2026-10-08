"""Subida de respaldos a Google Drive con OAuth de usuario.

Solo pedimos el alcance `drive.file`: la aplicación únicamente ve los archivos
y carpetas que ella misma crea, nunca el resto del Drive de la cuenta. No
dependemos de librerías de Google: hablamos con la API por HTTPS estándar.
"""
import base64
import hashlib
import http.client
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlencode, urlsplit

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.urls import reverse

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
DRIVE_URL = 'https://www.googleapis.com/drive/v3'
UPLOAD_HOST = 'www.googleapis.com'
SCOPE = 'https://www.googleapis.com/auth/drive.file'
NOMBRE_CARPETA = 'Respaldos Clinica'
TIMEOUT_SEGUNDOS = 30
TIMEOUT_SUBIDA_SEGUNDOS = 1800


class ErrorNube(Exception):
    pass


def _fernet():
    # La clave deriva de SECRET_KEY, que vive en el .env y NO viaja dentro de
    # los respaldos: así el token guardado en la base no sirve a quien robe
    # solo un respaldo.
    clave = hashlib.sha256(f'google-drive:{settings.SECRET_KEY}'.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(clave))


def cifrar(texto):
    return _fernet().encrypt(texto.encode()).decode()


def descifrar(cifrado):
    try:
        return _fernet().decrypt(cifrado.encode()).decode()
    except InvalidToken:
        raise ErrorNube(
            'No se pudieron descifrar las credenciales guardadas (cambió la SECRET_KEY). '
            'Desconecte y vuelva a conectar Google Drive.'
        )


def uri_de_redireccion():
    return settings.VISOR_BASE_URL + reverse('google_drive_callback')


def nuevo_estado():
    return secrets.token_urlsafe(32)


def url_de_autorizacion(client_id, estado):
    return AUTH_URL + '?' + urlencode({
        'client_id': client_id,
        'redirect_uri': uri_de_redireccion(),
        'response_type': 'code',
        'scope': SCOPE,
        'access_type': 'offline',
        # Sin "consent" Google no devuelve refresh_token si la cuenta ya
        # había autorizado antes la aplicación.
        'prompt': 'consent',
        'state': estado,
    })


def _pedir_json(url, datos=None, token=None, metodo=None):
    cabeceras = {}
    cuerpo = None
    if datos is not None:
        if token:
            cuerpo = json.dumps(datos).encode()
            cabeceras['Content-Type'] = 'application/json'
        else:
            cuerpo = urlencode(datos).encode()
            cabeceras['Content-Type'] = 'application/x-www-form-urlencoded'
    if token:
        cabeceras['Authorization'] = f'Bearer {token}'
    peticion = urllib.request.Request(url, data=cuerpo, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_SEGUNDOS) as respuesta:
            contenido = respuesta.read()
    except urllib.error.HTTPError as error:
        raise ErrorNube(_mensaje_de_error(error.read(), error.code))
    except (urllib.error.URLError, OSError) as error:
        raise ErrorNube(f'no se pudo conectar con Google ({getattr(error, "reason", error)})')
    return json.loads(contenido) if contenido else {}


def _mensaje_de_error(contenido, codigo):
    try:
        datos = json.loads(contenido)
    except ValueError:
        return f'Google respondió con el error {codigo}'
    error = datos.get('error')
    if isinstance(error, dict):
        return error.get('message') or f'Google respondió con el error {codigo}'
    descripcion = datos.get('error_description')
    return f'{error}: {descripcion}' if descripcion else (error or f'Google respondió con el error {codigo}')


def canjear_codigo(client_id, client_secret, codigo):
    """Cambia el código que devuelve Google por un refresh token."""
    datos = _pedir_json(TOKEN_URL, {
        'code': codigo,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': uri_de_redireccion(),
        'grant_type': 'authorization_code',
    })
    if not datos.get('refresh_token'):
        raise ErrorNube(
            'Google no entregó un refresh token. Revoque el acceso de la aplicación en '
            'myaccount.google.com/permissions y vuelva a conectar.'
        )
    return datos['refresh_token']


def token_de_acceso(client_id, client_secret, refresh_token):
    datos = _pedir_json(TOKEN_URL, {
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
    })
    return datos['access_token']


def correo_de_la_cuenta(token):
    datos = _pedir_json(DRIVE_URL + '/about?fields=user(emailAddress)', token=token)
    return datos.get('user', {}).get('emailAddress', '')


def crear_carpeta(token, nombre=NOMBRE_CARPETA):
    datos = _pedir_json(DRIVE_URL + '/files?fields=id', {
        'name': nombre,
        'mimeType': 'application/vnd.google-apps.folder',
    }, token=token)
    return datos['id']


def subir_archivo(token, ruta, carpeta_id):
    """Sube un archivo a la carpeta con una subida reanudable de una sola
    petición (el archivo se transmite desde disco, sin cargarlo en memoria).
    Devuelve el id del archivo en Drive."""
    inicio = _pedir_json_con_cabeceras(
        'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id',
        {'name': ruta.name, 'parents': [carpeta_id]},
        token,
    )
    destino = urlsplit(inicio)
    conexion = http.client.HTTPSConnection(destino.netloc, timeout=TIMEOUT_SUBIDA_SEGUNDOS)
    try:
        with open(ruta, 'rb') as archivo:
            conexion.request(
                'PUT', destino.path + '?' + destino.query, body=archivo,
                headers={
                    'Content-Length': str(ruta.stat().st_size),
                    'Content-Type': 'application/octet-stream',
                },
            )
            respuesta = conexion.getresponse()
            contenido = respuesta.read()
    except OSError as error:
        raise ErrorNube(f'se interrumpió la subida a Google Drive ({error})')
    finally:
        conexion.close()
    if respuesta.status not in (200, 201):
        raise ErrorNube(_mensaje_de_error(contenido, respuesta.status))
    return json.loads(contenido)['id']


def _pedir_json_con_cabeceras(url, datos, token):
    """Inicia la subida reanudable; la URL de subida viene en la cabecera Location."""
    peticion = urllib.request.Request(
        url, data=json.dumps(datos).encode(), method='POST',
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json; charset=UTF-8'},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_SEGUNDOS) as respuesta:
            ubicacion = respuesta.headers.get('Location')
    except urllib.error.HTTPError as error:
        raise ErrorNube(_mensaje_de_error(error.read(), error.code))
    except (urllib.error.URLError, OSError) as error:
        raise ErrorNube(f'no se pudo conectar con Google ({getattr(error, "reason", error)})')
    if not ubicacion:
        raise ErrorNube('Google no entregó la dirección de subida.')
    return ubicacion


def revocar(token):
    try:
        url = TOKEN_URL.replace('/token', '/revoke') + '?' + urlencode({'token': token})
        _pedir_json(url, datos={}, metodo='POST')
    except ErrorNube:
        pass

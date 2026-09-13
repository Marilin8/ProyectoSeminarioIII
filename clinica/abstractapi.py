"""Verificación de correos "existentes de verdad" vía la Email Verification
API de AbstractAPI (https://www.abstractapi.com/api/email-verification-validation-api).

No reemplaza a `validar_dominio_correo` (clinica/validators.py): esa sigue
corriendo primero porque es gratis y no depende de la red — descarta
formato inválido y desechables conocidos antes de gastar una consulta a la
API. Esto se usa para el paso más caro: preguntarle a AbstractAPI si el
buzón existe de verdad (o si seguro no existe).

Requiere ABSTRACT_API_KEY en el .env (capa gratis: 100 verificaciones/mes,
sin tarjeta). Si no está configurada, todo esto se comporta como si no
existiera (ver validar_correo_existente en clinica/validators.py) — nunca
bloquea un formulario por faltar la key.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

ABSTRACT_API_URL = 'https://emailvalidation.abstractapi.com/v1/'

# Valores que AbstractAPI puede devolver en 'deliverability':
#   DELIVERABLE   -> el buzón existe, se puede confiar en el correo.
#   UNDELIVERABLE -> el buzón no existe o el dominio no recibe correo.
#   RISKY         -> el dominio acepta cualquier correo (catch-all), es una
#                     casilla de rol (info@, ventas@) o está marcado como
#                     desechable — AbstractAPI no puede confirmar ni
#                     descartar que exista.
#   UNKNOWN       -> no se pudo determinar (el servidor del destinatario no
#                     respondió a tiempo, greylisting, etc.).
# Solo 'UNDELIVERABLE' es una señal confiable de que el correo NO existe;
# los demás (incluido 'UNKNOWN') se dejan pasar para no rechazar correos
# válidos por falsos negativos.
RESULTADO_NO_EXISTE = 'UNDELIVERABLE'


class AbstractApiError(Exception):
    """La API de AbstractAPI no pudo consultarse (red, timeout, api key
    inválida, etc.). No significa que el correo sea inválido: quien llama
    decide si eso bloquea el guardado o simplemente se deja pasar."""


def verificar_correo(correo, timeout=6):
    """Consulta la Email Verification API de AbstractAPI para `correo` y
    devuelve su respuesta (dict con 'deliverability', 'quality_score',
    'is_valid_format', 'is_free_email', 'is_disposable_email',
    'is_role_email', 'is_catchall_email', 'is_mx_found', 'is_smtp_valid',
    etc.). Lanza AbstractApiError si no se pudo consultar (sin API key,
    timeout, error de red, o la propia API respondiendo con un error)."""
    api_key = settings.ABSTRACT_API_KEY
    if not api_key:
        raise AbstractApiError('ABSTRACT_API_KEY no está configurada.')

    url = f'{ABSTRACT_API_URL}?' + urllib.parse.urlencode({'api_key': api_key, 'email': correo})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        # AbstractAPI manda el detalle del error en el body incluso con 4xx/5xx.
        try:
            cuerpo = json.loads(exc.read().decode('utf-8'))
            detalle = cuerpo.get('error', {}).get('message', str(cuerpo))
        except (ValueError, UnicodeDecodeError, AttributeError):
            detalle = str(exc)
        raise AbstractApiError(f'AbstractAPI respondió {exc.code}: {detalle}') from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise AbstractApiError(f'No se pudo consultar AbstractAPI: {exc}') from exc

    if 'error' in datos:
        raise AbstractApiError(f'AbstractAPI devolvió un error: {datos["error"]}')

    return datos

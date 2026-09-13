"""Verificación de correos "existentes de verdad" vía la Email Risk API de
Didit (https://docs.didit.me/identity-verification/email-verification/email-risk-api).

Se usa /v3/email/risk/, NO /v3/email/send/ — ese otro endpoint le manda un
código de un solo uso (OTP) al correo, pensado para un flujo de dos pasos
donde el usuario después escribe el código. Acá no hay esa pantalla
intermedia (esto corre en el clean_correo de un formulario normal), así
que se usa el endpoint que solo puntúa el riesgo del correo sin mandarle
nada.

No reemplaza a `validar_dominio_correo` (clinica/validators.py): esa sigue
corriendo primero porque es gratis y no depende de la red — descarta
formato inválido y desechables conocidos antes de gastar una consulta a la
API. Esto se usa para el paso más caro: preguntarle a Didit si el buzón
existe de verdad (o si seguro no existe).

Requiere DIDIT_API_KEY en el .env. Si no está configurada, todo esto se
comporta como si no existiera (ver validar_correo_existente en
clinica/validators.py) — nunca bloquea un formulario por faltar la key.
"""
import json
import urllib.error
import urllib.request

from django.conf import settings

DIDIT_RISK_URL = 'https://verification.didit.me/v3/email/risk/'


class DiditError(Exception):
    """La API de Didit no pudo consultarse (red, timeout, api key
    inválida, etc.). No significa que el correo sea inválido: quien llama
    decide si eso bloquea el guardado o simplemente se deja pasar."""


def verificar_correo(correo, timeout=6):
    """Consulta la Email Risk API de Didit para `correo` (sin mandarle
    ningún código, solo scoring) y devuelve el bloque 'email' de la
    respuesta: dict con 'is_undeliverable', 'is_disposable', 'is_breached',
    'email_intelligence', etc. Lanza DiditError si no se pudo consultar
    (sin API key, timeout, error de red, o una respuesta con forma rara)."""
    api_key = settings.DIDIT_API_KEY
    if not api_key:
        raise DiditError('DIDIT_API_KEY no está configurada.')

    cuerpo = json.dumps({'email': correo}).encode('utf-8')
    solicitud = urllib.request.Request(
        DIDIT_RISK_URL,
        data=cuerpo,
        method='POST',
        headers={'x-api-key': api_key, 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(solicitud, timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        # Didit manda el detalle del error en el body incluso con 4xx/5xx.
        try:
            detalle = json.loads(exc.read().decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            detalle = str(exc)
        raise DiditError(f'Didit respondió {exc.code}: {detalle}') from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise DiditError(f'No se pudo consultar Didit: {exc}') from exc

    email_info = datos.get('email')
    if not isinstance(email_info, dict):
        raise DiditError(f'Didit devolvió una respuesta inesperada: {datos}')

    return email_info

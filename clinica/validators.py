import re

from django.core.exceptions import ValidationError

from .abstractapi import AbstractApiError, RESULTADO_NO_EXISTE, verificar_correo

# Dominios de correo desechables / temporales conocidos. Si el dominio del
# correo figura acá, se rechaza. Validación determinista (sin DNS) que
# complementa la sintaxis base de EmailValidator.
DOMINIOS_DESECHABLES = {
    '10minutemail.com', 'mailinator.com', 'yopmail.com', 'guerrillamail.com',
    'sharklasers.com', 'tempmail.com', 'temp-mail.org', 'throwawaymail.com',
    'dispostable.com', 'mailcatch.com', 'spamgourmet.com', 'trashmail.com',
    'getnada.com', 'nada.email', 'mailnesia.com', 'maildrop.cc', 'fakeinbox.com',
    'mytemp.email', 'moakt.com', 'emailondeck.com', 'tempr.email',
}

_ETIQUETA_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9\-]{0,62}[A-Za-z0-9])?$')


def validar_dominio_correo(correo):
    """Valida estrictamente el dominio de un correo, sin depender de DNS:

    1. Debe tener un '@' y un dominio no vacío.
    2. El dominio debe ser sintácticamente válido (etiquetas alfanuméricas
       separadas por punto, TLD de al menos 2 letras).
    3. No debe estar en la lista de dominios desechables/temporales.

    Lanza ValidationError si no cumple. No hace nada si el correo viene vacío.
    """
    if not correo:
        return
    if '@' not in correo:
        raise ValidationError('El correo no tiene un formato válido.')

    dominio = correo.rsplit('@', 1)[1].strip().lower()
    if not dominio:
        raise ValidationError('El correo debe tener un dominio (lo que va después de @).')

    etiquetas = dominio.split('.')
    if len(etiquetas) < 2:
        raise ValidationError('El dominio del correo no es válido (le falta el punto).')

    tld = etiquetas[-1]
    if not (tld.isalpha() and len(tld) >= 2):
        raise ValidationError(
            'El dominio del correo debe terminar en una extensión válida (ej. .com, .gt).'
        )
    for etiqueta in etiquetas:
        if not _ETIQUETA_RE.match(etiqueta):
            raise ValidationError('El dominio del correo no es válido.')

    if dominio in DOMINIOS_DESECHABLES:
        raise ValidationError('No se permiten correos temporales o desechables.')


def validar_correo_existente(correo):
    """Confirma con AbstractAPI que el correo existe de verdad, además del
    chequeo gratis de validar_dominio_correo (que conviene correr primero
    en el mismo clean_correo, para no gastar una consulta a la API con algo
    que ya se sabe inválido).

    Solo rechaza cuando AbstractAPI devuelve deliverability='UNDELIVERABLE'
    (certeza de que el buzón no existe o el dominio no recibe correo).
    Cualquier otro caso se deja pasar sin bloquear el formulario:
    - 'DELIVERABLE' / 'RISKY' / 'UNKNOWN': AbstractAPI no dice que no exista.
    - Sin ABSTRACT_API_KEY configurada, timeout, o cualquier error de red:
      no tiene sentido tumbar el registro de un paciente/usuario porque la
      API externa esté caída o lenta.

    No hace nada si el correo viene vacío (igual que validar_dominio_correo).
    """
    if not correo:
        return
    try:
        resultado = verificar_correo(correo)
    except AbstractApiError:
        return

    if resultado.get('deliverability') == RESULTADO_NO_EXISTE:
        raise ValidationError(
            'Ese correo no existe o no puede recibir mensajes. Revisá que esté bien escrito.'
        )

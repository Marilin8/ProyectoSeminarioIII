import re

from django.core.exceptions import ValidationError

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

import re

from django.core.exceptions import ValidationError

from .didit import DiditError, verificar_correo

# Código propio en la ValidationError de validar_correo_existente, para que
# las vistas puedan distinguir "Didit dijo que no existe" de cualquier otro
# motivo de rechazo del campo correo (formato, desechable, etc.) sin tener
# que andar comparando el texto del mensaje. Ver avisar_si_correo_no_existe.
CODIGO_CORREO_NO_EXISTENTE = 'correo_no_existente'

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
    """Confirma con la Email Risk API de Didit que el correo existe de
    verdad, además del chequeo gratis de validar_dominio_correo (que
    conviene correr primero en el mismo clean_correo, para no gastar una
    consulta a la API con algo que ya se sabe inválido).

    Solo rechaza cuando Didit marca is_undeliverable=True (certeza de que
    el buzón no existe o el dominio no recibe correo). Cualquier otro caso
    se deja pasar sin bloquear el formulario:
    - is_undeliverable=False: Didit no dice que no exista (puede ser
      entregable, o el dato simplemente no estar disponible para ese
      dominio -- Didit documenta email_intelligence como "best effort").
    - Sin DIDIT_API_KEY configurada, timeout, o cualquier error de red: no
      tiene sentido tumbar el registro de un paciente/usuario porque la
      API externa esté caída o lenta.

    No hace nada si el correo viene vacío (igual que validar_dominio_correo).
    """
    if not correo:
        return
    try:
        info = verificar_correo(correo)
    except DiditError:
        return

    if info.get('is_undeliverable'):
        raise ValidationError(
            'Ese correo no existe o no puede recibir mensajes. Revisá que esté bien escrito.',
            code=CODIGO_CORREO_NO_EXISTENTE,
        )


def avisar_si_correo_no_existe(request, form, campo='correo'):
    """Si `form` quedó inválido porque validar_correo_existente rechazó
    `campo` (Didit confirmó que no existe), además del error que ya
    aparece bajo el campo, manda un mensaje más visible (banner arriba de
    la pantalla) para que no pase desapercibido.

    Se llama desde la vista, en el `else` de `if form.is_valid():` -- ahí
    es donde hay un `request` a mano para usar el framework de mensajes."""
    from django.contrib import messages

    errores = form.errors.as_data().get(campo, [])
    if any(error.code == CODIGO_CORREO_NO_EXISTENTE for error in errores):
        messages.warning(request, 'El correo ingresado no fue encontrado.')

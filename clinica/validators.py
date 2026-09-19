import re

import dns.exception
import dns.resolver
from django.conf import settings
from django.core.exceptions import ValidationError

# Código propio en la ValidationError de validar_correo_existente, para que
# las vistas puedan distinguir "el dominio no puede recibir correo" de
# cualquier otro motivo de rechazo del campo correo (formato, desechable,
# etc.) sin tener que andar comparando el texto del mensaje. Ver
# avisar_si_correo_no_existe.
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


_TIMEOUT_DNS = 5  # segundos


def dominio_puede_recibir_correo(dominio):
    """True si el dominio tiene un registro MX -- o, a falta de MX, al
    menos A/AAAA, que es la regla que manda RFC 5321 para cuando un
    dominio puede recibir correo sin un MX explícito (poco común, pero
    válido). False si el dominio no existe en DNS (NXDOMAIN) o ninguno de
    esos registros respondió.

    Puede propagar dns.exception.DNSException (timeout, servidor DNS
    caído, etc.) -- quien llama decide qué hacer con eso; acá no se
    confunde "no se pudo consultar" con "no existe"."""
    try:
        dns.resolver.resolve(dominio, 'MX', lifetime=_TIMEOUT_DNS)
        return True
    except dns.resolver.NXDOMAIN:
        return False
    except dns.resolver.NoAnswer:
        pass  # el dominio existe pero no tiene MX -- seguir con A/AAAA

    for tipo in ('A', 'AAAA'):
        try:
            dns.resolver.resolve(dominio, tipo, lifetime=_TIMEOUT_DNS)
            return True
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            continue
    return False


def validar_correo_existente(correo):
    """Confirma por DNS que el dominio del correo puede recibir correo de
    verdad (tiene MX o, a falta de eso, A/AAAA), sin depender de ningún
    servicio externo pago -- además del chequeo gratis de
    validar_dominio_correo (que conviene correr primero en el mismo
    clean_correo).

    Esto NO confirma que el buzón puntual (lo que va antes de la @) exista
    -- eso requeriría contactar al servidor de correo del destinatario
    (SMTP) o un servicio pago, y ni así es confiable con Gmail/Outlook
    (rechazan la mayoría de esos chequeos por antispam). Lo que sí atrapa,
    gratis y sin límite, es el error más común: un dominio inventado o mal
    escrito (ej. "gmial.com") o que ya no existe.

    Solo rechaza cuando el dominio no existe en DNS o no tiene ningún
    registro que le permita recibir correo. Cualquier error de DNS
    (timeout, servidor caído, red sin salida) se deja pasar sin bloquear
    el formulario -- no tiene sentido tumbar un registro porque la
    consulta DNS falló, no porque el dominio esté mal.

    No hace nada si el correo viene vacío (igual que validar_dominio_correo)
    o si VERIFICAR_CORREO_EXISTENTE está apagado en settings (así lo dejan
    las pruebas, para no depender de salir a internet).
    """
    if not correo or not settings.VERIFICAR_CORREO_EXISTENTE:
        return
    dominio = correo.rsplit('@', 1)[-1].strip().lower()
    if not dominio:
        return

    try:
        puede_recibir = dominio_puede_recibir_correo(dominio)
    except dns.exception.DNSException:
        return

    if not puede_recibir:
        raise ValidationError(
            'Ese correo no existe o su dominio no puede recibir mensajes. Revisá que esté bien escrito.',
            code=CODIGO_CORREO_NO_EXISTENTE,
        )


def avisar_si_correo_no_existe(request, form, campo='correo'):
    """Si `form` quedó inválido porque validar_correo_existente rechazó
    `campo` (el dominio no puede recibir correo), además del error que ya
    aparece bajo el campo, manda un mensaje más visible (banner arriba de
    la pantalla) para que no pase desapercibido.

    Se llama desde la vista, en el `else` de `if form.is_valid():` -- ahí
    es donde hay un `request` a mano para usar el framework de mensajes."""
    from django.contrib import messages

    errores = form.errors.as_data().get(campo, [])
    if any(error.code == CODIGO_CORREO_NO_EXISTENTE for error in errores):
        messages.warning(request, 'El correo ingresado no fue encontrado.')

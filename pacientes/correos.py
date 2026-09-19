import base64
import logging
import smtplib
import socket
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import EmailMessage
from django.urls import reverse

logger = logging.getLogger(__name__)


def enviar_resultados(orden):
    """Envía al correo del paciente el informe PDF adjunto + un link al visor
    web del estudio (donde ve las imágenes que dejó seleccionadas la
    radióloga). El visor pide los últimos 4 dígitos del DPI para abrirse.

    Devuelve '' si el correo se mandó, o un texto corto con el motivo del
    fallo (paciente sin correo, credenciales rechazadas, no se pudo conectar
    con el servidor de correo, etc.). Nunca deja que ese fallo tumbe la
    pantalla que lo llamó — siempre atrapa la excepción."""
    paciente = orden.cita.paciente

    if not paciente.correo:
        return 'el paciente no tiene un correo registrado'

    if not (settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD):
        return (
            'el sistema todavía no tiene configurado el correo emisor '
            '(EMAIL_HOST_USER / EMAIL_HOST_PASSWORD en el archivo .env)'
        )

    token = orden.asegurar_token_publico()
    ac = base64.urlsafe_b64encode(str(token).encode('ascii')).decode('ascii').rstrip('=')
    link_visor = (
        settings.VISOR_BASE_URL + reverse('visor_estudio')
        + '?' + urlencode({'studyId': orden.id, 'tab': 'images', 'ac': ac})
    )

    # Un combo (ver Cita.estudios) tiene un informe por cada estudio que lo
    # compone; un estudio normal tiene exactamente uno.
    informes_con_pdf = [i for i in orden.informes.all() if i.archivo]
    en_singular = len(informes_con_pdf) <= 1
    linea_informe = (
        'El informe médico va adjunto a este correo en formato PDF.' if en_singular
        else f'Los {len(informes_con_pdf)} informes médicos van adjuntos a este correo en formato PDF.'
    )

    asunto = 'Resultados de su estudio - Clínica de Imágenes'
    mensaje = f"""Estimado(a) {paciente.nombre} {paciente.apellido}:

Ya están disponibles los resultados de su estudio realizado en
Clínica de Imágenes.

Tipo de estudio: {orden.cita.tipo_estudio.nombre}
Fecha: {orden.cita.fecha:%d/%m/%Y}

Para ver las imágenes de su estudio, ingrese a este enlace:
{link_visor}

Se le pedirán los últimos 4 dígitos de su DPI para acceder.

{linea_informe}

Gracias por confiar en nosotros.

Atentamente,
Clínica de Imágenes
"""

    correo = EmailMessage(subject=asunto, body=mensaje, to=[paciente.correo])

    # Solo se adjuntan los informes en PDF. Las imágenes ya no se adjuntan:
    # se ven en el visor web a través del link.
    for informe in informes_con_pdf:
        correo.attach_file(informe.archivo.path)

    try:
        correo.send()
    except smtplib.SMTPAuthenticationError:
        logger.exception('SMTP rechazó las credenciales (orden #%s)', orden.id)
        return (
            'el servidor de correo rechazó el usuario o la contraseña '
            '(revisá EMAIL_HOST_USER / EMAIL_HOST_PASSWORD — Gmail necesita una '
            '"contraseña de aplicación")'
        )
    except (socket.timeout, TimeoutError, ConnectionError, OSError, smtplib.SMTPException):
        logger.exception('No se pudo conectar con el servidor de correo (orden #%s)', orden.id)
        return (
            'no se pudo conectar con el servidor de correo. Puede que la red '
            'bloquee la salida SMTP (puerto 587); probá desde otra red o pedile '
            'al administrador que configure el envío por un servicio de correo'
        )
    except Exception:
        logger.exception('Error inesperado enviando el correo de la orden #%s', orden.id)
        return 'ocurrió un error inesperado al enviar el correo (ver el registro del sistema)'

    return ''

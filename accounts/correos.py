import logging
import smtplib
import socket

from django.conf import settings
from django.core.mail import EmailMessage
from django.urls import reverse

logger = logging.getLogger(__name__)


def enviar_confirmacion_cuenta(request, usuario, token):
    """Manda al correo del usuario recién creado el link para confirmar que
    esa casilla es real y suya (ver accounts.views.crear_usuario /
    confirmar_correo_usuario). La cuenta queda inactiva hasta que entra ahí.

    Devuelve '' si el correo se mandó, o un texto corto con el motivo del
    fallo -- igual que pacientes.correos.enviar_resultados. Nunca deja que
    ese fallo tumbe la creación del usuario: si el correo no sale (ej. el
    conocido bloqueo de SMTP saliente en algunas redes), la cuenta queda
    igual creada pero inactiva, y un administrador puede activarla a mano
    desde "Usuarios activos" sin depender de este envío."""
    if not (settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD):
        return (
            'el sistema todavía no tiene configurado el correo emisor '
            '(EMAIL_HOST_USER / EMAIL_HOST_PASSWORD en el archivo .env)'
        )

    link = request.build_absolute_uri(
        reverse('confirmar_correo_usuario', args=[token]),
    )
    asunto = 'Confirmá tu cuenta - Clínica de Imágenes'
    mensaje = f"""Hola {usuario.first_name or usuario.username}:

Se creó una cuenta para vos en el sistema de la Clínica de Imágenes
(usuario: {usuario.username}).

Antes de poder ingresar, confirmá que este correo es tuyo entrando a
este enlace:
{link}

El enlace vence en {usuario.VIGENCIA_TOKEN_CONFIRMACION.days} días. Si
no reconocés esta cuenta, podés ignorar este correo.

Atentamente,
Clínica de Imágenes
"""
    correo = EmailMessage(subject=asunto, body=mensaje, to=[usuario.email])

    try:
        correo.send()
    except smtplib.SMTPAuthenticationError:
        logger.exception('SMTP rechazó las credenciales (confirmación de %s)', usuario.username)
        return (
            'el servidor de correo rechazó el usuario o la contraseña '
            '(revisá EMAIL_HOST_USER / EMAIL_HOST_PASSWORD — Gmail necesita una '
            '"contraseña de aplicación")'
        )
    except (socket.timeout, TimeoutError, ConnectionError, OSError, smtplib.SMTPException):
        logger.exception(
            'No se pudo conectar con el servidor de correo (confirmación de %s)', usuario.username,
        )
        return (
            'no se pudo conectar con el servidor de correo. Puede que la red '
            'bloquee la salida SMTP (puerto 587); el administrador puede activar '
            'la cuenta a mano desde "Usuarios activos" mientras tanto'
        )
    except Exception:
        logger.exception('Error inesperado enviando la confirmación de %s', usuario.username)
        return 'ocurrió un error inesperado al enviar el correo (ver el registro del sistema)'

    return ''

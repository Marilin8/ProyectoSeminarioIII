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


DOMINIOS_QUE_NO_RECIBEN = ('example.com', 'example.org', 'example.net')
SUFIJOS_QUE_NO_RECIBEN = ('.local', '.localhost', '.invalid', '.test', '.example')


def correo_no_recibe(correo):
    """True si el correo está vacío o es de un dominio inventado (ej. admin@clinica.local),
    donde un código de seguridad nunca llegaría."""
    correo = (correo or '').strip().lower()
    if '@' not in correo:
        return True
    dominio = correo.rsplit('@', 1)[1]
    return dominio in DOMINIOS_QUE_NO_RECIBEN or dominio.endswith(SUFIJOS_QUE_NO_RECIBEN)


def enmascarar_correo(correo):
    usuario, _, dominio = (correo or '').partition('@')
    if not dominio:
        return ''
    return f'{usuario[:2]}{"*" * max(len(usuario) - 2, 1)}@{dominio}'


def enviar_codigo_seguridad(usuario, codigo, motivo, minutos_validez):
    """Manda al correo del usuario un código de 6 dígitos para confirmar una acción delicada
    (`motivo` completa la frase "su código para ..."). Devuelve '' si salió, o un texto corto
    con el motivo del fallo, sin lanzar excepciones (mismo contrato que enviar_confirmacion_cuenta)."""
    if not (settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD):
        return (
            'el sistema todavía no tiene configurado el correo emisor '
            '(EMAIL_HOST_USER / EMAIL_HOST_PASSWORD en el archivo .env)'
        )
    mensaje = f"""Hola {usuario.first_name or usuario.username}:

Su código de seguridad para {motivo} es:

    {codigo}

Es válido por {minutos_validez} minutos y solo sirve una vez. Si usted no lo pidió,
ignore este mensaje y cambie su contraseña.

Atentamente,
Clínica de Imágenes
"""
    correo = EmailMessage(
        subject='Su código de seguridad - Clínica de Imágenes', body=mensaje, to=[usuario.email],
    )
    try:
        correo.send()
    except smtplib.SMTPAuthenticationError:
        logger.exception('SMTP rechazó las credenciales (código de seguridad)')
        return 'el servidor de correo rechazó el usuario o la contraseña (EMAIL_HOST_USER / EMAIL_HOST_PASSWORD)'
    except (socket.timeout, TimeoutError, ConnectionError, OSError, smtplib.SMTPException):
        logger.exception('No se pudo conectar con el servidor de correo (código de seguridad)')
        return 'no se pudo conectar con el servidor de correo; intente de nuevo en unos minutos'
    except Exception:
        logger.exception('Error inesperado enviando el código de seguridad')
        return 'ocurrió un error inesperado al enviar el correo (ver el registro del sistema)'
    return ''

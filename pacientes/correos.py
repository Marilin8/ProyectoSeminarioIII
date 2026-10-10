import base64
import io
import logging
import smtplib
import socket
from email.mime.image import MIMEImage
from urllib.parse import urlencode

import qrcode
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse
from django.utils.html import escape

logger = logging.getLogger(__name__)

CONTENT_ID_QR = 'qr_resultados'


def _link_visor(orden, nombre_url):
    """Enlace al visor web del estudio (el mismo que va en el correo): lleva
    el token público de la orden y, al abrirlo, el visor pide el DPI."""
    token = orden.asegurar_token_publico()
    ac = base64.urlsafe_b64encode(str(token).encode('ascii')).decode('ascii').rstrip('=')
    return (
        settings.VISOR_BASE_URL + reverse(nombre_url)
        + '?' + urlencode({'studyId': orden.id, 'tab': 'images', 'ac': ac})
    )


def link_visor_paciente(orden):
    return _link_visor(orden, 'visor_estudio')


def link_visor_medico_tratante(orden):
    return _link_visor(orden, 'visor_estudio_medico_tratante')


def qr_png(url):
    """PNG (bytes) con el código QR de `url`. El QR solo codifica el mismo
    enlace del correo: abre el mismo visor, que sigue pidiendo el DPI."""
    buffer = io.BytesIO()
    qrcode.make(url, box_size=8, border=2).save(buffer, format='PNG')
    return buffer.getvalue()


def qr_data_uri(url):
    return 'data:image/png;base64,' + base64.b64encode(qr_png(url)).decode('ascii')


def _armar_correo(asunto, texto, destinatario, link):
    """Correo de texto con el enlace de siempre, más -- como extra, sin quitar
    el enlace -- una versión HTML que muestra el código QR de ese mismo
    enlace. Si por lo que sea no se puede generar el QR, sale solo el texto
    con el enlace (el envío nunca depende del QR)."""
    correo = EmailMultiAlternatives(subject=asunto, body=texto, to=[destinatario])
    try:
        imagen_qr = qr_png(link)
    except Exception:
        logger.exception('No se pudo generar el QR del correo; se envía solo con el enlace')
        return correo

    link_html = escape(link)
    cuerpo = escape(texto).replace(
        link_html,
        f'<a href="{link_html}">{link_html}</a>'
        '<br><br><strong>También puede escanear este código QR con la cámara de su celular '
        '(abre el mismo enlace):</strong><br>'
        f'<img src="cid:{CONTENT_ID_QR}" alt="Código QR de sus resultados" width="200" height="200" '
        'style="margin:8px 0;border:1px solid #d1d5db;">',
    ).replace('\n', '<br>')
    correo.attach_alternative(
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1f2937;">'
        f'{cuerpo}</div>',
        'text/html',
    )
    # "related": la imagen se muestra dentro del HTML en vez de verse como
    # un adjunto suelto (las imágenes incrustadas con data: las bloquea Gmail).
    correo.mixed_subtype = 'related'
    imagen = MIMEImage(imagen_qr, _subtype='png')
    imagen.add_header('Content-ID', f'<{CONTENT_ID_QR}>')
    imagen.add_header('Content-Disposition', 'inline', filename='qr-resultados.png')
    correo.attach(imagen)
    return correo


def enviar_resultados(orden):
    """Envía al correo del paciente el informe PDF adjunto + un link al visor
    web del estudio (donde ve las imágenes que dejó seleccionadas la
    radióloga). El visor pide el DPI completo para abrirse.

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

    link_visor = link_visor_paciente(orden)

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

Se le pedirá su DPI completo para acceder.

{linea_informe}

Gracias por confiar en nosotros.

Atentamente,
Clínica de Imágenes
"""

    correo = _armar_correo(asunto, mensaje, paciente.correo, link_visor)

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


def enviar_estudio_medico_tratante(orden):
    """Avisa por correo al médico tratante de la cita (cuando es privado o
    ambos, ver MedicoTratante.recibe_estudios_privados) que el estudio de su
    paciente ya está listo, con un link al mismo visor web que usa el
    paciente. A diferencia de enviar_resultados, acá NO se adjunta el PDF
    del informe: el DPI del médico es la única llave para verlo, así que
    mandarlo suelto por correo anularía el control de acceso.

    Devuelve '' si el correo se mandó, o un texto corto con el motivo del
    fallo -- mismo contrato que enviar_resultados, nunca deja que la
    excepción tumbe la pantalla que lo llamó."""
    medico = orden.cita.medico_tratante

    if not medico or not medico.correo:
        return 'el médico tratante no tiene un correo registrado'

    if not (settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD):
        return (
            'el sistema todavía no tiene configurado el correo emisor '
            '(EMAIL_HOST_USER / EMAIL_HOST_PASSWORD en el archivo .env)'
        )

    link_visor = link_visor_medico_tratante(orden)

    paciente = orden.cita.paciente
    asunto = 'Estudio listo para revisar - Clínica de Imágenes'
    mensaje = f"""Estimado(a) {medico.nombre}:

El estudio de su paciente {paciente.nombre} {paciente.apellido} ya está
disponible para revisión en Clínica de Imágenes.

Tipo de estudio: {orden.cita.tipo_estudio.nombre}
Fecha: {orden.cita.fecha:%d/%m/%Y}

Para revisarlo, ingrese a este enlace:
{link_visor}

Se le pedirá su DPI completo para acceder: es la llave que protege el
estudio del paciente, así que no la comparta.

Atentamente,
Clínica de Imágenes
"""

    correo = _armar_correo(asunto, mensaje, medico.correo, link_visor)

    try:
        correo.send()
    except smtplib.SMTPAuthenticationError:
        logger.exception(
            'SMTP rechazó las credenciales (orden #%s, médico tratante)', orden.id,
        )
        return (
            'el servidor de correo rechazó el usuario o la contraseña '
            '(revisá EMAIL_HOST_USER / EMAIL_HOST_PASSWORD — Gmail necesita una '
            '"contraseña de aplicación")'
        )
    except (socket.timeout, TimeoutError, ConnectionError, OSError, smtplib.SMTPException):
        logger.exception(
            'No se pudo conectar con el servidor de correo (orden #%s, médico tratante)', orden.id,
        )
        return (
            'no se pudo conectar con el servidor de correo. Puede que la red '
            'bloquee la salida SMTP (puerto 587); probá desde otra red o pedile '
            'al administrador que configure el envío por un servicio de correo'
        )
    except Exception:
        logger.exception(
            'Error inesperado enviando el correo al médico tratante (orden #%s)', orden.id,
        )
        return 'ocurrió un error inesperado al enviar el correo (ver el registro del sistema)'

    return ''

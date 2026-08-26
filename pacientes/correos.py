import logging

from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)


def enviar_resultados(orden):
    """Envía el informe y las imágenes del estudio al correo del paciente.

    Portado del commit 758cb02 "Agregar envío de resultados por correo" de
    TechBlood/ProyectoSeminarioClinica. Si el paciente no tiene correo
    registrado, no hace nada (no interrumpe el flujo de adjuntar informe).

    Devuelve True si el correo se mandó, False si no había correo del
    paciente o si el envío falló (ej. el sistema todavía no tiene
    configuradas las credenciales SMTP en el .env: EMAIL_HOST_USER /
    EMAIL_HOST_PASSWORD). Nunca deja que ese fallo tumbe la pantalla que
    lo llamó — el llamador decide qué mostrarle al usuario según el
    resultado."""
    paciente = orden.cita.paciente

    if not paciente.correo:
        return False

    asunto = 'Resultados de su estudio - Clínica de Imágenes'

    mensaje = f"""
Estimado(a) {paciente.nombre} {paciente.apellido}:

Adjunto encontrará los resultados de su estudio realizado en
Clínica de Imágenes.

Tipo de estudio:
{orden.cita.tipo_estudio.nombre}

Gracias por confiar en nosotros.

Atentamente,

Clínica de Imágenes
"""

    correo = EmailMessage(
        subject=asunto,
        body=mensaje,
        to=[paciente.correo],
    )

    # Adjuntar informe PDF
    if orden.informe_archivo:
        correo.attach_file(orden.informe_archivo.path)

    # Adjuntar imágenes: solo las que la radióloga dejó seleccionadas en la
    # galería (ver_imagenes_jpg). Las que descartó ya no tienen "archivo"
    # (se les borró el JPG al desmarcarlas), por eso el filtro por
    # seleccionada=True alcanza para no intentar adjuntar algo vacío.
    for imagen in orden.imagenes.filter(seleccionada=True).exclude(archivo=''):
        correo.attach_file(imagen.archivo.path)

    try:
        correo.send()
    except Exception:
        # Típicamente: EMAIL_HOST_USER/EMAIL_HOST_PASSWORD sin configurar
        # en .env, o el servidor SMTP rechazó la conexión. Se registra en
        # el log del servidor para que el administrador lo pueda revisar,
        # pero no se propaga: quien llamó a esta función avisa al usuario
        # con un mensaje entendible en vez de una pantalla de error.
        logger.exception('No se pudo enviar el correo de resultados de la orden #%s', orden.id)
        return False

    return True

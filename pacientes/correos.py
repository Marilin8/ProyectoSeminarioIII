import base64
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import EmailMessage
from django.urls import reverse

logger = logging.getLogger(__name__)


def enviar_resultados(orden):
    """Envía al correo del paciente el informe PDF adjunto + un link al visor
    web del estudio (donde ve las imágenes que dejó seleccionadas la
    radióloga). El visor pide los últimos 4 dígitos del DPI para abrirse.

    Si el paciente no tiene correo registrado, no hace nada (no interrumpe el
    flujo). Devuelve True si el correo se mandó, False si no había correo o si
    el envío falló (ej. credenciales SMTP sin configurar en el .env:
    EMAIL_HOST_USER / EMAIL_HOST_PASSWORD). Nunca deja que ese fallo tumbe la
    pantalla que lo llamó."""
    paciente = orden.cita.paciente

    if not paciente.correo:
        return False

    token = orden.asegurar_token_publico()
    ac = base64.urlsafe_b64encode(str(token).encode('ascii')).decode('ascii').rstrip('=')
    link_visor = (
        settings.VISOR_BASE_URL + reverse('visor_estudio')
        + '?' + urlencode({'studyId': orden.id, 'tab': 'images', 'ac': ac})
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

El informe médico va adjunto a este correo en formato PDF.

Gracias por confiar en nosotros.

Atentamente,
Clínica de Imágenes
"""

    correo = EmailMessage(subject=asunto, body=mensaje, to=[paciente.correo])

    # Solo se adjunta el informe PDF. Las imágenes ya no se adjuntan: se ven
    # en el visor web a través del link.
    if orden.informe_archivo:
        correo.attach_file(orden.informe_archivo.path)

    try:
        correo.send()
    except Exception:
        logger.exception('No se pudo enviar el correo de resultados de la orden #%s', orden.id)
        return False

    return True

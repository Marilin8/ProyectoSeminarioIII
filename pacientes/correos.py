from django.core.mail import EmailMessage


def enviar_resultados(orden):
    """Envía el informe y las imágenes del estudio al correo del paciente.

    Portado del commit 758cb02 "Agregar envío de resultados por correo" de
    TechBlood/ProyectoSeminarioClinica. Si el paciente no tiene correo
    registrado, no hace nada (no interrumpe el flujo de adjuntar informe)."""
    paciente = orden.cita.paciente

    if not paciente.correo:
        return

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

    correo.send()

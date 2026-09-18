"""Borra el catálogo de estudios de prueba y carga el catálogo real
normalizado desde el tarifario (pacientes/data/catalogo_estudios.json):
~131 estudios con modalidad, duración y matriz de precios: COEX (solo
tarifa hábil) y Privado / Emergencia IGSS (hábil e inhábil).

Como los TipoEstudio están protegidos por las citas, primero se borran las
órdenes de trabajo y las citas de prueba (junto con sus imágenes y
notificaciones, que caen en cascada). En una base vacía (por ejemplo la de
tests o una instalación nueva) esos borrados no hacen nada y solo se carga
el catálogo.
"""
import json
from pathlib import Path

from django.db import migrations

CATALOGO = Path(__file__).resolve().parent.parent / 'data' / 'catalogo_estudios.json'

# clave del JSON -> (convenio, horario_habil). COEX no tiene tarifa inhábil.
MAPA_PRECIOS = {
    'coex_habil': ('coex', True),
    'privado_habil': ('privado', True),
    'privado_inhabil': ('privado', False),
    'emergencia_igss_habil': ('emergencia_igss', True),
    'emergencia_igss_inhabil': ('emergencia_igss', False),
}


def cargar(apps, schema_editor):
    TipoEstudio = apps.get_model('pacientes', 'TipoEstudio')
    PrecioEstudio = apps.get_model('pacientes', 'PrecioEstudio')
    Cita = apps.get_model('pacientes', 'Cita')
    OrdenTrabajo = apps.get_model('pacientes', 'OrdenTrabajo')
    Usuario = apps.get_model('accounts', 'Usuario')

    # Purga: órdenes -> citas -> tipos de estudio. Las imágenes de estudio y
    # las notificaciones ligadas a una cita se borran en cascada.
    OrdenTrabajo.objects.all().delete()
    Cita.objects.all().delete()
    TipoEstudio.objects.all().delete()

    # Todos los radiólogos activos quedan habilitados para todos los estudios
    # nuevos (igual que hacía 0019 con el catálogo viejo); el admin después
    # ajusta la lista estudio por estudio desde "Usuarios activos".
    radiologos = list(Usuario.objects.filter(rol='medico_radiologo', is_active=True))

    datos = json.loads(CATALOGO.read_text(encoding='utf-8'))
    for item in datos:
        estudio = TipoEstudio.objects.create(
            nombre=item['nombre'],
            modalidad=item['modalidad'],
            duracion_minutos=item['duracion_minutos'],
            activo=True,
        )
        if radiologos:
            estudio.radiologos.set(radiologos)
        filas = []
        for clave, valor in item['precios'].items():
            convenio, habil = MAPA_PRECIOS[clave]
            filas.append(PrecioEstudio(
                tipo_estudio=estudio, convenio=convenio,
                horario_habil=habil, precio=valor,
            ))
        PrecioEstudio.objects.bulk_create(filas)


def revertir(apps, schema_editor):
    PrecioEstudio = apps.get_model('pacientes', 'PrecioEstudio')
    TipoEstudio = apps.get_model('pacientes', 'TipoEstudio')
    PrecioEstudio.objects.all().delete()
    TipoEstudio.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('pacientes', '0029_remove_tipoestudio_precio_tipoestudio_modalidad_and_more'),
        ('accounts', '0003_usuario_rol'),
    ]

    operations = [
        migrations.RunPython(cargar, revertir),
    ]

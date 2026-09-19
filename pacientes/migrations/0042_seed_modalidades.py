# Siembra las modalidades que ya venían como enum fijo en TipoEstudio, con
# el mismo código, para que los estudios existentes no queden sin una
# Modalidad válida al pasar el campo a texto libre (ver 0041).

from django.db import migrations

MODALIDADES_INICIALES = [
    ('rx', 'Rayos X'),
    ('rx_contraste', 'Rayos X con contraste / fluoroscopía'),
    ('tac', 'Tomografía (TAC)'),
    ('usg', 'Ultrasonido / Doppler'),
    ('mamo_densit', 'Mamografía / Densitometría'),
]


def sembrar_modalidades(apps, schema_editor):
    Modalidad = apps.get_model('pacientes', 'Modalidad')
    for codigo, nombre in MODALIDADES_INICIALES:
        Modalidad.objects.get_or_create(codigo=codigo, defaults={'nombre': nombre})


def eliminar_modalidades(apps, schema_editor):
    Modalidad = apps.get_model('pacientes', 'Modalidad')
    Modalidad.objects.filter(codigo__in=[codigo for codigo, _ in MODALIDADES_INICIALES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('pacientes', '0041_modalidad_ordentrabajo_correccion_detalle_and_more'),
    ]

    operations = [
        migrations.RunPython(sembrar_modalidades, eliminar_modalidades),
    ]

from django.db import migrations

TIPOS_ESTUDIO = ['Rayos X', 'Ultrasonido', 'Tomografía', 'Resonancia']


def crear_tipos_estudio(apps, schema_editor):
    TipoEstudio = apps.get_model('pacientes', 'TipoEstudio')
    for nombre in TIPOS_ESTUDIO:
        TipoEstudio.objects.get_or_create(nombre=nombre)


def eliminar_tipos_estudio(apps, schema_editor):
    TipoEstudio = apps.get_model('pacientes', 'TipoEstudio')
    TipoEstudio.objects.filter(nombre__in=TIPOS_ESTUDIO).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('pacientes', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(crear_tipos_estudio, eliminar_tipos_estudio),
    ]

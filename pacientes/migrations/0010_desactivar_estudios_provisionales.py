from django.db import migrations

TIPOS_ESTUDIO_PROVISIONALES = ['Rayos X', 'Ultrasonido', 'Tomografía', 'Resonancia']


def desactivar_provisionales(apps, schema_editor):
    TipoEstudio = apps.get_model('pacientes', 'TipoEstudio')
    TipoEstudio.objects.filter(nombre__in=TIPOS_ESTUDIO_PROVISIONALES).update(activo=False)


def reactivar_provisionales(apps, schema_editor):
    TipoEstudio = apps.get_model('pacientes', 'TipoEstudio')
    TipoEstudio.objects.filter(nombre__in=TIPOS_ESTUDIO_PROVISIONALES).update(activo=True)


class Migration(migrations.Migration):

    dependencies = [
        ('pacientes', '0009_tipoestudio_activo'),
    ]

    operations = [
        migrations.RunPython(desactivar_provisionales, reactivar_provisionales),
    ]

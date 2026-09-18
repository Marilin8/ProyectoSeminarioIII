from django.db import migrations


def asignar_radiologos_a_todos_los_estudios(apps, schema_editor):
    """Antes de este cambio, cualquier radiólogo podía asignarse a cualquier
    tipo de estudio. Para no romper ese comportamiento en instalaciones ya
    en uso, se asigna a cada radiólogo existente todos los tipos de estudio
    activos; a partir de ahora el admin puede restringir cada radiólogo a
    los estudios que realmente realiza."""
    Usuario = apps.get_model('accounts', 'Usuario')
    TipoEstudio = apps.get_model('pacientes', 'TipoEstudio')

    radiologos = Usuario.objects.filter(rol='medico_radiologo')
    estudios_activos = TipoEstudio.objects.filter(activo=True)
    for estudio in estudios_activos:
        estudio.radiologos.set(radiologos)


def revertir(apps, schema_editor):
    TipoEstudio = apps.get_model('pacientes', 'TipoEstudio')
    for estudio in TipoEstudio.objects.all():
        estudio.radiologos.clear()


class Migration(migrations.Migration):

    dependencies = [
        ('pacientes', '0018_tipoestudio_radiologos'),
        # La migración de datos consulta Usuario.rol, así que necesita que el
        # campo ya exista.
        ('accounts', '0003_usuario_rol'),
    ]

    operations = [
        migrations.RunPython(asignar_radiologos_a_todos_los_estudios, revertir),
    ]

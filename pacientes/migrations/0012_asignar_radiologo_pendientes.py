from django.db import migrations


def asignar_radiologo_a_pendientes_huerfanas(apps, schema_editor):
    Cita = apps.get_model('pacientes', 'Cita')
    Usuario = apps.get_model('accounts', 'Usuario')

    pendientes_sin_radiologo = Cita.objects.filter(estado='pendiente', radiologo__isnull=True)
    if not pendientes_sin_radiologo.exists():
        return

    radiologos = list(Usuario.objects.filter(rol='medico_radiologo'))
    if len(radiologos) == 1:
        pendientes_sin_radiologo.update(radiologo=radiologos[0])
    # Si hay 0 o más de 1 radiólogo, no hay forma no ambigua de elegir uno solo;
    # se dejan sin asignar (un admin las puede reasignar a mano si hace falta).


def revertir(apps, schema_editor):
    # No hay nada que revertir de forma segura (no sabemos cuáles habíamos tocado).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('pacientes', '0011_cita_radiologo'),
    ]

    operations = [
        migrations.RunPython(asignar_radiologo_a_pendientes_huerfanas, revertir),
    ]

from django.db import migrations


class Migration(migrations.Migration):
    """Une las dos hojas que dejó la fusión de visual-andres con Marilin: la
    que cierra el historial de Andres (0038_merge_20260911_1840) y la cadena
    de Elmer (0041_ordenpago_notas)."""

    dependencies = [
        ('pacientes', '0038_merge_20260911_1840'),
        ('pacientes', '0041_ordenpago_notas'),
    ]

    operations = []

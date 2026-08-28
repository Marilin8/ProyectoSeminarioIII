# Generado a mano, portando el módulo de notificación por correo
# (commit 758cb02 "Agregar envío de resultados por correo" de
# TechBlood/ProyectoSeminarioClinica) a este proyecto.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pacientes', '0024_cita_es_emergencia_forzada'),
    ]

    operations = [
        migrations.AddField(
            model_name='paciente',
            name='correo',
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
    ]

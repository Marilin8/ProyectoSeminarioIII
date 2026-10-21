"""Crea la "Sucursal principal" y le asigna todo lo que existía antes de las
sucursales: todos los usuarios, todas las citas y todos los turnos."""
from django.db import migrations


def crear_principal(apps, schema_editor):
    Sucursal = apps.get_model('accounts', 'Sucursal')
    Usuario = apps.get_model('accounts', 'Usuario')
    Cita = apps.get_model('pacientes', 'Cita')
    Ticket = apps.get_model('pacientes', 'Ticket')

    principal = Sucursal.objects.filter(es_principal=True).first()
    if principal is None:
        principal = Sucursal.objects.create(nombre='Sucursal principal', es_principal=True)
    Cita.objects.filter(sucursal__isnull=True).update(sucursal=principal)
    Ticket.objects.filter(sucursal__isnull=True).update(sucursal=principal)
    for usuario in Usuario.objects.all():
        if not usuario.sucursales.exists():
            usuario.sucursales.add(principal)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0038_sucursales'),
        ('pacientes', '0055_cita_ticket_sucursal'),
    ]

    operations = [
        migrations.RunPython(crear_principal, migrations.RunPython.noop),
    ]

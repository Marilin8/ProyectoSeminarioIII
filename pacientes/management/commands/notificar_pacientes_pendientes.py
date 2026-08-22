from django.core.management.base import BaseCommand

from ...models import Paciente
from ...views import _notificar_datos_pendientes_si_corresponde


class Command(BaseCommand):
    help = (
        'Barrido de seguridad (pensado para fin del día) sobre TODOS los pacientes '
        'registrados que quedaron con datos pendientes de llenar: sexo, fecha de '
        'nacimiento o teléfono. Desde que se agenda una cita o se registra un ticket ya '
        'se avisa al instante (ver pacientes.views._notificar_datos_pendientes_si_corresponde); '
        'este comando solo cubre el caso de pacientes viejos a los que no se les volvió a '
        'agendar nada y quedaron sin avisar. No duplica avisos: si ya hay uno sin leer '
        'para un paciente, lo deja como está. Pensado para programarse como tarea diaria '
        '(ej. Programador de tareas de Windows a las 18:00).'
    )

    def handle(self, *args, **options):
        pacientes_pendientes = [
            paciente for paciente in Paciente.objects.order_by('nombre', 'apellido')
            if paciente.campos_pendientes()
        ]

        if not pacientes_pendientes:
            self.stdout.write('Ningún paciente quedó con datos pendientes.')
            return

        for paciente in pacientes_pendientes:
            _notificar_datos_pendientes_si_corresponde(paciente)

        self.stdout.write(self.style.SUCCESS(
            f'Revisados {len(pacientes_pendientes)} paciente(s) con datos pendientes '
            '(no se duplican avisos ya existentes sin leer).'
        ))

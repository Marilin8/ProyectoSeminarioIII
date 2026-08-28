<<<<<<< HEAD
from django.core.management.base import BaseCommand

from ...models import Paciente
from ...views import _notificar_datos_pendientes_si_corresponde
=======
import datetime

from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from accounts.models import Usuario

from ...models import Cita, Notificacion, Paciente, Ticket
>>>>>>> 6c6a7f92a98d42c5c4312897e77c9a819885bb58


class Command(BaseCommand):
    help = (
<<<<<<< HEAD
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
=======
        'Notifica a las recepcionistas activas (pensado para fin del día) el listado de '
        'pacientes atendidos hoy (con cita o ticket registrado hoy) que quedaron con datos '
        'pendientes de llenar: sexo, fecha de nacimiento o teléfono. Pensado para programarse '
        'como tarea diaria (ej. Programador de tareas de Windows a las 18:00).'
    )

    def handle(self, *args, **options):
        hoy = timezone.localdate()

        # No usamos `creada_en__date=hoy`: ese lookup depende de que MySQL
        # tenga cargadas las tablas de zonas horarias con nombre (CONVERT_TZ),
        # y en este servidor no están cargadas (ver accounts/views.py,
        # bitacora()), así que Django siempre devolvía 0 filas. Calculamos el
        # rango del día directamente en Python en vez de depender de esa
        # conversión en la base de datos.
        inicio = timezone.make_aware(datetime.datetime.combine(hoy, datetime.time.min))
        fin = timezone.make_aware(datetime.datetime.combine(hoy, datetime.time.max))

        ids_pacientes = set(
            Cita.objects.filter(creada_en__range=(inicio, fin)).values_list('paciente_id', flat=True)
        )
        ids_pacientes.update(
            Ticket.objects.filter(creado_en__range=(inicio, fin)).values_list('paciente_id', flat=True)
        )

        if not ids_pacientes:
            self.stdout.write('No hubo pacientes atendidos hoy.')
            return

        pacientes_pendientes = [
            (paciente, paciente.campos_pendientes())
            for paciente in Paciente.objects.filter(id__in=ids_pacientes).order_by('nombre', 'apellido')
        ]
        pacientes_pendientes = [(p, campos) for p, campos in pacientes_pendientes if campos]

        if not pacientes_pendientes:
            self.stdout.write('Ningún paciente de hoy quedó con datos pendientes.')
            return

        recepcionistas = Usuario.objects.filter(rol=Usuario.ROL_RECEPCIONISTA, is_active=True)
        if not recepcionistas.exists():
            self.stdout.write(self.style.WARNING('No hay recepcionistas activas a quién avisar.'))
            return

        for paciente, campos in pacientes_pendientes:
            mensaje = (
                f'{paciente.nombre} {paciente.apellido} (DPI {paciente.dpi}) quedó con datos '
                f'pendientes: {", ".join(campos)}.'
            )
            Notificacion.notificar_a_varios(
                usuarios=recepcionistas,
                tipo=Notificacion.TIPO_DATOS_PACIENTE_PENDIENTES,
                mensaje=mensaje,
                url=reverse('completar_datos_paciente', args=[paciente.id]),
            )

        self.stdout.write(self.style.SUCCESS(
            f'Avisadas {recepcionistas.count()} recepcionista(s) sobre '
            f'{len(pacientes_pendientes)} paciente(s) con datos pendientes.'
>>>>>>> 6c6a7f92a98d42c5c4312897e77c9a819885bb58
        ))

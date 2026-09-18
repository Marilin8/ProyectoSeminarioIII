"""Carga tickets/turnos de prueba para visualizar la Pantalla de turnos.

Ejemplos:
    python manage.py cargar_turnos_demo
    python manage.py cargar_turnos_demo --cantidad 12 --atendidos 2 --limpiar
"""

import random

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import Usuario
from pacientes.models import DailySequence, Paciente, Ticket


class Command(BaseCommand):
    help = 'Crea tickets de prueba (COEX / Privado / Emergencia IGSS) para hoy.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--cantidad', type=int, default=8,
            help='Cuántos turnos crear (por defecto 8).',
        )
        parser.add_argument(
            '--atendidos', type=int, default=1,
            help='Marcar los primeros N turnos como ya atendidos (por defecto 1).',
        )
        parser.add_argument(
            '--limpiar', action='store_true',
            help='Borra los tickets de hoy y reinicia el contador antes de crear.',
        )
        parser.add_argument(
            '--semilla', type=int, default=None,
            help='Semilla para que el reparto de servicios sea reproducible.',
        )

    def handle(self, *args, **opciones):
        cantidad = opciones['cantidad']
        atendidos = opciones['atendidos']
        if cantidad < 1:
            raise CommandError('--cantidad debe ser al menos 1.')
        if opciones['semilla'] is not None:
            random.seed(opciones['semilla'])

        recepcionista = (
            Usuario.objects.filter(rol=Usuario.ROL_RECEPCIONISTA, is_active=True).first()
            or Usuario.objects.filter(is_superuser=True).first()
        )
        if recepcionista is None:
            raise CommandError('No hay ningún usuario recepcionista ni superusuario para registrar los turnos.')

        pacientes = list(Paciente.objects.all())
        if not pacientes:
            raise CommandError('No hay pacientes en la base de datos. Crea algunos primero.')

        hoy = timezone.localdate()

        if opciones['limpiar']:
            borrados, _ = Ticket.del_dia(hoy).delete()
            DailySequence.objects.filter(
                servicio=Ticket.SECUENCIA_TURNOS, fecha=hoy,
            ).delete()
            self.stdout.write(self.style.WARNING(f'Se borraron {borrados} ticket(s) de hoy y se reinició el contador.'))

        servicios = [
            Ticket.SERVICIO_COEX,
            Ticket.SERVICIO_PRIVADO,
            Ticket.SERVICIO_EMERGENCIA_IGSS,
        ]
        motivos = [
            'Radiografía de tórax', 'Ultrasonido abdominal', 'Tomografía de cráneo',
            'Resonancia de rodilla', 'Mamografía de control', 'Radiografía de columna',
        ]

        elegidos = random.sample(pacientes, min(cantidad, len(pacientes)))
        if len(elegidos) < cantidad:
            elegidos += random.choices(pacientes, k=cantidad - len(elegidos))

        creados = []
        for i, paciente in enumerate(elegidos):
            servicio = random.choice(servicios)
            urgente = servicio == Ticket.SERVICIO_EMERGENCIA_IGSS and random.random() < 0.6
            ticket = Ticket.objects.create(
                paciente=paciente,
                servicio=servicio,
                prioridad=Ticket.PRIORIDAD_URGENTE if urgente else Ticket.PRIORIDAD_NORMAL,
                motivo=random.choice(motivos),
                registrado_por=recepcionista,
            )
            creados.append(ticket)

        # Un par de turnos de Privado adelantan posiciones en la fila.
        for ticket in creados:
            if ticket.servicio == Ticket.SERVICIO_PRIVADO and random.random() < 0.5:
                ticket.adelantar(random.randint(1, 2))

        for ticket in creados[:max(0, atendidos)]:
            ticket.estado = Ticket.ESTADO_ATENDIDO
            ticket.atendido_en = timezone.now()
            ticket.save(update_fields=['estado', 'atendido_en'])

        self.stdout.write(self.style.SUCCESS(f'\nSe crearon {len(creados)} turno(s) para {hoy}:'))
        cola = Ticket.del_dia(hoy).order_by('-prioridad', 'orden')
        for ticket in cola:
            marca = ' (atendido)' if ticket.estado == Ticket.ESTADO_ATENDIDO else ''
            self.stdout.write(
                f'  {ticket.turno}  {ticket.get_servicio_display():16} '
                f'{ticket.get_prioridad_display():8} {ticket.paciente.nombre} {ticket.paciente.apellido}{marca}'
            )
        self.stdout.write('\nAbre la Pantalla de turnos en /turnos/')

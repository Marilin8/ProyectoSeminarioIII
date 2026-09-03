import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Usuario
from pacientes.models import (
    Cita, Cobro, OrdenTrabajo, Paciente, ReporteDiario, TipoEstudio,
)


class Command(BaseCommand):
    help = 'Crea usuarios, pacientes y citas de demostración para validar los bloques 1-6.'

    PASSWORD = 'DemoCIME2026!'

    USUARIOS = (
        ('demo_admin', Usuario.ROL_ADMINISTRADOR, True),
        ('demo_recepcionista', Usuario.ROL_RECEPCIONISTA, False),
        ('demo_caja', Usuario.ROL_RECEPCIONISTA, False),
        ('demo_tecnico', Usuario.ROL_TECNICO_IMAGENES, False),
        ('demo_radiologo', Usuario.ROL_MEDICO_RADIOLOGO, False),
        ('demo_remitente', Usuario.ROL_MEDICO_REMITENTE, False),
    )

    @transaction.atomic
    def handle(self, *args, **options):
        usuarios = {}
        for username, rol, superuser in self.USUARIOS:
            usuario, creado = Usuario.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': 'Demo',
                    'last_name': rol.replace('_', ' ').title(),
                    'email': f'{username}@cime.local',
                    'rol': rol,
                    'is_staff': superuser,
                    'is_superuser': superuser,
                },
            )
            usuario.rol = rol
            usuario.puede_operar_caja = username in ('demo_caja', 'demo_recepcionista')
            if rol == Usuario.ROL_TECNICO_IMAGENES:
                usuario.salario_base = 3500
            elif rol == Usuario.ROL_MEDICO_RADIOLOGO:
                usuario.salario_base = 5000
            usuario.is_active = True
            usuario.is_staff = superuser
            usuario.is_superuser = superuser
            usuario.set_password(self.PASSWORD)
            usuario.save()
            usuarios[username] = usuario
            self.stdout.write(f'{"Creado" if creado else "Actualizado"}: {username}')

        radiologos = list(
            Usuario.objects.filter(
                rol=Usuario.ROL_MEDICO_RADIOLOGO, is_active=True
            ).order_by('id')
        )
        if radiologos:
            for estudio in TipoEstudio.objects.filter(activo=True).prefetch_related('radiologos'):
                if not estudio.radiologos.filter(is_active=True).exists():
                    estudio.radiologos.add(radiologos[estudio.pk % len(radiologos)])

        paciente, _ = Paciente.objects.get_or_create(
            dpi='1234567891234',
            defaults={
                'nombre': 'Paciente',
                'apellido': 'Prueba',
                'sexo': Paciente.SEXO_MASCULINO,
                'telefono': '5555-1234',
                'correo': 'pacienteprueba@correo.com',
                'fecha_nacimiento': datetime.date(1990, 1, 15),
            },
        )

        estudios = list(
            TipoEstudio.objects.filter(activo=True).prefetch_related('radiologos').order_by('id')[:3]
        )
        estudio = (
            TipoEstudio.objects.filter(activo=True, radiologos__isnull=False)
            .prefetch_related('radiologos')
            .order_by('id')
            .first()
        )
        if estudio and radiologos:
            hoy = timezone.localdate()
            escenarios = (
                (Cita.CONVENIO_COEX, hoy + datetime.timedelta(days=1), datetime.time(9, 0), 'COEX'),
                (Cita.CONVENIO_PRIVADO, hoy + datetime.timedelta(days=2), datetime.time(10, 0), 'Privado'),
                (Cita.CONVENIO_EMERGENCIA_IGSS, hoy, datetime.time(11, 0), 'Emergencia IGSS'),
            )
            for indice, (convenio, fecha, hora, etiqueta) in enumerate(escenarios):
                paciente_demo, _ = Paciente.objects.get_or_create(
                    dpi=f'12345678912{str(indice + 1).zfill(2)}',
                    defaults={
                        'nombre': 'Demo', 'apellido': etiqueta,
                        'sexo': Paciente.SEXO_FEMENINO,
                        'telefono': f'5555-12{indice:02d}',
                        'correo': f'demo{indice}@correo.com',
                    },
                )
                tipo = estudios[indice % len(estudios)] if estudios else estudio
                radiologo = tipo.radiologos.filter(is_active=True).first() or radiologos[0]
                cita, creada = Cita.objects.get_or_create(
                    paciente=paciente_demo, tipo_estudio=tipo, convenio=convenio,
                    fecha=fecha, hora=hora,
                    defaults={
                        'radiologo': radiologo, 'estado': Cita.ESTADO_AGENDADA,
                        'fecha_sugerida': fecha, 'hora_sugerida': hora,
                        'creada_por': usuarios['demo_admin'],
                        'revisada_por': usuarios['demo_admin'],
                        'revisada_en': timezone.now(),
                    },
                )
                ReporteDiario.objects.get_or_create(fecha=fecha, convenio=convenio)
                if convenio == Cita.CONVENIO_PRIVADO:
                    orden, _ = OrdenTrabajo.objects.get_or_create(
                        cita=cita,
                        defaults={'motivo': 'Demostración de flujo', 'creada_por': usuarios['demo_admin']},
                    )
                    cita.estado = Cita.ESTADO_EN_PROCESO
                    cita.save(update_fields=['estado'])
                    Cobro.objects.get_or_create(cita=cita)
                self.stdout.write(f'{"Creada" if creada else "Existente"}: cita demo {etiqueta} #{cita.pk}')

            for indice in range(1, 21):
                convenio, etiqueta = escenarios[(indice - 1) % len(escenarios)][0], escenarios[(indice - 1) % len(escenarios)][3]
                fecha = hoy + datetime.timedelta(days=(indice % 7) - 3)
                hora = datetime.time(8 + (indice % 8), 0)
                paciente_extra, _ = Paciente.objects.get_or_create(
                    dpi=f'9876543{indice:06d}',
                    defaults={
                        'nombre': 'Paciente Demo',
                        'apellido': f'{etiqueta} {indice:02d}',
                        'sexo': Paciente.SEXO_MASCULINO,
                        'telefono': f'4444-{indice:04d}',
                        'correo': 'jcastillom32@gmail.com',
                    },
                )
                if paciente_extra.correo != 'jcastillom32@gmail.com':
                    paciente_extra.correo = 'jcastillom32@gmail.com'
                    paciente_extra.save(update_fields=['correo'])
                tipo = estudios[(indice - 1) % len(estudios)]
                radiologo = tipo.radiologos.filter(is_active=True).first() or radiologos[0]
                cita_extra, creada = Cita.objects.get_or_create(
                    paciente=paciente_extra, tipo_estudio=tipo, convenio=convenio,
                    fecha=fecha, hora=hora,
                    defaults={
                        'radiologo': radiologo, 'estado': Cita.ESTADO_EN_PROCESO,
                        'fecha_sugerida': fecha, 'hora_sugerida': hora,
                        'hora_llegada': timezone.now(),
                        'creada_por': usuarios['demo_recepcionista'],
                        'revisada_por': usuarios['demo_admin'],
                        'revisada_en': timezone.now(),
                    },
                )
                orden_extra, _ = OrdenTrabajo.objects.get_or_create(
                    cita=cita_extra,
                    defaults={
                        'motivo': 'Demostración de filtros y paginación',
                        'creada_por': usuarios['demo_recepcionista'],
                    },
                )
                Cobro.objects.get_or_create(cita=cita_extra)
                ReporteDiario.objects.get_or_create(fecha=fecha, convenio=convenio)
            self.stdout.write('Creadas o reutilizadas: 20 órdenes demo para Caja.')

        self.stdout.write(self.style.SUCCESS(
            f'Datos demo listos. Contraseña común de usuarios demo: {self.PASSWORD}'
        ))

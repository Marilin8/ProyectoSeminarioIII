import datetime
import random
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Usuario, PagoPlanilla, LineaComisionLiquidada
from pacientes.models import (
    Paciente, TipoEstudio, PrecioEstudio, Combo, Cita, Cobro, ReporteDiario
)

class Command(BaseCommand):
    help = 'Puebla la base de datos con datos de prueba realistas para todas las pantallas.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Iniciando poblamiento de datos de prueba...'))
        
        try:
            with transaction.atomic():
                # 1. USUARIOS DEMO
                usuarios_datos = [
                    ('demo_admin', Usuario.ROL_ADMINISTRADOR, True),
                    ('demo_recepcionista', Usuario.ROL_RECEPCIONISTA, False),
                    ('demo_tecnico', Usuario.ROL_TECNICO_IMAGENES, False),
                    ('demo_radiologo', Usuario.ROL_MEDICO_RADIOLOGO, False),
                    ('demo_remitente', Usuario.ROL_MEDICO_REMITENTE, False),
                ]
                
                usuarios_map = {}
                for username, rol, is_super in usuarios_datos:
                    user, created = Usuario.objects.get_or_create(
                        username=username,
                        defaults={
                            'first_name': 'Demo',
                            'last_name': rol.replace('_', ' ').title(),
                            'email': f'{username}@cime.local',
                            'rol': rol,
                            'is_staff': is_super,
                            'is_superuser': is_super,
                            'is_active': True,
                        }
                    )
                    user.set_password('DemoCIME2026!')
                    # Salarios base para planilla
                    if rol == Usuario.ROL_TECNICO_IMAGENES:
                        user.salario_base = Decimal('3500.00')
                    elif rol == Usuario.ROL_MEDICO_RADIOLOGO:
                        user.salario_base = Decimal('5000.00')
                    
                    user.save()
                    usuarios_map[username] = user

                # 2. CATÁLOGO DE ESTUDIOS
                estudios_datos = [
                    ('Rayos X de Tórax', 'rx', 30, Decimal('200.00')),
                    ('Ultrasonido Abdominal', 'usg', 45, Decimal('400.00')),
                    ('Tomografía Craneal', 'tac', 60, Decimal('800.00')),
                    ('Resonancia Magnética de Columna', 'mamo_densit', 90, Decimal('1200.00')),
                    ('Mamografía', 'mamo_densit', 30, Decimal('300.00')),
                ]
                
                estudios_objs = []
                for nombre, mod, dur, precio_priv in estudios_datos:
                    estudio, _ = TipoEstudio.objects.get_or_create(
                        nombre=nombre,
                        defaults={'modalidad': mod, 'duracion_minutos': dur, 'activo': True}
                    )
                    # Precios por convenio
                    PrecioEstudio.objects.update_or_create(
                        tipo_estudio=estudio, convenio=Cita.CONVENIO_PRIVADO, horario_habil=True,
                        defaults={'precio': precio_priv}
                    )
                    PrecioEstudio.objects.update_or_create(
                        tipo_estudio=estudio, convenio=Cita.CONVENIO_COEX, horario_habil=True,
                        defaults={'precio': Decimal('0.00')}
                    )
                    PrecioEstudio.objects.update_or_create(
                        tipo_estudio=estudio, convenio=Cita.CONVENIO_EMERGENCIA_IGSS, horario_habil=True,
                        defaults={'precio': Decimal('0.00')}
                    )
                    # Asignar radiólogo por defecto
                    estudio.radiologos.add(usuarios_map['demo_radiologo'])
                    estudios_objs.append(estudio)

                # 3. COMBOS
                combo1, _ = Combo.objects.get_or_create(
                    nombre='Checkup Básico',
                    defaults={'activo': True, 'aplica_descuento': True, 'porcentaje_descuento': Decimal('10.00')}
                )
                combo1.estudios.set([estudios_objs[0], estudios_objs[1]])

                combo2, _ = Combo.objects.get_or_create(
                    nombre='Perfil Ginecológico',
                    defaults={'activo': True, 'aplica_descuento': True, 'porcentaje_descuento': Decimal('15.00')}
                )
                combo2.estudios.set([estudios_objs[4], estudios_objs[1]])

                # 4. PACIENTES
                pacientes_datos = [
                    ('1000000010001', 'Juan', 'Pérez', '5555-1001', '1985-05-12'),
                    ('1000000010002', 'María', 'García', '5555-1002', '1992-08-24'),
                    ('1000000010003', 'Carlos', 'López', '5555-1003', '1978-11-03'),
                    ('1000000010004', 'Ana', 'Martínez', '5555-1004', '2000-01-15'),
                    ('1000000010005', 'Luis', 'Rodríguez', '5555-10005', '1965-03-20'),
                    ('1000000010006', 'Elena', 'Sánchez', '5555-1006', '1988-07-07'),
                    ('1000000010007', 'Pedro', 'Gómez', '5555-1007', '1995-12-30'),
                    ('1000000010008', 'Sofía', 'Díaz', '5555-1008', '1982-04-18'),
                    ('1000000010009', 'Jorge', 'Ruiz', '5555-1009', '1970-09-10'),
                    ('1000000010010', 'Lucía', 'Torres', '5555-1010', '1998-06-22'),
                ]

                pacientes_objs = []
                for dpi, nom, ape, tel, nac in pacientes_datos:
                    p, _ = Paciente.objects.get_or_create(
                        dpi=dpi,
                        defaults={
                            'nombre': nom, 'apellido': ape, 'telefono': tel,
                            'fecha_nacimiento': datetime.datetime.strptime(nac, '%Y-%m-%d').date(),
                            'sexo': Paciente.SEXO_MASCULINO if nom in ['Juan', 'Carlos', 'Luis', 'Pedro', 'Jorge'] else Paciente.SEXO_FEMENINO
                        }
                    )
                    pacientes_objs.append(p)

                # 5. CITAS Y COBROS
                hoy = timezone.localdate()
                convenios = [Cita.CONVENIO_COEX, Cita.CONVENIO_PRIVADO, Cita.CONVENIO_EMERGENCIA_IGSS]
                estados = [Cita.ESTADO_AGENDADA, Cita.ESTADO_PENDIENTE, Cita.ESTADO_PROCESADA]
                
                citas_creadas = 0
                for i in range(30):
                    # Distribuir fechas: semana pasada, hoy, próxima semana
                    delta = random.randint(-7, 14)
                    fecha = hoy + datetime.timedelta(days=delta)
                    hora = datetime.time(random.randint(7, 17), random.choice([0, 15, 30, 45]))
                    
                    paciente = random.choice(pacientes_objs)
                    estudio = random.choice(estudios_objs)
                    conv = random.choice(convenios)
                    est = random.choice(estados)
                    
                    cita, _ = Cita.objects.get_or_create(
                        paciente=paciente, tipo_estudio=estudio, convenio=conv,
                        fecha=fecha, hora=hora,
                        defaults={
                            'estado': est,
                            'radiologo': usuarios_map['demo_radiologo'],
                            'creada_por': usuarios_map['demo_recepcionista'],
                            'revisada_por': usuarios_map['demo_admin'],
                            'revisada_en': timezone.now(),
                        }
                    )
                    citas_creadas += 1
                    
                    # Crear Cobro asociado
                    Cobro.objects.get_or_create(
                        cita=cita,
                        defaults={
                            'estado': random.choice([Cobro.ESTADO_PENDIENTE, Cobro.ESTADO_PAGADO]),
                            'forma_pago': random.choice([Cobro.FORMA_EFECTIVO, Cobro.FORMA_TARJETA]),
                            'numero_boleta': f'B-{random.randint(1000, 9999)}'
                        }
                    )

                # 6. PLANILLA Y COMISIONES
                # Pago de salario para el mes pasado
                mes_pasado = hoy.replace(day=1) - datetime.timedelta(days=1)
                anio_pago = mes_pasado.year
                mes_pago = mes_pasado.month

                empleados_comision = [usuarios_map['demo_tecnico'], usuarios_map['demo_radiologo']]
                for emp in empleados_comision:
                    pago, _ = PagoPlanilla.objects.get_or_create(
                        usuario=emp, anio=anio_pago, mes=mes_pago,
                        defaults={
                            'salario_base': emp.salario_base,
                            'comisiones': Decimal('150.00'),
                            'total': emp.salario_base + Decimal('150.00'),
                            'registrado_por': usuarios_map['demo_admin'],
                            'verificado': True,
                            'es_adelanto': False
                        }
                    )
                    # Crear algunas líneas de comisión para el historial
                    citas_proc = Cita.objects.filter(estado=Cita.ESTADO_PROCESADA)[:5]
                    for c in citas_proc:
                        LineaComisionLiquidada.objects.get_or_create(
                            pago=pago, usuario=emp, cita=c,
                            defaults={
                                'rol_en_cita': LineaComisionLiquidada.rol_tecnico if emp.rol == Usuario.ROL_TECNICO_IMAGENES else LineaComisionLiquidada.rol_radiologo,
                                'comision': Decimal('25.00')
                            }
                        )

                # 7. REPORTES DIARIOS (Muestra COEX)
                for i in range(3):
                    fecha_rep = hoy - datetime.timedelta(days=i)
                    ReporteDiario.objects.get_or_create(
                        fecha=fecha_rep, convenio=Cita.CONVENIO_COEX,
                        defaults={'estado': ReporteDiario.ESTADO_ENVIADO, 'enviado_por': usuarios_map['demo_admin']}
                    )

                # RESUMEN FINAL
                self.stdout.write('\\n' + '='*30)
                self.stdout.write(self.style.SUCCESS('RESUMEN DE POBLAMIENTO'))
                self.stdout.write('='*30)
                self.stdout.write(f'Usuarios Demo: {len(usuarios_map)}')
                self.stdout.write(f'Tipos de Estudio: {TipoEstudio.objects.count()}')
                self.stdout.write(f'Combos: {Combo.objects.count()}')
                self.stdout.write(f'Pacientes: {Paciente.objects.count()}')
                self.stdout.write(f'Citas: {Cita.objects.count()}')
                self.stdout.write(f'Cobros: {Cobro.objects.count()}')
                self.stdout.write(f'Pagos Planilla: {PagoPlanilla.objects.count()}')
                self.stdout.write(f'Reportes Diarios: {ReporteDiario.objects.count()}')
                self.stdout.write('='*30)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error durante el poblamiento: {str(e)}'))
            raise e

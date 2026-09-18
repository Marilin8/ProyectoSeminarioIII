"""Carga datos visuales para probar HU-058 y los cobros por convenio.

Uso:
    python manage.py cargar_hu58_demo
    python manage.py cargar_hu58_demo --limpiar

La carga crea 10 estudios por convenio (COEX, Emergencia IGSS y Privado).
Los estudios COEX/IGSS se organizan en parejas del mismo paciente para poder
crear órdenes agrupadas desde Caja. La marca en ``Paciente.notas`` no existe,
por lo que se usa un DPI prefijado para evitar duplicados al repetir el
comando.
"""

import datetime
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Usuario
from pacientes.models import (
    Cita,
    Cobro,
    Combo,
    DetalleOrdenPago,
    EstudioExtra,
    ImagenEstudio,
    OrdenPago,
    OrdenTrabajo,
    Notificacion,
    Paciente,
    PrecioEstudio,
    TipoEstudio,
)


MARCA_DPI = '99958'


class Command(BaseCommand):
    help = 'Crea datos demo variados para probar HU-058 y los cobros por convenio.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limpiar', action='store_true',
            help='Elimina únicamente los datos creados por este comando antes de cargarlos.',
        )

    def handle(self, *args, **options):
        recepcionista = self._usuario(Usuario.ROL_RECEPCIONISTA, 'demo_recepcionista')
        tecnico = self._usuario(Usuario.ROL_TECNICO_IMAGENES, 'demo_tecnico')
        radiologo = self._usuario(Usuario.ROL_MEDICO_RADIOLOGO, 'demo_radiologo')
        if not recepcionista or not tecnico or not radiologo:
            raise CommandError('Faltan las cuentas demo de recepción, técnico o radiología.')

        if options['limpiar']:
            self._limpiar()

        with transaction.atomic():
            estudios = self._crear_estudios()
            combo = self._crear_combo(estudios)
            resultados = {
                convenio: self._crear_lote(
                    convenio, estudios, combo, recepcionista, tecnico, radiologo,
                )
                for convenio in (
                    Cita.CONVENIO_COEX,
                    Cita.CONVENIO_EMERGENCIA_IGSS,
                    Cita.CONVENIO_PRIVADO,
                )
            }

        self.stdout.write(self.style.SUCCESS('Datos demo HU-058 creados correctamente.'))
        for convenio, cantidad in resultados.items():
            self.stdout.write(f'  {dict(Cita.CONVENIO_CHOICES)[convenio]}: {cantidad} estudios')
        self.stdout.write(
            'Use demo_recepcionista / DemoCIME2026! y abra Caja > Pagos pendientes.'
        )

    @staticmethod
    def _usuario(rol, username):
        return Usuario.objects.filter(username=username, rol=rol, is_active=True).first()

    def _limpiar(self):
        pacientes = Paciente.objects.filter(dpi__startswith=MARCA_DPI)
        citas = Cita.objects.filter(paciente__in=pacientes)
        OrdenPago.objects.filter(paciente__in=pacientes).delete()
        OrdenTrabajo.objects.filter(cita__in=citas).delete()
        Cobro.objects.filter(cita__in=citas).delete()
        EstudioExtra.objects.filter(cita__in=citas).delete()
        citas.delete()
        pacientes.delete()
        self.stdout.write(self.style.WARNING('Datos demo HU-058 anteriores eliminados.'))

    def _crear_estudios(self):
        nombres = [
            ('Demo RX Tórax PA', TipoEstudio.MODALIDAD_RX),
            ('Demo RX Tórax Lateral', TipoEstudio.MODALIDAD_RX),
            ('Demo RX Columna AP', TipoEstudio.MODALIDAD_RX),
            ('Demo Ultrasonido abdominal', TipoEstudio.MODALIDAD_USG),
            ('Demo TAC de cráneo', TipoEstudio.MODALIDAD_TAC),
            ('Demo Mamografía bilateral', TipoEstudio.MODALIDAD_MAMO_DENSIT),
        ]
        estudios = []
        for indice, (nombre, modalidad) in enumerate(nombres):
            estudio, _ = TipoEstudio.objects.get_or_create(
                nombre=nombre, defaults={'modalidad': modalidad},
            )
            for convenio, precio in (
                (Cita.CONVENIO_COEX, 100 + indice * 15),
                (Cita.CONVENIO_EMERGENCIA_IGSS, 130 + indice * 20),
                (Cita.CONVENIO_PRIVADO, 180 + indice * 25),
            ):
                PrecioEstudio.objects.update_or_create(
                    tipo_estudio=estudio,
                    convenio=convenio,
                    horario_habil=True,
                    defaults={'precio': Decimal(precio)},
                )
                if convenio != Cita.CONVENIO_COEX:
                    PrecioEstudio.objects.update_or_create(
                        tipo_estudio=estudio,
                        convenio=convenio,
                        horario_habil=False,
                        defaults={'precio': Decimal(precio + 35)},
                    )
            estudios.append(estudio)
        return estudios

    def _crear_combo(self, estudios):
        combo, _ = Combo.objects.get_or_create(
            nombre='Demo Combo Tórax HU-058',
            defaults={
                'activo': True,
                'aplica_descuento': True,
                'porcentaje_descuento': Decimal('15.00'),
            },
        )
        combo.estudios.set(estudios[:2])
        return combo

    def _crear_lote(self, convenio, estudios, combo, recepcionista, tecnico, radiologo):
        creadas = []
        pacientes = {}
        for indice in range(10):
            grupo = indice // 2
            if grupo not in pacientes:
                pacientes[grupo] = Paciente.objects.create(
                    dpi=f'{MARCA_DPI}{convenio[:2].upper()}{grupo:02d}',
                    carnet_igss=(
                        f'DEMO-{convenio[:3].upper()}-{grupo:02d}'
                        if convenio != Cita.CONVENIO_PRIVADO else None
                    ),
                    nombre=f'Demo {convenio.title()} {grupo + 1}',
                    apellido=f'Paciente {grupo + 1}',
                    sexo='F' if grupo % 2 else 'M',
                    telefono=f'5555-{1000 + grupo}',
                    correo=f'demo.hu58.{convenio}.{grupo}@example.com',
                    fecha_nacimiento=datetime.date(
                        1980 + grupo, (grupo % 9) + 1, (grupo % 25) + 1,
                    ),
                )
            paciente = pacientes[grupo]
            hora = datetime.time(8 + (indice % 5) * 2, 0 if indice % 2 == 0 else 30)
            esta_procesada = indice < 3
            cita = Cita.objects.create(
                paciente=paciente,
                tipo_estudio=estudios[indice % len(estudios)],
                radiologo=radiologo,
                convenio=convenio,
                estado=Cita.ESTADO_PROCESADA if esta_procesada else Cita.ESTADO_EN_PROCESO,
                fecha=timezone.localdate(),
                hora=hora,
                hora_llegada=timezone.now(),
                medico_referente='Demo HU-058',
                notas=f'Dato demo HU-058 {convenio} #{indice + 1}',
                creada_por=recepcionista,
            )
            orden_trabajo = OrdenTrabajo.objects.create(
                cita=cita, motivo='Prueba visual HU-058', creada_por=recepcionista,
            )
            if esta_procesada:
                orden_trabajo.informe_texto = 'Informe demo HU-058: sin hallazgos de relevancia.'
                orden_trabajo.informe_creado_por = radiologo
                orden_trabajo.informe_creado_en = timezone.now()
                orden_trabajo.save(update_fields=[
                    'informe_texto', 'informe_creado_por', 'informe_creado_en',
                ])
            ImagenEstudio.objects.create(
                orden=orden_trabajo,
                archivo=ContentFile(b'imagen demo', name=f'hu58-{convenio}-{indice}.jpg'),
                subida_por=tecnico,
            )
            Notificacion.notificar(
                destinatario=radiologo,
                tipo=Notificacion.TIPO_ESTUDIO_LISTO_INFORMAR,
                mensaje=(
                    f'Estudio demo listo para informar: {cita.tipo_estudio} de '
                    f'{paciente.nombre} {paciente.apellido}.'
                ),
                cita=cita,
                url='/citas/procesadas/',
            )
            Cobro.objects.create(cita=cita)
            if indice in (2, 7):
                EstudioExtra.objects.create(
                    cita=cita,
                    tipo_estudio=estudios[(indice + 1) % len(estudios)],
                    agregado_por=radiologo,
                    notas='Extra demo notificado por Radiología.',
                )
            if convenio == Cita.CONVENIO_PRIVADO and indice >= 5:
                cobro = cita.cobro
                cobro.forma_pago = (
                    Cobro.FORMA_EFECTIVO if indice % 2 else Cobro.FORMA_TARJETA
                )
                cobro.numero_boleta = f'DEMO-PRIV-{indice + 1:02d}'
                cobro.marcar_pagado(recepcionista, notas='Pago privado demo.')
            creadas.append(cita)

        if convenio in (Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS):
            self._crear_orden_demo(creadas[:2], combo, recepcionista)
        return len(creadas)

    def _crear_orden_demo(self, citas, combo, recepcionista):
        subtotal = sum((cita.precio for cita in citas), Decimal('0.00'))
        descuento = (subtotal * combo.porcentaje_descuento / 100).quantize(Decimal('0.01'))
        orden = OrdenPago.objects.create(
            convenio=citas[0].convenio,
            paciente=citas[0].paciente,
            subtotal=subtotal,
            descuento=descuento,
            total=subtotal - descuento,
            combo=combo if citas[0].tipo_estudio_id in combo.estudios.values_list('id', flat=True) else None,
            notas='Orden demo pendiente de boleta global.',
            creado_por=recepcionista,
        )
        for cita in citas:
            DetalleOrdenPago.objects.create(
                orden_pago=orden,
                cita=cita,
                tipo_estudio=cita.tipo_estudio,
                precio=cita.precio,
                descuento=(descuento / len(citas)).quantize(Decimal('0.01')),
                total=(cita.precio - descuento / len(citas)).quantize(Decimal('0.01')),
            )

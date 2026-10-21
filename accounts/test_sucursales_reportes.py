"""Etapa 4 de sucursales: estadísticas, finanzas, Estado de la Clínica, informe anual y
comisiones según la sucursal elegida en la barra lateral."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import estadisticas, finanzas
from accounts.models import Sucursal
from pacientes.comisiones_medico_tratante import desglose_por_sucursal
from pacientes.models import Cita, MedicoTratante, PrecioEstudio, TipoEstudio
from pacientes.tests import Usuario, crear_cita, crear_paciente, crear_usuario


class ReportesPorSucursalTests(TestCase):
    def setUp(self):
        self.admin = crear_usuario('admin_rep_suc', rol=Usuario.ROL_ADMINISTRADOR)
        self.principal = Sucursal.objects.get(es_principal=True)
        self.norte = Sucursal.objects.create(nombre='Norte')
        self.rx = TipoEstudio.objects.create(nombre='RX reportes suc')
        for convenio, _ in Cita.CONVENIO_CHOICES:
            for habil in (True, False):
                PrecioEstudio.objects.create(tipo_estudio=self.rx, convenio=convenio, horario_habil=habil, precio=Decimal('100'))
        self.hoy = timezone.localdate()
        self.cita_norte = crear_cita(self.admin, tipo_estudio=self.rx, sucursal=self.norte, estado=Cita.ESTADO_PROCESADA)
        for i in range(2):
            crear_cita(
                self.admin, tipo_estudio=self.rx, sucursal=self.principal, estado=Cita.ESTADO_PROCESADA,
                paciente=crear_paciente(dpi=f'929292929291{i}'),
            )
        self.client.force_login(self.admin)

    def _elegir(self, sucursal):
        self.client.post(reverse('cambiar_sucursal'), {'sucursal': sucursal.id if sucursal else 'todas'})

    def test_estadisticas_de_una_sucursal_y_comparativo(self):
        solo_norte = estadisticas.calcular(30, hoy=self.hoy, sucursal=self.norte)
        todas = estadisticas.calcular(30, hoy=self.hoy)

        self.assertEqual(solo_norte['estudios']['total'], 1)
        self.assertEqual(todas['estudios']['total'], 3)
        self.assertEqual(solo_norte['por_sucursal'], [])
        self.assertEqual([(f['nombre'], f['total']) for f in todas['por_sucursal']],
                         [('Sucursal principal', 2), ('Norte', 1)])

    def test_el_panel_usa_la_sucursal_de_la_barra_lateral(self):
        self._elegir(self.norte)
        respuesta = self.client.get(reverse('dashboard'))
        self.assertEqual(respuesta.context['estudios']['total'], 1)
        self.assertContains(respuesta, 'Norte')

        self._elegir(None)
        respuesta = self.client.get(reverse('dashboard'))
        self.assertEqual(respuesta.context['estudios']['total'], 3)
        self.assertContains(respuesta, 'Estudios realizados por sucursal')

    def test_finanzas_por_sucursal(self):
        filtros = finanzas.leer_filtros({'periodo': 'hoy'}, sucursal=self.norte)
        self.assertEqual(finanzas.calcular(filtros)['kpi']['produccion'], Decimal('100'))

        todas = finanzas.calcular(finanzas.leer_filtros({'periodo': 'hoy'}))
        self.assertEqual(todas['kpi']['produccion'], Decimal('300'))
        self.assertEqual([f['nombre'] for f in todas['sucursales_ranking']], ['Sucursal principal', 'Norte'])

        self._elegir(self.norte)
        csv = self.client.get(reverse('panel_financiero'), {'periodo': 'hoy', 'formato': 'csv'}).content.decode('utf-8-sig')
        self.assertIn('Norte', csv)
        self.assertNotIn('Sucursal principal', csv)

    def test_estado_de_la_clinica_por_sucursal(self):
        self._elegir(self.norte)
        datos = self.client.get(reverse('estado_clinica_datos'), {'dias': 30}).json()

        self.assertEqual(datos['citas']['completadas'], 1)
        self.assertEqual(datos['periodo']['sucursal'], 'Norte')

    def test_informe_anual_por_sucursal(self):
        self._elegir(self.norte)
        respuesta = self.client.get(reverse('informe_anual'), {'anio': self.hoy.year})

        self.assertEqual(respuesta.context['cantidad_anual'], 1)

    def test_desglose_de_comisiones_por_sucursal(self):
        medico = MedicoTratante.objects.create(nombre='Dr. Desglose')
        Cita.objects.update(medico_tratante=medico)

        filas = desglose_por_sucursal(Cita.objects.select_related('sucursal').order_by('id'))

        self.assertEqual([(f['nombre'], f['cantidad'], f['total']) for f in filas],
                         [('Norte', 1, Decimal('100')), ('Sucursal principal', 2, Decimal('200'))])

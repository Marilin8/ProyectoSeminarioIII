import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import finanzas
from pacientes.models import Cita, Cobro, MedicoTratante, Paciente, PrecioEstudio, TipoEstudio

Usuario = get_user_model()


class PanelFinancieroTests(TestCase):
    def setUp(self):
        self.admin = Usuario.objects.create_user(
            username='admin-fin', password='clave-segura-123', rol=Usuario.ROL_ADMINISTRADOR,
        )
        self.rad_ana = Usuario.objects.create_user(
            username='rad-ana', password='x-segura-123', rol=Usuario.ROL_MEDICO_RADIOLOGO, first_name='Ana',
        )
        self.rad_beto = Usuario.objects.create_user(
            username='rad-beto', password='x-segura-123', rol=Usuario.ROL_MEDICO_RADIOLOGO, first_name='Beto',
        )
        self.medico = MedicoTratante.objects.create(nombre='Dr. Referente')
        self.hoy = timezone.localdate()
        self.rx = self._estudio('RX fin', Decimal('100'))
        self.tac = self._estudio('TAC fin', Decimal('500'))
        self._dpi = 2000000000000

    def _estudio(self, nombre, precio):
        estudio = TipoEstudio.objects.create(nombre=nombre)
        for convenio, _ in Cita.CONVENIO_CHOICES:
            for habil in (True, False):
                PrecioEstudio.objects.create(
                    tipo_estudio=estudio, convenio=convenio, horario_habil=habil,
                    precio=precio if habil else precio * 2,
                )
        return estudio

    def _cita(self, estudio, convenio=Cita.CONVENIO_PRIVADO, estado=Cita.ESTADO_PROCESADA,
              radiologo=None, medico=None, fecha=None, hora=datetime.time(9, 0), pagado=None):
        self._dpi += 1
        paciente = Paciente.objects.create(
            dpi=str(self._dpi), nombre='P', apellido='Fin', sexo=Paciente.SEXO_FEMENINO,
            fecha_nacimiento=datetime.date(1990, 1, 1),
        )
        cita = Cita.objects.create(
            paciente=paciente, tipo_estudio=estudio, convenio=convenio, estado=estado,
            fecha=fecha or self.hoy, hora=hora, creada_por=self.admin,
            radiologo=radiologo, medico_tratante=medico,
        )
        if pagado is not None:
            cobro = Cobro.objects.create(cita=cita, forma_pago=pagado)
            cobro.marcar_pagado(self.admin)
        return cita

    def _calcular(self, **filtros):
        datos = {'periodo': 'hoy'}
        datos.update(filtros)
        return finanzas.calcular(finanzas.leer_filtros(datos, hoy=self.hoy))

    def test_produccion_cobrado_pendiente_e_igss(self):
        self._cita(self.rx, pagado=Cobro.FORMA_EFECTIVO)                      # 100 cobrado
        self._cita(self.tac)                                                  # 500 por cobrar
        self._cita(self.tac, convenio=Cita.CONVENIO_COEX)                     # 500 IGSS
        self._cita(self.rx, estado=Cita.ESTADO_AUSENTE)                       # no suma
        self._cita(self.rx, hora=datetime.time(19, 0), pagado=Cobro.FORMA_TARJETA)  # 200 inhábil

        kpi = self._calcular()['kpi']

        self.assertEqual(kpi['produccion'], Decimal('1300'))
        self.assertEqual(kpi['estudios'], 4)
        self.assertEqual(kpi['privado_cobrado'], Decimal('300'))
        self.assertEqual(kpi['privado_pendiente'], Decimal('500'))
        self.assertEqual(kpi['igss'], Decimal('500'))
        self.assertEqual(kpi['promedio'], Decimal('325.00'))

    def test_rankings_de_radiologos_medicos_y_estudios(self):
        self._cita(self.rx, radiologo=self.rad_ana, medico=self.medico)
        self._cita(self.rx, radiologo=self.rad_ana)
        self._cita(self.tac, radiologo=self.rad_beto, medico=self.medico)

        datos = self._calcular()

        self.assertEqual([(f['nombre'], f['cantidad'], f['monto']) for f in datos['radiologos']],
                         [('Beto', 1, Decimal('500')), ('Ana', 2, Decimal('200'))])
        self.assertEqual(datos['medicos'][0]['nombre'], 'Dr. Referente')
        self.assertEqual(datos['medicos'][0]['cantidad'], 2)
        self.assertEqual(datos['kpi']['referido'], Decimal('600'))
        self.assertEqual(datos['estudios'][0]['nombre'], 'TAC fin')

    def test_filtros_por_estudio_radiologo_y_convenio(self):
        self._cita(self.rx, radiologo=self.rad_ana)
        self._cita(self.tac, radiologo=self.rad_beto, convenio=Cita.CONVENIO_COEX)

        self.assertEqual(self._calcular(estudio=str(self.rx.id))['kpi']['produccion'], Decimal('100'))
        self.assertEqual(self._calcular(radiologo=str(self.rad_beto.id))['kpi']['produccion'], Decimal('500'))
        self.assertEqual(self._calcular(convenio='coex')['kpi']['produccion'], Decimal('500'))
        self.assertEqual(self._calcular(convenio='nada')['kpi']['produccion'], Decimal('600'))

    def test_periodos(self):
        hoy = datetime.date(2026, 10, 21)  # miércoles
        self.assertEqual(finanzas.rango_del_periodo('semana', hoy=hoy)[1:], (datetime.date(2026, 10, 19), hoy))
        self.assertEqual(finanzas.rango_del_periodo('mes', hoy=hoy)[1:], (datetime.date(2026, 10, 1), hoy))
        self.assertEqual(finanzas.rango_del_periodo('mes_anterior', hoy=hoy)[1:],
                         (datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)))
        self.assertEqual(finanzas.rango_del_periodo('rango', '2026-10-10', '2026-10-01', hoy=hoy)[1:],
                         (datetime.date(2026, 10, 1), datetime.date(2026, 10, 10)))
        self.assertEqual(finanzas.rango_del_periodo('x', hoy=hoy)[0], 'mes')

    def test_la_pagina_y_el_csv(self):
        self._cita(self.rx, radiologo=self.rad_ana, pagado=Cobro.FORMA_EFECTIVO)
        self.client.force_login(self.admin)

        pagina = self.client.get(reverse('panel_financiero'), {'periodo': 'hoy'})
        self.assertContains(pagina, 'Panel financiero')
        self.assertContains(pagina, 'Q100.00')
        html = pagina.content.decode()
        self.assertNotRegex(html, r'(width|height):\d+,\d')

        csv = self.client.get(reverse('panel_financiero'), {'periodo': 'hoy', 'formato': 'csv'})
        self.assertEqual(csv['Content-Type'], 'text/csv; charset=utf-8')
        texto = csv.content.decode('utf-8-sig')
        self.assertIn('RX fin', texto)
        self.assertIn('100.00', texto)
        self.assertIn('Cobrado', texto)

    def test_solo_el_administrador(self):
        recep = Usuario.objects.create_user(
            username='recep-fin', password='x-segura-123', rol=Usuario.ROL_RECEPCIONISTA,
        )
        self.client.force_login(recep)
        self.assertEqual(self.client.get(reverse('panel_financiero')).status_code, 302)

    def test_el_panel_de_estadisticas_enlaza_a_finanzas(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('dashboard')), reverse('panel_financiero'))

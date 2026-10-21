"""Etapa 3 de sucursales: precios propios por sucursal sobre el precio general."""
import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import finanzas
from accounts.models import Bitacora, Sucursal
from pacientes.models import (
    Cita, Combo, HistorialPrecioEstudio, PrecioEstudio, TipoEstudio,
)
from pacientes.tests import Usuario, crear_cita, crear_paciente, crear_usuario

Q = Decimal


class PreciosPorSucursalTests(TestCase):
    def setUp(self):
        self.admin = crear_usuario('admin_precios_suc', rol=Usuario.ROL_ADMINISTRADOR)
        self.principal = Sucursal.objects.get(es_principal=True)
        self.norte = Sucursal.objects.create(nombre='Norte')
        self.rx = TipoEstudio.objects.create(nombre='RX precios suc')
        for convenio, _ in Cita.CONVENIO_CHOICES:
            for habil in (True, False):
                PrecioEstudio.objects.create(
                    tipo_estudio=self.rx, convenio=convenio, horario_habil=habil, precio=Q('100') if habil else Q('150'),
                )
        self.client.force_login(self.admin)

    def _url(self, sucursal=None):
        return f"{reverse('precios_sucursal_estudio', args=[self.rx.id])}?sucursal={(sucursal or self.norte).id}"

    def _guardar(self, privado_habil='', sucursal=None, **otros):
        datos = {'sucursal': (sucursal or self.norte).id, 'precio_privado_habil': privado_habil}
        datos.update(otros)
        return self.client.post(self._url(sucursal), datos)

    def _precio(self, **kw):
        return TipoEstudio.objects.get(pk=self.rx.pk).precio_para(Cita.CONVENIO_PRIVADO, True, **kw)

    def test_sin_precio_propio_usa_el_general(self):
        self.assertEqual(self._precio(sucursal=self.norte), Q('100'))

    def test_precio_propio_solo_en_esa_sucursal(self):
        self._guardar('120')

        self.assertEqual(self._precio(sucursal=self.norte), Q('120'))
        self.assertEqual(self._precio(sucursal=self.principal), Q('100'))
        self.assertEqual(self._precio(), Q('100'))
        # Las demás celdas siguen con el general (incluida la inhábil, que cae a su general).
        estudio = TipoEstudio.objects.get(pk=self.rx.pk)
        self.assertEqual(estudio.precio_para(Cita.CONVENIO_PRIVADO, False, sucursal=self.norte), Q('150'))
        self.assertTrue(Bitacora.objects.filter(descripcion__contains='en la sucursal Norte').exists())

    def test_la_cita_cobra_el_precio_de_su_sucursal(self):
        self._guardar('120')
        cita_norte = crear_cita(self.admin, tipo_estudio=self.rx, sucursal=self.norte)
        cita_central = crear_cita(
            self.admin, tipo_estudio=self.rx, sucursal=self.principal, paciente=crear_paciente(dpi='9191919191911'),
        )

        self.assertEqual(Cita.objects.get(pk=cita_norte.pk).precio, Q('120'))
        self.assertEqual(Cita.objects.get(pk=cita_central.pk).precio, Q('100'))

    def test_dejar_vacio_vuelve_al_general_y_queda_en_el_historial(self):
        self._guardar('120')
        self._guardar('')

        self.assertEqual(self._precio(sucursal=self.norte), Q('100'))
        self.assertFalse(PrecioEstudio.objects.filter(tipo_estudio=self.rx, sucursal=self.norte).exists())
        historial = list(HistorialPrecioEstudio.objects.filter(sucursal=self.norte).order_by('creado_en'))
        self.assertEqual([(h.valor_anterior, h.valor_nuevo) for h in historial], [(None, Q('120')), (Q('120'), None)])

    def test_las_fechas_pasadas_conservan_el_precio_que_tenian(self):
        ayer = timezone.localdate() - datetime.timedelta(days=1)
        manana = timezone.localdate() + datetime.timedelta(days=1)
        self._guardar('120')
        # Antes de crear el precio propio, en Norte valía el general.
        self.assertEqual(self._precio(sucursal=self.norte, fecha=ayer), Q('100'))

        ahora = timezone.now() + datetime.timedelta(days=2)
        with mock.patch('django.utils.timezone.now', return_value=ahora):
            self._guardar('130')
        # Mañana (antes del cambio a 130) seguía en 120; el precio actual es 130.
        self.assertEqual(self._precio(sucursal=self.norte, fecha=manana), Q('120'))
        self.assertEqual(self._precio(sucursal=self.norte), Q('130'))

    def test_el_precio_general_no_mezcla_los_precios_de_sucursal(self):
        self._guardar('120')

        respuesta = self.client.get(reverse('editar_estudio', args=[self.rx.id]))

        self.assertEqual(respuesta.context['form'].fields['precio_privado_habil'].initial, Q('100'))

    def test_el_combo_tiene_precio_propio_en_la_sucursal(self):
        otro = TipoEstudio.objects.create(nombre='US precios suc')
        for convenio, _ in Cita.CONVENIO_CHOICES:
            for habil in (True, False):
                PrecioEstudio.objects.create(tipo_estudio=otro, convenio=convenio, horario_habil=habil, precio=Q('50'))
        combo = Combo.objects.create(nombre='Combo sucursal')
        combo.estudios.set([self.rx, otro])
        combo.sincronizar_tipo_estudio()
        combo.refresh_from_db()

        self._guardar('120')

        espejo = TipoEstudio.objects.get(pk=combo.tipo_estudio_generado_id)
        self.assertEqual(espejo.precio_para(Cita.CONVENIO_PRIVADO, True), Q('150'))
        self.assertEqual(espejo.precio_para(Cita.CONVENIO_PRIVADO, True, sucursal=self.norte), Q('170'))

    def test_el_panel_financiero_usa_el_precio_de_cada_sucursal(self):
        self._guardar('120')
        crear_cita(self.admin, tipo_estudio=self.rx, sucursal=self.norte, estado=Cita.ESTADO_PROCESADA)
        crear_cita(
            self.admin, tipo_estudio=self.rx, sucursal=self.principal, estado=Cita.ESTADO_PROCESADA,
            paciente=crear_paciente(dpi='9191919191912'),
        )

        datos = finanzas.calcular(finanzas.leer_filtros({'periodo': 'hoy'}))

        self.assertEqual(datos['kpi']['produccion'], Q('220'))

    def test_solo_el_administrador(self):
        recep = crear_usuario('recep_precios_suc', rol=Usuario.ROL_RECEPCIONISTA)
        self.client.force_login(recep)

        self.assertEqual(self._guardar('1').status_code, 302)
        self.assertFalse(PrecioEstudio.objects.filter(sucursal=self.norte).exists())

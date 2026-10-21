"""Columnas "Técnico" y "Médico referente" del reporte diario."""
import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from pacientes.models import Cita, ImagenEstudio, MedicoTratante, OrdenTrabajo, ReporteDiario, TipoEstudio
from pacientes.tests import Usuario, crear_cita, crear_paciente, crear_usuario


class ColumnasReporteDiarioTests(TestCase):
    def setUp(self):
        self.recep = crear_usuario('recep_cols', rol=Usuario.ROL_RECEPCIONISTA)
        self.ayer = timezone.localdate() - datetime.timedelta(days=1)
        self.estudio = TipoEstudio.objects.create(nombre='RX columnas')
        self.medico = MedicoTratante.objects.create(nombre='Dr. Tratante', tipo=MedicoTratante.TIPO_PRIVADO)
        self.otro = MedicoTratante.objects.create(nombre='Dra. Otra', tipo=MedicoTratante.TIPO_AMBOS)
        self.cita = crear_cita(
            self.recep, tipo_estudio=self.estudio, fecha=self.ayer, estado=Cita.ESTADO_PROCESADA,
            medico_tratante=self.medico,
        )
        self.reporte = ReporteDiario.de_cita(self.cita)[0]
        self.url = reverse('ver_reporte_diario', args=['privado', self.ayer.isoformat()])
        self.client.force_login(self.recep)

    def _imagen(self, orden, tecnico):
        return ImagenEstudio.objects.create(
            orden=orden, tipo_estudio=self.estudio, subida_por=tecnico,
            archivo=SimpleUploadedFile('i.jpg', b'\xff\xd8\xff\xe0x', content_type='image/jpeg'),
        )

    def test_el_medico_referente_es_el_medico_tratante(self):
        respuesta = self.client.get(self.url)

        fila = respuesta.context['filas'][0]
        self.assertEqual(fila['medico_referente'], 'Dr. Tratante')
        self.assertContains(respuesta, f'name="medico_tratante_{self.cita.id}"')
        self.assertContains(respuesta, f'<option value="{self.medico.id}" selected>')

    def test_cambiar_el_medico_desde_el_reporte(self):
        self.client.post(self.url, {f'medico_tratante_{self.cita.id}': str(self.otro.id)})
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.medico_tratante, self.otro)

        self.client.post(self.url, {f'medico_tratante_{self.cita.id}': ''})
        self.cita.refresh_from_db()
        self.assertIsNone(self.cita.medico_tratante)

    def test_el_tecnico_es_quien_subio_las_imagenes(self):
        tec_a = crear_usuario('tec_a', rol=Usuario.ROL_TECNICO_IMAGENES, first_name='Ana')
        tec_b = crear_usuario('tec_b', rol=Usuario.ROL_TECNICO_IMAGENES, first_name='Beto')
        orden = OrdenTrabajo.objects.create(cita=self.cita, motivo='x', creada_por=self.recep)
        self._imagen(orden, tec_a)
        self._imagen(orden, tec_b)
        self._imagen(orden, tec_a)

        fila = self.client.get(self.url).context['filas'][0]

        self.assertEqual(fila['tecnico'], 'Ana, Beto')
        self.assertFalse(fila['tecnico_pendiente'])

    def test_sin_imagenes_el_tecnico_queda_pendiente(self):
        respuesta = self.client.get(self.url)

        self.assertTrue(respuesta.context['filas'][0]['tecnico_pendiente'])
        self.assertContains(respuesta, 'Pendiente')

    def test_un_texto_viejo_se_sigue_mostrando_si_no_hay_medico_tratante(self):
        cita = crear_cita(
            self.recep, paciente=crear_paciente(dpi='8080808080801'), tipo_estudio=self.estudio,
            fecha=self.ayer, estado=Cita.ESTADO_PROCESADA, medico_referente='Dr. Antiguo',
        )

        filas = self.client.get(self.url).context['filas']

        fila = next(f for f in filas if f['cita_id'] == cita.id)
        self.assertEqual(fila['medico_referente'], 'Dr. Antiguo')


class OrdenEstudiosRealizadosTests(TestCase):
    """"Estudios realizados": primero el último paciente al que se le hizo un estudio."""

    def test_el_ultimo_paciente_atendido_aparece_primero(self):
        recep = crear_usuario('recep_orden_hist', rol=Usuario.ROL_RECEPCIONISTA)
        hoy = timezone.localdate()
        antiguo = crear_paciente(dpi='8181818181801', nombre='Aaron')
        reciente = crear_paciente(dpi='8181818181802', nombre='Zoe')
        de_hoy_temprano = crear_paciente(dpi='8181818181803', nombre='Beto')
        crear_cita(recep, paciente=antiguo, fecha=hoy - datetime.timedelta(days=3), estado=Cita.ESTADO_PROCESADA)
        crear_cita(recep, paciente=reciente, fecha=hoy, hora=datetime.time(15, 0), estado=Cita.ESTADO_EN_PROCESO)
        crear_cita(recep, paciente=de_hoy_temprano, fecha=hoy, hora=datetime.time(8, 0), estado=Cita.ESTADO_PROCESADA)
        # Un estudio viejo de Zoe no la baja: cuenta el más reciente.
        crear_cita(recep, paciente=reciente, fecha=hoy - datetime.timedelta(days=10), estado=Cita.ESTADO_PROCESADA)
        self.client.force_login(recep)

        pacientes = self.client.get(reverse('historial_pacientes')).context['pacientes']

        self.assertEqual([p.nombre for p in pacientes], ['Zoe', 'Beto', 'Aaron'])


class EnvioSinPagoIgssTests(TestCase):
    """Solo Privado exige el pago antes de enviar resultados; COEX y Emergencia IGSS no."""

    def setUp(self):
        from pacientes.models import Cobro
        self.recep = crear_usuario('recep_envio_igss', rol=Usuario.ROL_RECEPCIONISTA)
        self.Cobro = Cobro

    def _cita_con_cobro_pendiente(self, convenio, dpi):
        cita = crear_cita(self.recep, convenio=convenio, estado=Cita.ESTADO_PROCESADA, paciente=crear_paciente(dpi=dpi))
        OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.recep)
        self.Cobro.objects.create(cita=cita)
        return Cita.objects.get(pk=cita.pk)

    def test_privado_con_cobro_pendiente_no_se_envia(self):
        cita = self._cita_con_cobro_pendiente(Cita.CONVENIO_PRIVADO, '8282828282801')
        self.assertTrue(cita.cobro_bloquea_envio)

    def test_coex_y_emergencia_igss_se_envian_sin_pago(self):
        for convenio, dpi in ((Cita.CONVENIO_COEX, '8282828282802'), (Cita.CONVENIO_EMERGENCIA_IGSS, '8282828282803')):
            cita = self._cita_con_cobro_pendiente(convenio, dpi)
            self.assertFalse(cita.cobro_bloquea_envio, convenio)

    def test_el_historial_ofrece_enviar_y_qr_en_igss_con_cobro_pendiente(self):
        cita = self._cita_con_cobro_pendiente(Cita.CONVENIO_COEX, '8282828282804')
        self.client.force_login(self.recep)

        respuesta = self.client.get(reverse('historial_paciente', args=[cita.paciente_id]))

        self.assertNotContains(respuesta, 'No se puede enviar el estudio')
        self.assertContains(respuesta, reverse('qr_estudio', args=[cita.id]))
        self.assertContains(respuesta, reverse('enviar_estudio', args=[cita.id]))


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

"""Red de seguridad: recorre TODAS las URLs de la aplicación (GET) con cada
rol y comprueba que ninguna devuelva un error 500. Sirve para detectar vistas
rotas, tablas inexistentes o plantillas que revientan en tiempo de ejecución.
"""
import datetime
import re

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import urls as accounts_urls
from pacientes import urls as pacientes_urls
from pacientes.models import (
    Cita,
    ImagenEstudio,
    Notificacion,
    OrdenTrabajo,
    Paciente,
    ReporteDiario,
    Ticket,
    TipoEstudio,
)

Usuario = get_user_model()

ESTADOS_ACEPTABLES = {200, 301, 302, 400, 403, 404, 405}


class SmokeTodasLasUrlsTests(TestCase):

    def setUp(self):
        self.recepcionista = Usuario.objects.create_user(
            'smoke_recep', password='x', rol=Usuario.ROL_RECEPCIONISTA,
        )
        self.tecnico = Usuario.objects.create_user(
            'smoke_tec', password='x', rol=Usuario.ROL_TECNICO_IMAGENES,
        )
        self.radiologo = Usuario.objects.create_user(
            'smoke_rad', password='x', rol=Usuario.ROL_MEDICO_RADIOLOGO,
        )
        self.admin_fin = Usuario.objects.create_user(
            'smoke_admin_fin', password='x', rol=Usuario.ROL_ADMINISTRADOR_FINANCIERO,
        )
        self.admin = Usuario.objects.create_user(
            'smoke_admin', password='x', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True,
        )

        self.paciente = Paciente.objects.create(
            dpi='1231231231231', nombre='Ana', apellido='López',
            sexo=Paciente.SEXO_FEMENINO, fecha_nacimiento=datetime.date(1980, 4, 10),
        )
        self.estudio = TipoEstudio.objects.create(
            nombre='Radiografía de tórax smoke', modalidad='rx', duracion_minutos=30,
        )
        self.estudio.radiologos.add(self.radiologo)
        self.cita = Cita.objects.create(
            paciente=self.paciente, tipo_estudio=self.estudio, convenio=Cita.CONVENIO_PRIVADO,
            estado=Cita.ESTADO_AGENDADA, fecha=timezone.localdate(),
            hora=datetime.time(9, 0), creada_por=self.recepcionista,
        )
        self.orden = OrdenTrabajo.objects.create(
            cita=self.cita, creada_por=self.recepcionista,
            motivo='Control', informe_texto='Sin hallazgos.',
        )
        self.imagen = ImagenEstudio.objects.create(
            orden=self.orden, subida_por=self.tecnico, seleccionada=True,
            archivo=SimpleUploadedFile(
                'rx.jpg', b'\xff\xd8\xff\xe0' + b'0' * 100, content_type='image/jpeg',
            ),
            archivo_original=SimpleUploadedFile(
                'rx.dcm', b'DICM' + b'1' * 100, content_type='application/dicom',
            ),
        )
        self.ticket = Ticket.objects.create(
            paciente=self.paciente, servicio=Ticket.SERVICIO_COEX,
            registrado_por=self.recepcionista,
        )
        self.notificacion = Notificacion.notificar(
            destinatario=self.recepcionista, tipo=Notificacion.TIPO_CITA_CONFIRMADA,
            mensaje='Notificación de prueba', url='/dashboard/',
        )
        self.reporte = ReporteDiario.objects.create(
            convenio=Cita.CONVENIO_COEX,
            fecha=timezone.localdate() - datetime.timedelta(days=1),
            estado=ReporteDiario.ESTADO_ENVIADO,
        )

        self.mapa_ids = {
            'cita_id': self.cita.id,
            'orden_id': self.orden.id,
            'imagen_id': self.imagen.id,
            'ticket_id': self.ticket.id,
            'estudio_id': self.estudio.id,
            'paciente_id': self.paciente.id,
            'notificacion_id': self.notificacion.id,
            'usuario_id': self.recepcionista.id,
        }

    def _recolectar(self):
        rutas = []
        for app_urls in (accounts_urls.urlpatterns, pacientes_urls.urlpatterns):
            for patron in app_urls:
                if patron.name:
                    rutas.append((patron.name, str(patron.pattern)))
        return rutas

    def _kwargs_desde_ruta(self, ruta):
        kwargs = {}
        for token in re.findall(r'<([^>]+)>', ruta):
            tipo, _, nombre = token.partition(':')
            if nombre in self.mapa_ids:
                kwargs[nombre] = self.mapa_ids[nombre]
            elif nombre == 'fecha':
                kwargs[nombre] = self.reporte.fecha.strftime('%Y-%m-%d')
            elif tipo == 'int':
                kwargs[nombre] = 1
            else:
                kwargs[nombre] = 'coex'
        return kwargs

    def test_get_de_todas_las_urls_sin_errores_500(self):
        fallos = []
        total = 0
        roles = [self.recepcionista, self.tecnico, self.radiologo, self.admin_fin, self.admin]
        for rol in roles:
            for nombre, ruta in self._recolectar():
                url = reverse(nombre, kwargs=self._kwargs_desde_ruta(ruta))
                self.client.force_login(rol)
                respuesta = self.client.get(url)
                total += 1
                if respuesta.status_code >= 500:
                    fallos.append((rol.username, nombre, url, respuesta.status_code))
        self.assertEqual(fallos, [])
        print(f'... smoke: {total} peticiones GET sin errores 500')

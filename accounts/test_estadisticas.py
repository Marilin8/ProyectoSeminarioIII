import datetime

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import estadisticas
from pacientes.models import Cita, ImagenEstudio, InformeEstudio, OrdenTrabajo, Paciente, TipoEstudio

Usuario = get_user_model()


class EstadisticasTests(TestCase):
    def setUp(self):
        self.admin = Usuario.objects.create_user(
            username='admin-est', password='clave-segura-123', rol=Usuario.ROL_ADMINISTRADOR,
        )
        self.hoy = timezone.localdate()
        self.torax = TipoEstudio.objects.create(nombre='Rayos X tórax est')
        self.usg = TipoEstudio.objects.create(nombre='Ultrasonido est')
        self._dpi = 1000000000000

    def _paciente(self):
        self._dpi += 1
        return Paciente.objects.create(
            dpi=str(self._dpi), nombre='P', apellido='Prueba', sexo=Paciente.SEXO_FEMENINO,
            fecha_nacimiento=datetime.date(1990, 1, 1),
        )

    def _cita(self, paciente=None, estudio=None, fecha=None, convenio=Cita.CONVENIO_PRIVADO,
              estado=Cita.ESTADO_PROCESADA, minutos=None):
        cita = Cita.objects.create(
            paciente=paciente or self._paciente(), tipo_estudio=estudio or self.torax,
            convenio=convenio, estado=estado, fecha=fecha or self.hoy,
            hora=datetime.time(9, 0), creada_por=self.admin,
        )
        if minutos is not None:
            llegada = timezone.now() - datetime.timedelta(minutes=minutos)
            cita.hora_llegada = llegada
            cita.save(update_fields=['hora_llegada'])
            orden = OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.admin)
            imagen = ImagenEstudio.objects.create(
                orden=orden, tipo_estudio=cita.tipo_estudio, subida_por=self.admin,
                archivo=SimpleUploadedFile('i.jpg', b'\xff\xd8\xff\xe0x', content_type='image/jpeg'),
            )
            ImagenEstudio.objects.filter(pk=imagen.pk).update(subida_en=timezone.now())
        return cita

    def test_tiempo_promedio_de_atencion_de_hoy(self):
        self._cita(minutos=20)
        self._cita(minutos=40)

        datos = estadisticas.calcular(30, hoy=self.hoy)

        self.assertEqual(datos['kpi']['promedio_hoy'], 30)
        self.assertEqual(datos['kpi']['pacientes_medidos'], 2)
        self.assertTrue(datos['tiempos']['hay_datos'])

    def test_tiempos_fuera_de_rango_no_cuentan(self):
        self._cita(minutos=20)
        self._cita(minutos=60 * 20)  # llegada marcada hace 20 horas: dato erróneo

        datos = estadisticas.calcular(30, hoy=self.hoy)

        self.assertEqual(datos['kpi']['promedio_hoy'], 20)

    def test_estudio_mas_realizado(self):
        self._cita(estudio=self.usg)
        self._cita(estudio=self.usg)
        self._cita(estudio=self.torax)
        self._cita(estudio=self.torax, estado=Cita.ESTADO_AUSENTE)  # no se realizó

        datos = estadisticas.calcular(30, hoy=self.hoy)

        self.assertEqual(datos['estudios']['top']['nombre'], 'Ultrasonido est')
        self.assertEqual(datos['estudios']['total'], 3)

    def test_pacientes_nuevos_privado_vs_igss_por_primera_cita(self):
        recurrente = self._paciente()
        self._cita(paciente=recurrente, fecha=self.hoy - datetime.timedelta(days=400))
        self._cita(paciente=recurrente)  # ya era paciente: no es nuevo
        self._cita(convenio=Cita.CONVENIO_PRIVADO)
        self._cita(convenio=Cita.CONVENIO_COEX)
        self._cita(convenio=Cita.CONVENIO_EMERGENCIA_IGSS)

        datos = estadisticas.calcular(30, hoy=self.hoy)

        self.assertEqual(datos['nuevos']['mes_actual']['privado'], 1)
        self.assertEqual(datos['nuevos']['mes_actual']['igss'], 2)

    def _usuario(self, username, rol, nombre):
        return Usuario.objects.create_user(
            username=username, password='clave-segura-123', rol=rol, first_name=nombre,
        )

    def _atendida_por(self, tecnico, minutos_atencion, radiologo=None, minutos_informe=None):
        ahora = timezone.now()
        cita = self._cita()
        cita.hora_llegada = ahora - datetime.timedelta(minutes=minutos_atencion)
        cita.radiologo = radiologo
        cita.save(update_fields=['hora_llegada', 'radiologo'])
        orden = OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.admin)
        imagen = ImagenEstudio.objects.create(
            orden=orden, tipo_estudio=cita.tipo_estudio, subida_por=tecnico,
            archivo=SimpleUploadedFile('i.jpg', b'\xff\xd8\xff\xe0x', content_type='image/jpeg'),
        )
        ImagenEstudio.objects.filter(pk=imagen.pk).update(subida_en=ahora)
        if radiologo is not None:
            InformeEstudio.objects.create(
                orden=orden, tipo_estudio=cita.tipo_estudio, texto='ok', creado_por=radiologo,
                creado_en=ahora + datetime.timedelta(minutes=minutos_informe),
            )

    def test_ranking_de_tecnicos_y_radiologos(self):
        ana = self._usuario('tec-ana', Usuario.ROL_TECNICO_IMAGENES, 'Ana')
        beto = self._usuario('tec-beto', Usuario.ROL_TECNICO_IMAGENES, 'Beto')
        rosa = self._usuario('rad-rosa', Usuario.ROL_MEDICO_RADIOLOGO, 'Rosa')
        luis = self._usuario('rad-luis', Usuario.ROL_MEDICO_RADIOLOGO, 'Luis')
        self._atendida_por(ana, 10, rosa, 30)
        self._atendida_por(ana, 20, rosa, 90)
        self._atendida_por(beto, 45, luis, 60 * 26)

        personal = estadisticas.calcular(30, hoy=self.hoy)['personal']

        tecnicos = [(f['nombre'], f['minutos'], f.get('etiqueta')) for f in personal['tecnicos']]
        self.assertEqual(tecnicos, [('Ana', 15, 'rapido'), ('Beto', 45, 'lento')])
        radiologos = [(f['nombre'], f['texto']) for f in personal['radiologos']]
        self.assertEqual(radiologos, [('Rosa', '1 h'), ('Luis', '1 d 2 h')])

    def test_formato_duracion(self):
        self.assertEqual(estadisticas.formato_duracion(45), '45 min')
        self.assertEqual(estadisticas.formato_duracion(75), '1 h 15 min')
        self.assertEqual(estadisticas.formato_duracion(60 * 24 * 2), '2 d')

    def test_periodo_invalido_usa_el_de_por_defecto(self):
        self.assertEqual(estadisticas.periodo_valido('abc'), estadisticas.PERIODO_POR_DEFECTO)
        self.assertEqual(estadisticas.periodo_valido('999'), estadisticas.PERIODO_POR_DEFECTO)
        self.assertEqual(estadisticas.periodo_valido('7'), 7)

    def test_el_admin_ve_el_panel_de_estadisticas_y_el_boton_al_menu(self):
        self._cita(minutos=25)
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('dashboard'), {'dias': 7})

        self.assertTemplateUsed(respuesta, 'accounts/dashboard_admin.html')
        self.assertContains(respuesta, 'Tiempo promedio de atención')
        self.assertContains(respuesta, reverse('menu_principal'))

    def test_las_coordenadas_de_las_graficas_usan_punto_decimal(self):
        # En español Django escribe "40,5": eso rompe el SVG y los anchos CSS.
        self._cita(minutos=25, estudio=self.torax)
        self._cita(estudio=self.usg)
        self._cita(estudio=self.usg)
        self._cita(estudio=self.usg)
        self.client.force_login(self.admin)

        html = self.client.get(reverse('dashboard')).content.decode()

        self.assertNotRegex(html, r'(c[xy]|y[12])="[^"]*\d,\d')
        # En points la coma separa x de y; un decimal con coma daría más de una por par.
        self.assertNotRegex(html, r'points="[^"]*\d,\d+,\d')
        self.assertNotRegex(html, r'(width|height):\d+,\d')

    def test_el_menu_principal_muestra_los_botones_y_vuelve_a_estadisticas(self):
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('menu_principal'))

        self.assertTemplateUsed(respuesta, 'accounts/dashboard.html')
        self.assertContains(respuesta, 'Ver estadísticas')

    def test_otros_roles_siguen_viendo_su_menu(self):
        recepcionista = Usuario.objects.create_user(
            username='recep-est', password='clave-segura-123', rol=Usuario.ROL_RECEPCIONISTA,
        )
        self.client.force_login(recepcionista)

        respuesta = self.client.get(reverse('dashboard'))

        self.assertTemplateUsed(respuesta, 'accounts/dashboard.html')
        self.assertNotContains(respuesta, 'Ver estadísticas')

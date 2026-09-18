import base64
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Bitacora, RolAdicional
from pacientes import horarios
from pacientes.forms import AgendarCitaForm, RegistrarTicketForm, validar_telefono_pais
from pacientes.models import (
    Cita,
    Cobro,
    Combo,
    EstudioExtra,
    HistorialPrecioEstudio,
    ImagenEstudio,
    Notificacion,
    OrdenPago,
    OrdenTrabajo,
    Paciente,
    PrecioEstudio,
    Ticket,
    TipoEstudio,
)

Usuario = get_user_model()


def crear_paciente(**kwargs):
    datos = dict(
        dpi='1234567890101',
        nombre='Juana',
        apellido='Pérez',
        sexo=Paciente.SEXO_FEMENINO,
        fecha_nacimiento=datetime.date(1990, 5, 20),
    )
    datos.update(kwargs)
    return Paciente.objects.create(**datos)


def crear_usuario(username='usuario', **kwargs):
    return Usuario.objects.create_user(username=username, password='clave-segura-123', **kwargs)


def crear_cita(usuario, paciente=None, tipo_estudio=None, **kwargs):
    paciente = paciente or crear_paciente()
    if tipo_estudio is None:
        tipo_estudio, _ = TipoEstudio.objects.get_or_create(nombre='Radiografía de tórax')
    datos = dict(
        paciente=paciente,
        tipo_estudio=tipo_estudio,
        convenio=Cita.CONVENIO_PRIVADO,
        estado=Cita.ESTADO_AGENDADA,
        fecha=timezone.localdate(),
        hora=datetime.time(9, 0),
        creada_por=usuario,
    )
    datos.update(kwargs)
    return Cita.objects.create(**datos)


class TelefonoPaisValidatorTests(TestCase):
    """Validador del teléfono con selector de país (ver
    includes/telefono_pais.html): exige la cantidad de dígitos exacta del
    país cuando el valor trae el formato "+código dígitos", pero no rompe
    los teléfonos viejos guardados como solo dígitos sueltos."""

    def test_acepta_vacio(self):
        validar_telefono_pais('')
        validar_telefono_pais(None)

    def test_acepta_cantidad_correcta_de_digitos(self):
        validar_telefono_pais('+502 12345678')  # Guatemala, 8 dígitos
        validar_telefono_pais('+52 1234567890')  # México, 10 dígitos

    def test_rechaza_cantidad_incorrecta_de_digitos(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            validar_telefono_pais('+502 1234567')  # Guatemala, 7 en vez de 8

    def test_rechaza_codigo_de_pais_no_reconocido(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            validar_telefono_pais('+999 12345678')

    def test_no_rompe_telefonos_viejos_sin_prefijo(self):
        # Guardados antes de que existiera el selector de país: solo
        # dígitos, sin "+código". Se aceptan tal cual.
        validar_telefono_pais('55551234')


class FlujoPrivadoTests(TestCase):
    """Flujo del módulo Privado: recepción agenda de una vez (AGENDADA, sin
    revisión del radiólogo), se auto-asigna radiólogo, avisa (sin bloquear)
    si el turno ya está ocupado -> cola de procesamiento -> llegada -> orden."""

    def setUp(self):
        self.recepcionista = crear_usuario('recep_priv', rol=Usuario.ROL_RECEPCIONISTA)
        self.radiologo = crear_usuario('rad_priv', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.estudio = TipoEstudio.objects.create(nombre='Radiografía de tórax privada')
        self.estudio.radiologos.add(self.radiologo)
        self.fecha = timezone.localdate() + datetime.timedelta(days=2)

    def _agendar(self, hora='10:00', dpi='9090909090901', nombre='Marco'):
        self.client.force_login(self.recepcionista)
        return self.client.post(reverse('agendar_cita_privado'), {
            'dpi': dpi,
            'nombre': nombre,
            'apellido': 'Privado',
            'sexo': Paciente.SEXO_MASCULINO,
            'telefono': '55551234',
            'correo': '',
            'fecha_nacimiento': '1990-01-01',
            'tipo_estudio': self.estudio.id,
            'fecha': self.fecha.isoformat(),
            'hora': hora,
            'motivo': 'Control',
        }, follow=True)

    def test_agendar_privado_agenda_directo_y_autoasigna_radiologo(self):
        self._agendar()
        cita = Cita.objects.get(paciente__dpi='9090909090901')
        self.assertEqual(cita.convenio, Cita.CONVENIO_PRIVADO)
        self.assertEqual(cita.estado, Cita.ESTADO_AGENDADA)
        self.assertEqual(cita.radiologo, self.radiologo)

    def test_agendar_privado_no_duplica_estudio_mismo_paciente_y_horario(self):
        self._agendar()

        respuesta = self._agendar()

        self.assertEqual(
            Cita.objects.filter(
                paciente__dpi='9090909090901',
                tipo_estudio=self.estudio,
                fecha=self.fecha,
                hora='10:00',
            ).count(),
            1,
        )
        self.assertContains(respuesta, 'ya tiene agendado ese mismo estudio')

    def test_agendar_privado_con_varios_radiologos_exige_elegir(self):
        otro = crear_usuario('rad_priv_2', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.estudio.radiologos.add(otro)

        respuesta = self._agendar()
        self.assertContains(respuesta, 'varios radiólogos')
        self.assertFalse(Cita.objects.filter(paciente__dpi='9090909090901').exists())

        self.client.force_login(self.recepcionista)
        self.client.post(reverse('agendar_cita_privado'), {
            'dpi': '9090909090901', 'nombre': 'Marco', 'apellido': 'Privado',
            'sexo': Paciente.SEXO_MASCULINO, 'telefono': '55551234', 'correo': '',
            'fecha_nacimiento': '1990-01-01', 'tipo_estudio': self.estudio.id,
            'radiologo': otro.id, 'fecha': self.fecha.isoformat(), 'hora': '10:00',
            'motivo': 'Control',
        })
        cita = Cita.objects.get(paciente__dpi='9090909090901')
        self.assertEqual(cita.radiologo, otro)

    def test_privado_no_aparece_en_solicitudes_del_radiologo(self):
        self._agendar()
        self.client.force_login(self.radiologo)
        lista = self.client.get(reverse('solicitudes_pendientes'))
        self.assertNotContains(lista, 'Marco')

    def test_agendar_privado_avisa_si_turno_ocupado(self):
        crear_cita(
            self.recepcionista, tipo_estudio=self.estudio,
            fecha=self.fecha, hora=datetime.time(10, 0),
            paciente=crear_paciente(dpi='1010101010101'),
        )
        respuesta = self._agendar(dpi='2020202020202', nombre='Segundo')
        self.assertContains(respuesta, 'ya estaba ocupado')
        self.assertEqual(Cita.objects.filter(paciente__dpi='2020202020202').count(), 1)

    def test_cola_de_procesamiento_llegada_y_orden(self):
        self._agendar()
        cita = Cita.objects.get(paciente__dpi='9090909090901')

        self.client.force_login(self.recepcionista)
        self.client.post(reverse('marcar_llegada_privado', args=[cita.id]))
        cita.refresh_from_db()
        self.assertIsNotNone(cita.hora_llegada)

        self.client.post(reverse('generar_orden_privado', args=[cita.id]), {'motivo': 'Rx de control'})
        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.ESTADO_EN_PROCESO)
        self.assertTrue(OrdenTrabajo.objects.filter(cita=cita).exists())

    def test_marcar_llegada_privado_genera_ticket_normal(self):
        self._agendar()
        cita = Cita.objects.get(paciente__dpi='9090909090901')
        self.client.force_login(self.recepcionista)

        self.client.post(reverse('marcar_llegada_privado', args=[cita.id]))

        ticket = Ticket.objects.get(cita=cita)
        self.assertEqual(ticket.servicio, Cita.CONVENIO_PRIVADO)
        self.assertEqual(ticket.prioridad, Ticket.PRIORIDAD_NORMAL)
        self.assertEqual(ticket.estado, Ticket.ESTADO_EN_ESPERA)

    def test_marcar_llegada_privado_puede_adelantar_el_turno(self):
        p1, p2 = crear_paciente(dpi='9191919191911'), crear_paciente(dpi='9292929292921')
        cita_coex = crear_cita(
            self.recepcionista, paciente=p1, tipo_estudio=self.estudio,
            convenio=Cita.CONVENIO_COEX, fecha=self.fecha, hora=datetime.time(9, 0),
        )
        cita_privado = crear_cita(
            self.recepcionista, paciente=p2, tipo_estudio=self.estudio,
            convenio=Cita.CONVENIO_PRIVADO, fecha=self.fecha, hora=datetime.time(9, 30),
        )
        self.client.force_login(self.recepcionista)

        self.client.post(reverse('marcar_llegada_coex', args=[cita_coex.id]))
        self.client.post(reverse('marcar_llegada_privado', args=[cita_privado.id]), {'adelantar': '1'})

        ticket_coex = Ticket.objects.get(cita=cita_coex)
        ticket_privado = Ticket.objects.get(cita=cita_privado)
        cola = list(Ticket.objects.filter(estado=Ticket.ESTADO_EN_ESPERA).order_by('-prioridad', 'orden'))
        self.assertEqual(cola, [ticket_privado, ticket_coex])
        # El número de turno oficial no cambia aunque se haya adelantado.
        self.assertEqual(ticket_privado.numero, 2)


@override_settings(VERIFICAR_CORREO_EXISTENTE=True)
class VerificacionCorreoAgendarPrivadoTests(TestCase):
    """En el módulo Privado el correo es opcional (a diferencia de COEX y
    Emergencia IGSS, donde es obligatorio) -- confirma que dejarlo en blanco
    no dispara ninguna consulta DNS, y que escribir uno si lo verifica y
    avisa cuando el dominio no puede recibir correo."""

    def setUp(self):
        self.recepcionista = crear_usuario('recep_correo', rol=Usuario.ROL_RECEPCIONISTA)
        self.radiologo = crear_usuario('rad_correo', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.estudio = TipoEstudio.objects.create(nombre='Radiografía de tórax verificación')
        self.estudio.radiologos.add(self.radiologo)
        self.fecha = timezone.localdate() + datetime.timedelta(days=2)
        self.client.force_login(self.recepcionista)

    def _agendar(self, correo, dpi='8080808080801'):
        return self.client.post(reverse('agendar_cita_privado'), {
            'dpi': dpi, 'nombre': 'Marco', 'apellido': 'Privado',
            'sexo': Paciente.SEXO_MASCULINO, 'telefono': '55551234', 'correo': correo,
            'fecha_nacimiento': '1990-01-01', 'tipo_estudio': self.estudio.id,
            'fecha': self.fecha.isoformat(), 'hora': '10:00', 'motivo': 'Control',
        }, follow=True)

    @patch('clinica.validators.dominio_puede_recibir_correo')
    def test_correo_en_blanco_no_consulta_dns(self, mock_check):
        respuesta = self._agendar(correo='')

        mock_check.assert_not_called()
        self.assertTrue(Cita.objects.filter(paciente__dpi='8080808080801').exists())
        self.assertNotContains(respuesta, 'no fue encontrado')

    @patch('clinica.validators.dominio_puede_recibir_correo')
    def test_correo_escrito_que_no_existe_bloquea_y_avisa(self, mock_check):
        mock_check.return_value = False

        respuesta = self._agendar(correo='no-existe@dominio-inventado.com')

        mock_check.assert_called_once_with('dominio-inventado.com')
        self.assertFalse(Cita.objects.filter(paciente__dpi='8080808080801').exists())
        self.assertContains(respuesta, 'no fue encontrado')

    @patch('clinica.validators.dominio_puede_recibir_correo')
    def test_correo_escrito_que_si_existe_agenda_normal(self, mock_check):
        mock_check.return_value = True

        respuesta = self._agendar(correo='si-existe@example.com')

        mock_check.assert_called_once_with('example.com')
        self.assertTrue(Cita.objects.filter(paciente__dpi='8080808080801').exists())
        self.assertNotContains(respuesta, 'no fue encontrado')


class VisorEstudioTests(TestCase):
    """Visor web público del estudio: link estilo PACS
    (/visor/?studyId=<id>&ac=<token base64>) + gate de últimos 4 dígitos del
    DPI + imágenes servidas solo con sesión autorizada."""

    def setUp(self):
        self.recepcionista = crear_usuario('recep_visor', rol=Usuario.ROL_RECEPCIONISTA)
        self.tecnico = crear_usuario('tec_visor', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.paciente = crear_paciente(dpi='1122334455667', correo='p@correo.com')
        self.estudio = TipoEstudio.objects.create(nombre='Radiografía de tórax visor')
        self.cita = crear_cita(
            self.recepcionista, paciente=self.paciente, tipo_estudio=self.estudio,
            estado=Cita.ESTADO_PROCESADA,
        )
        self.orden = OrdenTrabajo.objects.create(
            cita=self.cita, motivo='x', creada_por=self.recepcionista,
            informe_texto='Sin hallazgos.', resultados_enviados_en=timezone.now(),
        )
        self.imagen = ImagenEstudio.objects.create(
            orden=self.orden, subida_por=self.tecnico, seleccionada=True,
            archivo=SimpleUploadedFile('img.jpg', b'\xff\xd8\xff\xe0fake', content_type='image/jpeg'),
        )
        token = self.orden.asegurar_token_publico()
        ac = base64.urlsafe_b64encode(str(token).encode()).decode().rstrip('=')
        self.url = f"{reverse('visor_estudio')}?studyId={self.orden.id}&tab=images&ac={ac}"
        self.url_img = reverse('visor_imagen', args=[self.orden.id, self.imagen.id])

    def test_sin_dpi_muestra_el_gate(self):
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'últimos 4')

    def test_link_sin_ac_valido_da_404(self):
        respuesta = self.client.get(f"{reverse('visor_estudio')}?studyId={self.orden.id}&ac=basura")
        self.assertEqual(respuesta.status_code, 404)

    def test_dpi_incorrecto_no_autoriza(self):
        respuesta = self.client.post(self.url, {'dpi_ultimos': '0000'})
        self.assertContains(respuesta, 'no coinciden')
        self.assertNotContains(respuesta, self.estudio.nombre)

    def test_dpi_correcto_muestra_estudio_e_imagenes(self):
        self.client.post(self.url, {'dpi_ultimos': '5667'})
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, self.estudio.nombre)
        self.assertContains(respuesta, self.url_img)
        self.assertEqual(self.client.get(self.url_img).status_code, 200)

    def test_imagen_sin_sesion_autorizada_da_404(self):
        self.assertEqual(self.client.get(self.url_img).status_code, 404)

    def test_orden_sin_resultados_enviados_no_es_accesible(self):
        self.orden.resultados_enviados_en = None
        self.orden.save(update_fields=['resultados_enviados_en'])
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_se_bloquea_tras_varios_intentos(self):
        for _ in range(5):
            self.client.post(self.url, {'dpi_ultimos': '9999'})
        respuesta = self.client.post(self.url, {'dpi_ultimos': '5667'})
        self.assertContains(respuesta, 'Demasiados intentos')
        self.assertNotContains(respuesta, self.estudio.nombre)


class PacienteModelTests(TestCase):

    def test_edad_en_antes_de_su_cumpleanos_no_cuenta_el_anio_actual(self):
        paciente = crear_paciente(fecha_nacimiento=datetime.date(2000, 8, 20))
        self.assertEqual(paciente.edad_en(datetime.date(2026, 8, 7)), 25)

    def test_edad_en_el_dia_de_su_cumpleanos_ya_cuenta_el_anio(self):
        paciente = crear_paciente(fecha_nacimiento=datetime.date(2000, 8, 20))
        self.assertEqual(paciente.edad_en(datetime.date(2026, 8, 20)), 26)

    def test_str_incluye_nombre_apellido_y_dpi(self):
        paciente = crear_paciente(nombre='Juana', apellido='Pérez', dpi='1111222233330')
        self.assertEqual(str(paciente), 'Juana Pérez (1111222233330)')

    def test_el_sistema_asigna_un_expediente_correlativo(self):
        p1 = crear_paciente(dpi='1000000000001')
        p2 = crear_paciente(dpi='1000000000002')
        self.assertTrue(p1.expediente)
        self.assertEqual(len(p1.expediente), 6)
        self.assertEqual(int(p2.expediente), int(p1.expediente) + 1)

    def test_no_reasigna_el_expediente_al_editar(self):
        paciente = crear_paciente(dpi='1000000000003')
        original = paciente.expediente
        paciente.telefono = '55550000'
        paciente.save()
        paciente.refresh_from_db()
        self.assertEqual(paciente.expediente, original)


class CitaModelTests(TestCase):

    def setUp(self):
        self.usuario = crear_usuario('recepcionista1')

    def test_esta_tarde_es_falso_si_aun_no_vence_la_tolerancia(self):
        ahora = timezone.localtime()
        cita = crear_cita(
            self.usuario,
            estado=Cita.ESTADO_AGENDADA,
            fecha=ahora.date(),
            hora=(ahora + datetime.timedelta(minutes=10)).time(),
        )
        self.assertFalse(cita.esta_tarde)

    def test_esta_tarde_es_verdadero_pasada_la_tolerancia_sin_llegada(self):
        ahora = timezone.localtime()
        hace_una_hora = (ahora - datetime.timedelta(hours=1))
        cita = crear_cita(
            self.usuario,
            estado=Cita.ESTADO_AGENDADA,
            fecha=hace_una_hora.date(),
            hora=hace_una_hora.time(),
        )
        self.assertTrue(cita.esta_tarde)

    def test_esta_tarde_es_falso_si_ya_marco_llegada(self):
        ahora = timezone.localtime()
        hace_una_hora = ahora - datetime.timedelta(hours=1)
        cita = crear_cita(
            self.usuario,
            estado=Cita.ESTADO_AGENDADA,
            fecha=hace_una_hora.date(),
            hora=hace_una_hora.time(),
            hora_llegada=ahora,
        )
        self.assertFalse(cita.esta_tarde)

    def test_esta_tarde_es_falso_si_el_estado_no_es_agendada(self):
        ahora = timezone.localtime()
        hace_una_hora = ahora - datetime.timedelta(hours=1)
        cita = crear_cita(
            self.usuario,
            estado=Cita.ESTADO_PROCESADA,
            fecha=hace_una_hora.date(),
            hora=hace_una_hora.time(),
        )
        self.assertFalse(cita.esta_tarde)

    def test_marcar_ausentes_vencidas_actualiza_citas_de_dias_anteriores(self):
        ayer = timezone.localdate() - datetime.timedelta(days=1)
        cita = crear_cita(self.usuario, estado=Cita.ESTADO_AGENDADA, fecha=ayer, hora=datetime.time(9, 0))

        actualizadas = Cita.marcar_ausentes_vencidas()

        cita.refresh_from_db()
        self.assertEqual(actualizadas, 1)
        self.assertEqual(cita.estado, Cita.ESTADO_AUSENTE)

    def test_marcar_ausentes_vencidas_no_toca_citas_ya_procesadas(self):
        ayer = timezone.localdate() - datetime.timedelta(days=1)
        cita = crear_cita(self.usuario, estado=Cita.ESTADO_PROCESADA, fecha=ayer, hora=datetime.time(9, 0))

        Cita.marcar_ausentes_vencidas()

        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.ESTADO_PROCESADA)

    def test_marcar_ausentes_vencidas_no_toca_citas_futuras(self):
        manana = timezone.localdate() + datetime.timedelta(days=1)
        cita = crear_cita(self.usuario, estado=Cita.ESTADO_AGENDADA, fecha=manana, hora=datetime.time(9, 0))

        Cita.marcar_ausentes_vencidas()

        cita.refresh_from_db()
        self.assertEqual(cita.estado, Cita.ESTADO_AGENDADA)


class OrdenTrabajoModelTests(TestCase):

    def setUp(self):
        self.usuario = crear_usuario('tecnico1')
        self.cita = crear_cita(self.usuario, fecha=datetime.date(2026, 1, 10))

    def test_tiene_informe_es_falso_sin_texto_ni_archivo(self):
        orden = OrdenTrabajo.objects.create(cita=self.cita, motivo='Dolor torácico', creada_por=self.usuario)
        self.assertFalse(orden.tiene_informe)

    def test_tiene_informe_es_verdadero_con_texto(self):
        orden = OrdenTrabajo.objects.create(
            cita=self.cita, motivo='Dolor torácico', creada_por=self.usuario, informe_texto='Sin hallazgos.',
        )
        self.assertTrue(orden.tiene_informe)

    def test_tiene_imagenes_refleja_las_imagenes_asociadas(self):
        orden = OrdenTrabajo.objects.create(cita=self.cita, motivo='Control', creada_por=self.usuario)
        self.assertFalse(orden.tiene_imagenes)

        ImagenEstudio.objects.create(
            orden=orden,
            archivo=SimpleUploadedFile('rx.jpg', b'contenido-falso-de-imagen'),
            subida_por=self.usuario,
        )
        self.assertTrue(orden.tiene_imagenes)

    def test_edad_paciente_usa_la_fecha_de_la_cita_no_la_de_hoy(self):
        paciente = crear_paciente(dpi='9999888877776', fecha_nacimiento=datetime.date(2000, 6, 1))
        cita = crear_cita(self.usuario, paciente=paciente, fecha=datetime.date(2020, 1, 10))
        orden = OrdenTrabajo.objects.create(cita=cita, motivo='Control', creada_por=self.usuario)

        self.assertEqual(orden.edad_paciente, 19)


class CalendarioRadiologoTests(TestCase):
    """El selector de radiólogo del calendario: al elegir uno, el calendario
    muestra solo la agenda de ese radiólogo."""

    def setUp(self):
        self.recepcion = crear_usuario('recep_cal', rol=Usuario.ROL_RECEPCIONISTA)
        self.client.force_login(self.recepcion)
        self.rad1 = crear_usuario('rad_uno', rol=Usuario.ROL_MEDICO_RADIOLOGO, first_name='Radiologo', last_name='Uno')
        self.rad2 = crear_usuario('rad_dos', rol=Usuario.ROL_MEDICO_RADIOLOGO, first_name='Radiologo', last_name='Dos')
        self.estudio = TipoEstudio.objects.create(nombre='RX cal')
        manana = horarios.inicio_semana(timezone.localdate()) + datetime.timedelta(days=1)
        self.dia = manana
        self.cita1 = crear_cita(
            self.recepcion, tipo_estudio=self.estudio, convenio=Cita.CONVENIO_COEX,
            estado=Cita.ESTADO_AGENDADA, radiologo=self.rad1, fecha=self.dia,
            hora=datetime.time(8, 0), paciente=crear_paciente(dpi='1112223334445'),
        )
        self.cita2 = crear_cita(
            self.recepcion, tipo_estudio=self.estudio, convenio=Cita.CONVENIO_COEX,
            estado=Cita.ESTADO_AGENDADA, radiologo=self.rad2, fecha=self.dia,
            hora=datetime.time(9, 0), paciente=crear_paciente(dpi='5556667778889'),
        )

    def _celda(self, respuesta, hora):
        for fila in respuesta.context['filas']:
            if fila['hora'] == hora:
                return next(c for c in fila['celdas'] if c['dia'] == self.dia)
        raise AssertionError('hora no encontrada')

    def test_sin_filtro_ve_las_citas_de_todos(self):
        r = self.client.get(reverse('calendario_coex'), {'semana': self.dia.isoformat()})
        self.assertTrue(self._celda(r, datetime.time(8, 0))['asignado'])
        self.assertTrue(self._celda(r, datetime.time(9, 0))['asignado'])

    def test_filtrando_por_radiologo_solo_ve_su_agenda(self):
        r = self.client.get(reverse('calendario_coex'), {
            'semana': self.dia.isoformat(), 'radiologo': self.rad1.id,
        })
        self.assertEqual(r.context['radiologo_seleccionado'], self.rad1)
        self.assertTrue(self._celda(r, datetime.time(8, 0))['asignado'])   # cita del rad1
        celda9 = self._celda(r, datetime.time(9, 0))
        self.assertFalse(celda9['asignado'])   # la cita del rad2 no aparece
        self.assertFalse(celda9['ocupado'])

    def test_celda_ocupada_trae_el_detalle_de_las_citas(self):
        # otra cita a la misma hora que cita1 (8:00), otro paciente/estudio
        crear_cita(
            self.recepcion, tipo_estudio=self.estudio, convenio=Cita.CONVENIO_PRIVADO,
            estado=Cita.ESTADO_AGENDADA, radiologo=self.rad2, fecha=self.dia,
            hora=datetime.time(8, 0), paciente=crear_paciente(dpi='7778889990001'),
        )
        r = self.client.get(reverse('calendario_coex'), {'semana': self.dia.isoformat()})
        celda = self._celda(r, datetime.time(8, 0))
        self.assertEqual(len(celda['citas']), 2)
        estudios = {c['estudio'] for c in celda['citas']}
        self.assertEqual(estudios, {'RX cal'})
        radiologos = {c['radiologo'] for c in celda['citas']}
        self.assertEqual(radiologos, {'Radiologo Uno', 'Radiologo Dos'})
        clave = f"{self.dia.isoformat()}|08:00"
        self.assertIn(clave, r.context['slots_detalle'])


class ListaEstudiosTests(TestCase):
    """Lista de estudios del admin: buscador, filtro por categoría y
    paginación de 20 por hoja."""

    def setUp(self):
        self.admin = crear_usuario('admin_estudios', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.client.force_login(self.admin)
        # (la migración de catálogo ya deja ~131 estudios en la BD de test)
        for i in range(25):
            TipoEstudio.objects.create(nombre=f'ZZTEST RX {i:02d}', modalidad=TipoEstudio.MODALIDAD_RX)

    def test_pagina_muestra_maximo_20(self):
        r = self.client.get(reverse('lista_estudios'))
        self.assertEqual(len(r.context['pagina'].object_list), 20)

    def test_filtro_y_buscador_combinados_pagina_de_20(self):
        r = self.client.get(reverse('lista_estudios'), {'q': 'ZZTEST', 'modalidad': TipoEstudio.MODALIDAD_RX})
        self.assertEqual(r.context['pagina'].paginator.count, 25)
        self.assertEqual(len(r.context['pagina'].object_list), 20)
        self.assertEqual(r.context['pagina'].paginator.num_pages, 2)

    def test_buscador_por_nombre_exacto(self):
        r = self.client.get(reverse('lista_estudios'), {'q': 'ZZTEST RX 03'})
        self.assertEqual(r.context['pagina'].paginator.count, 1)

    def test_segunda_pagina_del_filtro(self):
        r = self.client.get(reverse('lista_estudios'), {'q': 'ZZTEST', 'page': '2'})
        self.assertEqual(len(r.context['pagina'].object_list), 5)


class PrecioHistoricoTests(TestCase):
    """TipoEstudio.precio_para(fecha=...) / Cita.precio_base: una cita
    vieja debe seguir mostrando el precio que estaba vigente el día en que
    se agendó, aunque después se haya actualizado la tarifa."""

    def setUp(self):
        self.admin = crear_usuario('admin_hist_precio', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.estudio = TipoEstudio.objects.create(nombre='Radiografía histórico')
        self.precio = PrecioEstudio.objects.create(
            tipo_estudio=self.estudio, convenio=Cita.CONVENIO_COEX,
            horario_habil=True, precio=Decimal('300.00'),
        )

    def _cambiar_precio(self, nuevo, cuando):
        """Simula un cambio de precio registrado en un momento puntual
        (auto_now_add no deja pasar `creado_en` al crear, se corrige después)."""
        anterior = self.precio.precio
        cambio = HistorialPrecioEstudio.objects.create(
            tipo_estudio=self.estudio, convenio=Cita.CONVENIO_COEX, horario_habil=True,
            valor_anterior=anterior, valor_nuevo=nuevo, modificado_por=self.admin,
        )
        HistorialPrecioEstudio.objects.filter(pk=cambio.pk).update(
            creado_en=timezone.make_aware(datetime.datetime.combine(cuando, datetime.time(12, 0))),
        )
        self.precio.precio = nuevo
        self.precio.save(update_fields=['precio'])

    def test_precio_para_sin_historial_usa_el_actual(self):
        self.assertEqual(self.estudio.precio_para(Cita.CONVENIO_COEX, True), Decimal('300.00'))
        self.assertEqual(
            self.estudio.precio_para(Cita.CONVENIO_COEX, True, fecha=datetime.date(2026, 1, 1)),
            Decimal('300.00'),
        )

    def test_precio_para_fecha_anterior_al_cambio_usa_el_valor_viejo(self):
        self._cambiar_precio(Decimal('350.00'), cuando=datetime.date(2026, 10, 1))

        # El precio actual ya es 350...
        self.assertEqual(self.estudio.precio_para(Cita.CONVENIO_COEX, True), Decimal('350.00'))
        # ...pero septiembre (antes del cambio de octubre) sigue en 300.
        self.assertEqual(
            self.estudio.precio_para(Cita.CONVENIO_COEX, True, fecha=datetime.date(2026, 9, 15)),
            Decimal('300.00'),
        )

    def test_precio_para_fecha_posterior_al_cambio_usa_el_valor_nuevo(self):
        self._cambiar_precio(Decimal('350.00'), cuando=datetime.date(2026, 10, 1))

        self.assertEqual(
            self.estudio.precio_para(Cita.CONVENIO_COEX, True, fecha=datetime.date(2026, 11, 1)),
            Decimal('350.00'),
        )

    def test_encadena_hacia_atras_con_varios_cambios(self):
        self._cambiar_precio(Decimal('350.00'), cuando=datetime.date(2026, 10, 1))
        self._cambiar_precio(Decimal('400.00'), cuando=datetime.date(2026, 12, 1))

        # Una cita de agosto (antes de ambos cambios) ve el precio original.
        self.assertEqual(
            self.estudio.precio_para(Cita.CONVENIO_COEX, True, fecha=datetime.date(2026, 8, 1)),
            Decimal('300.00'),
        )
        # Entre octubre y diciembre, el precio intermedio.
        self.assertEqual(
            self.estudio.precio_para(Cita.CONVENIO_COEX, True, fecha=datetime.date(2026, 11, 1)),
            Decimal('350.00'),
        )
        # Después de diciembre, el actual.
        self.assertEqual(
            self.estudio.precio_para(Cita.CONVENIO_COEX, True, fecha=datetime.date(2026, 12, 15)),
            Decimal('400.00'),
        )

    def test_cita_precio_base_usa_el_precio_vigente_el_dia_de_la_cita(self):
        recepcionista = crear_usuario('recep_hist_precio', rol=Usuario.ROL_RECEPCIONISTA)
        paciente = crear_paciente(dpi='7777777777701')
        cita_septiembre = crear_cita(
            recepcionista, paciente=paciente, tipo_estudio=self.estudio,
            convenio=Cita.CONVENIO_COEX, fecha=datetime.date(2026, 9, 15), hora=datetime.time(9, 0),
        )

        self._cambiar_precio(Decimal('350.00'), cuando=datetime.date(2026, 10, 1))

        self.assertEqual(cita_septiembre.precio_base, Decimal('300.00'))

        cita_noviembre = crear_cita(
            recepcionista, paciente=paciente, tipo_estudio=self.estudio,
            convenio=Cita.CONVENIO_COEX, fecha=datetime.date(2026, 11, 1), hora=datetime.time(9, 0),
        )
        self.assertEqual(cita_noviembre.precio_base, Decimal('350.00'))


class InformeAnualTests(TestCase):
    """Resumen anual de facturación por mes y convenio (ver
    pacientes.views.informe_anual): usa el precio vigente en la fecha de
    cada cita, no el precio actual del estudio."""

    def setUp(self):
        self.admin = crear_usuario('admin_informe_anual', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.recepcionista = crear_usuario('recep_informe_anual', rol=Usuario.ROL_RECEPCIONISTA)
        self.tecnico = crear_usuario('tec_informe_anual', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.estudio = TipoEstudio.objects.create(nombre='Radiografía informe anual')
        self.precio = PrecioEstudio.objects.create(
            tipo_estudio=self.estudio, convenio=Cita.CONVENIO_COEX,
            horario_habil=True, precio=Decimal('300.00'),
        )
        self.client.force_login(self.admin)

    def _cita(self, fecha, estado=Cita.ESTADO_PROCESADA, convenio=Cita.CONVENIO_COEX, dpi=None):
        paciente = crear_paciente(dpi=dpi or f'{fecha.toordinal():013d}'[-13:])
        return crear_cita(
            self.recepcionista, paciente=paciente, tipo_estudio=self.estudio,
            convenio=convenio, estado=estado, fecha=fecha, hora=datetime.time(9, 0),
        )

    def _cambiar_precio(self, nuevo, cuando):
        cambio = HistorialPrecioEstudio.objects.create(
            tipo_estudio=self.estudio, convenio=Cita.CONVENIO_COEX, horario_habil=True,
            valor_anterior=self.precio.precio, valor_nuevo=nuevo, modificado_por=self.admin,
        )
        HistorialPrecioEstudio.objects.filter(pk=cambio.pk).update(
            creado_en=timezone.make_aware(datetime.datetime.combine(cuando, datetime.time(12, 0))),
        )
        self.precio.precio = nuevo
        self.precio.save(update_fields=['precio'])

    def test_solo_cuenta_citas_no_pendientes_ni_rechazadas(self):
        self._cita(datetime.date(2026, 3, 5), estado=Cita.ESTADO_PROCESADA)
        self._cita(datetime.date(2026, 3, 6), estado=Cita.ESTADO_PENDIENTE)
        self._cita(datetime.date(2026, 3, 7), estado=Cita.ESTADO_RECHAZADA)

        respuesta = self.client.get(reverse('informe_anual'), {'anio': 2026})

        self.assertEqual(respuesta.context['cantidad_anual'], 1)
        self.assertEqual(respuesta.context['total_anual'], Decimal('300.00'))

    def test_ausente_no_suma_al_total_ni_a_la_cantidad(self):
        self._cita(datetime.date(2026, 3, 5), estado=Cita.ESTADO_PROCESADA)
        self._cita(datetime.date(2026, 3, 6), estado=Cita.ESTADO_AUSENTE)

        respuesta = self.client.get(reverse('informe_anual'), {'anio': 2026})

        self.assertEqual(respuesta.context['cantidad_anual'], 1)
        self.assertEqual(respuesta.context['total_anual'], Decimal('300.00'))

    def test_agrupa_por_mes_y_convenio(self):
        self._cita(datetime.date(2026, 1, 10), convenio=Cita.CONVENIO_COEX)
        PrecioEstudio.objects.create(
            tipo_estudio=self.estudio, convenio=Cita.CONVENIO_PRIVADO,
            horario_habil=True, precio=Decimal('500.00'),
        )
        self._cita(datetime.date(2026, 1, 20), convenio=Cita.CONVENIO_PRIVADO)
        self._cita(datetime.date(2026, 2, 1), convenio=Cita.CONVENIO_COEX)

        respuesta = self.client.get(reverse('informe_anual'), {'anio': 2026})

        filas = {f['mes']: f for f in respuesta.context['filas']}
        indice_coex = [c for c, _ in Cita.CONVENIO_CHOICES].index(Cita.CONVENIO_COEX)
        indice_privado = [c for c, _ in Cita.CONVENIO_CHOICES].index(Cita.CONVENIO_PRIVADO)
        self.assertEqual(filas[1]['valores_lista'][indice_coex], Decimal('300.00'))
        self.assertEqual(filas[1]['valores_lista'][indice_privado], Decimal('500.00'))
        self.assertEqual(filas[1]['total'], Decimal('800.00'))
        self.assertEqual(filas[2]['valores_lista'][indice_coex], Decimal('300.00'))
        self.assertEqual(filas[2]['cantidad'], 1)

    def test_usa_precio_vigente_en_la_fecha_de_cada_cita(self):
        """El caso concreto pedido: un estudio a Q300 en septiembre, subido
        a Q350 en octubre -- el informe del año debe reflejar cada mes con
        el precio que tenía en ese momento, no el precio actual."""
        self._cita(datetime.date(2026, 9, 15))
        self._cambiar_precio(Decimal('350.00'), cuando=datetime.date(2026, 10, 1))
        self._cita(datetime.date(2026, 11, 1))

        respuesta = self.client.get(reverse('informe_anual'), {'anio': 2026})

        filas = {f['mes']: f for f in respuesta.context['filas']}
        indice_coex = [c for c, _ in Cita.CONVENIO_CHOICES].index(Cita.CONVENIO_COEX)
        self.assertEqual(filas[9]['valores_lista'][indice_coex], Decimal('300.00'))
        self.assertEqual(filas[11]['valores_lista'][indice_coex], Decimal('350.00'))
        self.assertEqual(respuesta.context['total_anual'], Decimal('650.00'))

    def test_filtra_por_query_param_anio(self):
        self._cita(datetime.date(2025, 6, 1))
        self._cita(datetime.date(2026, 6, 1))

        respuesta_2025 = self.client.get(reverse('informe_anual'), {'anio': 2025})
        respuesta_2026 = self.client.get(reverse('informe_anual'), {'anio': 2026})

        self.assertEqual(respuesta_2025.context['cantidad_anual'], 1)
        self.assertEqual(respuesta_2026.context['cantidad_anual'], 1)

    def test_recepcionista_puede_ver_el_informe(self):
        self.client.force_login(self.recepcionista)
        respuesta = self.client.get(reverse('informe_anual'))
        self.assertEqual(respuesta.status_code, 200)

    def test_tecnico_no_puede_ver_el_informe(self):
        self.client.force_login(self.tecnico)
        respuesta = self.client.get(reverse('informe_anual'))
        self.assertEqual(respuesta.status_code, 302)


class HistorialPrecioEstudioViewTests(TestCase):
    """Auditoría: editar_estudio registra HistorialPrecioEstudio + bitácora
    solo cuando un precio realmente cambia, y la pantalla de historial
    completo lo lista."""

    def setUp(self):
        self.admin = crear_usuario('admin_audit_precio', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.estudio = TipoEstudio.objects.create(
            nombre='Tomografía histórico', modalidad=TipoEstudio.MODALIDAD_TAC,
        )
        PrecioEstudio.objects.create(
            tipo_estudio=self.estudio, convenio=Cita.CONVENIO_COEX,
            horario_habil=True, precio=Decimal('300.00'),
        )
        self.client.force_login(self.admin)

    def _datos_base(self, **overrides):
        datos = {
            'nombre': self.estudio.nombre, 'modalidad': TipoEstudio.MODALIDAD_TAC, 'duracion_minutos': '30',
            'precio_coex_habil': '300.00', 'precio_privado_habil': '0', 'precio_privado_inhabil': '0',
            'precio_emergencia_igss_habil': '0', 'precio_emergencia_igss_inhabil': '0',
        }
        datos.update(overrides)
        return datos

    def test_cambiar_precio_registra_historial_y_bitacora(self):
        self.client.post(
            reverse('editar_estudio', args=[self.estudio.id]),
            self._datos_base(precio_coex_habil='350.00'),
        )

        cambio = HistorialPrecioEstudio.objects.get(tipo_estudio=self.estudio)
        self.assertEqual(cambio.valor_anterior, Decimal('300.00'))
        self.assertEqual(cambio.valor_nuevo, Decimal('350.00'))
        self.assertEqual(cambio.modificado_por, self.admin)
        self.assertTrue(
            Bitacora.objects.filter(accion=Bitacora.ACCION_EDITAR_PRECIO_ESTUDIO).exists()
        )

    def test_guardar_sin_cambiar_precio_no_registra_nada(self):
        self.client.post(reverse('editar_estudio', args=[self.estudio.id]), self._datos_base())

        self.assertFalse(HistorialPrecioEstudio.objects.filter(tipo_estudio=self.estudio).exists())
        self.assertFalse(
            Bitacora.objects.filter(accion=Bitacora.ACCION_EDITAR_PRECIO_ESTUDIO).exists()
        )

    def test_pantalla_de_historial_lista_el_cambio(self):
        # follow=True consume el toast de éxito en la misma respuesta -- si
        # no, ese mensaje queda pendiente en la sesión y aparece también en
        # la siguiente pantalla que se visite, mezclándose con lo que esa
        # pantalla realmente muestra.
        self.client.post(
            reverse('editar_estudio', args=[self.estudio.id]),
            self._datos_base(precio_coex_habil='350.00'),
            follow=True,
        )

        respuesta = self.client.get(reverse('historial_precios_estudio'))

        self.assertContains(respuesta, 'Tomografía histórico')
        # El Decimal se muestra localizado (coma decimal), igual que en
        # lista_estudios.html -- no es un bug de esta pantalla nueva.
        self.assertContains(respuesta, 'Q300,00')
        self.assertContains(respuesta, 'Q350,00')

    def test_buscador_filtra_por_nombre_de_estudio(self):
        self.client.post(
            reverse('editar_estudio', args=[self.estudio.id]),
            self._datos_base(precio_coex_habil='350.00'),
            follow=True,
        )

        respuesta = self.client.get(
            reverse('historial_precios_estudio'), {'q': 'no existe ningún estudio así'},
        )

        self.assertNotContains(respuesta, 'Tomografía histórico')


class HorariosTests(TestCase):

    def test_horarios_disponibles_va_de_inicio_a_fin_cada_15_minutos(self):
        disponibles = horarios.horarios_disponibles()
        self.assertEqual(disponibles[0], datetime.time(7, 0))
        self.assertEqual(disponibles[1], datetime.time(7, 15))
        self.assertEqual(disponibles[-1], datetime.time(16, 45))
        self.assertNotIn(datetime.time(17, 0), disponibles)
        self.assertEqual(len(disponibles), 40)

    def test_rango_ocupado_por_suma_la_duracion_a_la_hora_de_inicio(self):
        inicio, fin = horarios.rango_ocupado_por(
            datetime.date(2026, 8, 12), datetime.time(7, 15), 120,
        )
        self.assertEqual(inicio, datetime.datetime(2026, 8, 12, 7, 15))
        self.assertEqual(fin, datetime.datetime(2026, 8, 12, 9, 15))

    def test_se_cruzan_detecta_solapamiento_de_rangos(self):
        cita_2_horas = horarios.rango_ocupado_por(
            datetime.date(2026, 8, 12), datetime.time(7, 15), 120,
        )
        self.assertTrue(horarios.se_cruzan(
            cita_2_horas, horarios.rango_ocupado_por(datetime.date(2026, 8, 12), datetime.time(8, 0), 15),
        ))
        self.assertFalse(horarios.se_cruzan(
            cita_2_horas, horarios.rango_ocupado_por(datetime.date(2026, 8, 12), datetime.time(9, 15), 15),
        ))

    def test_inicio_semana_devuelve_el_lunes_de_esa_semana(self):
        miercoles = datetime.date(2026, 8, 12)  # miércoles
        self.assertEqual(horarios.inicio_semana(miercoles), datetime.date(2026, 8, 10))

    def test_en_el_pasado_es_verdadero_para_un_momento_ya_ocurrido(self):
        ayer = timezone.localdate() - datetime.timedelta(days=1)
        self.assertTrue(horarios.en_el_pasado(ayer, datetime.time(9, 0)))

    def test_en_el_pasado_es_falso_para_un_momento_futuro(self):
        manana = timezone.localdate() + datetime.timedelta(days=1)
        self.assertFalse(horarios.en_el_pasado(manana, datetime.time(9, 0)))

    def test_fuera_de_ventana_es_falso_dentro_del_limite(self):
        fecha = datetime.date.today() + datetime.timedelta(days=horarios.LIMITE_DIAS_ADELANTE)
        self.assertFalse(horarios.fuera_de_ventana(fecha))

    def test_fuera_de_ventana_es_verdadero_pasado_el_limite(self):
        fecha = datetime.date.today() + datetime.timedelta(days=horarios.LIMITE_DIAS_ADELANTE + 1)
        self.assertTrue(horarios.fuera_de_ventana(fecha))


class TicketModelTests(TestCase):

    def setUp(self):
        self.usuario = crear_usuario('recepcionista_tickets')

    def test_al_guardar_genera_numero_y_turno_correlativos(self):
        paciente1 = crear_paciente(dpi='1111111111111')
        paciente2 = crear_paciente(dpi='2222222222222')

        ticket1 = Ticket.objects.create(
            paciente=paciente1, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )
        ticket2 = Ticket.objects.create(
            paciente=paciente2, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )

        self.assertEqual(ticket1.numero, 1)
        self.assertEqual(ticket1.turno, '001')
        self.assertEqual(ticket2.numero, 2)
        self.assertEqual(ticket2.turno, '002')
        self.assertEqual(ticket1.orden, 1)
        self.assertEqual(ticket2.orden, 2)

    def test_la_secuencia_de_turnos_es_compartida_entre_servicios(self):
        """La Pantalla de turnos une COEX/Privado/Emergencia IGSS: el número
        de turno es un solo contador correlativo, no uno por servicio."""
        paciente1 = crear_paciente(dpi='3333333333333')
        paciente2 = crear_paciente(dpi='4444444444444')

        ticket_emergencia = Ticket.objects.create(
            paciente=paciente1, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )
        ticket_coex = Ticket.objects.create(
            paciente=paciente2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario,
        )

        self.assertEqual(ticket_emergencia.turno, '001')
        self.assertEqual(ticket_coex.turno, '002')

    def test_adelantar_cambia_el_orden_pero_no_el_numero_de_turno(self):
        """Ejemplo del enunciado: 001 y 002 llegan por COEX, 003 llega por
        Privado y se adelanta 1 turno -> queda mostrado antes que 002, pero
        su número de turno sigue siendo 003."""
        p1, p2, p3 = (crear_paciente(dpi=f'{n:013d}') for n in (1, 2, 3))
        ticket_001 = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        ticket_002 = Ticket.objects.create(paciente=p2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        ticket_003 = Ticket.objects.create(paciente=p3, servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario)

        ticket_003.adelantar(1)

        cola = list(Ticket.objects.filter(estado=Ticket.ESTADO_EN_ESPERA).order_by('-prioridad', 'orden'))
        self.assertEqual(cola, [ticket_001, ticket_003, ticket_002])
        self.assertEqual(ticket_003.turno, '003')

    def test_ticket_urgente_de_emergencia_siempre_va_primero(self):
        p1, p2 = (crear_paciente(dpi=f'{n:013d}') for n in (5, 6))
        ticket_coex = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        ticket_emergencia = Ticket.objects.create(
            paciente=p2, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS,
            prioridad=Ticket.PRIORIDAD_URGENTE, registrado_por=self.usuario,
        )

        # Adelantar de más no debe poder pasar por encima del urgente.
        ticket_coex.adelantar(5)

        cola = list(Ticket.objects.filter(estado=Ticket.ESTADO_EN_ESPERA).order_by('-prioridad', 'orden'))
        self.assertEqual(cola, [ticket_emergencia, ticket_coex])

    def test_guardar_de_nuevo_no_regenera_el_turno_ya_asignado(self):
        paciente = crear_paciente(dpi='5555555555555')
        ticket = Ticket.objects.create(
            paciente=paciente, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )
        turno_original = ticket.turno

        ticket.estado = Ticket.ESTADO_ATENDIDO
        ticket.save(update_fields=['estado'])

        self.assertEqual(ticket.turno, turno_original)


class RegistrarTicketEmergenciaViewTests(TestCase):

    def setUp(self):
        self.usuario = crear_usuario('recepcionista_view', rol=Usuario.ROL_RECEPCIONISTA)
        self.client.force_login(self.usuario)
        self.datos_formulario = {
            'dpi': '6666666666666',
            'nombre': 'Carlos',
            'apellido': 'Gómez',
            'sexo': Paciente.SEXO_MASCULINO,
            'telefono': '55551234',
            'correo': 'carlos.gomez@correo.com',
            'fecha_nacimiento': '1985-03-10',
            'carnet_igss': '6666666666',
            'motivo': 'Dolor abdominal agudo',
        }

    def test_registrar_ticket_crea_paciente_y_ticket_en_espera(self):
        respuesta = self.client.post(reverse('registrar_ticket_emergencia'), self.datos_formulario)

        self.assertRedirects(respuesta, reverse('pantalla_turnos'))
        paciente = Paciente.objects.get(dpi='6666666666666')
        ticket = Ticket.objects.get(paciente=paciente)
        self.assertEqual(ticket.servicio, Ticket.SERVICIO_EMERGENCIA_IGSS)
        self.assertEqual(ticket.estado, Ticket.ESTADO_EN_ESPERA)
        self.assertEqual(ticket.prioridad, Ticket.PRIORIDAD_URGENTE)
        self.assertEqual(ticket.registrado_por, self.usuario)

    def test_registrar_ticket_reutiliza_paciente_existente_por_dpi(self):
        paciente_existente = crear_paciente(dpi='6666666666666', nombre='Nombre Original')

        self.client.post(reverse('registrar_ticket_emergencia'), self.datos_formulario)

        self.assertEqual(Paciente.objects.filter(dpi='6666666666666').count(), 1)
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.paciente_id, paciente_existente.id)

    def test_registrar_ticket_no_pisa_nombre_pero_actualiza_contacto_y_completa_vacios(self):
        crear_paciente(
            dpi='6666666666666', nombre='Nombre Viejo', telefono='00000000',
            sexo='', fecha_nacimiento=None,
        )

        self.client.post(reverse('registrar_ticket_emergencia'), self.datos_formulario)

        paciente = Paciente.objects.get(dpi='6666666666666')
        # El nombre ya guardado NO se cambia, aunque el form traiga otra cosa.
        self.assertEqual(paciente.nombre, 'Nombre Viejo')
        # El teléfono SÍ se corrige.
        self.assertEqual(paciente.telefono, '55551234')
        # Lo que estaba vacío SÍ se completa.
        self.assertEqual(paciente.sexo, Paciente.SEXO_MASCULINO)
        self.assertEqual(paciente.fecha_nacimiento, datetime.date(1985, 3, 10))

    def test_usuario_no_recepcionista_no_puede_acceder(self):
        otro_usuario = crear_usuario('tecnico_no_autorizado', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.client.force_login(otro_usuario)

        respuesta = self.client.get(reverse('registrar_ticket_emergencia'))

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Ticket.objects.count(), 0)


class HistorialPacientesBusquedaTests(TestCase):
    """La lista "Estudios realizados" también se puede buscar por el N° de
    expediente que el sistema le asigna a cada paciente."""

    def setUp(self):
        self.recepcion = crear_usuario('recep_historial', rol=Usuario.ROL_RECEPCIONISTA)
        self.client.force_login(self.recepcion)
        self.paciente = crear_paciente(dpi='4004004004001', nombre='Elena', apellido='Ramírez')
        crear_cita(self.recepcion, paciente=self.paciente, estado=Cita.ESTADO_PROCESADA)
        self.otro = crear_paciente(dpi='4004004004002', nombre='Otro', apellido='Paciente')
        crear_cita(self.recepcion, paciente=self.otro, estado=Cita.ESTADO_PROCESADA)

    def test_busca_por_numero_de_expediente(self):
        respuesta = self.client.get(reverse('historial_pacientes'), {'q': self.paciente.expediente})
        encontrados = [p.id for p in respuesta.context['pacientes']]
        self.assertEqual(encontrados, [self.paciente.id])

    def test_la_lista_muestra_el_expediente(self):
        respuesta = self.client.get(reverse('historial_pacientes'))
        self.assertContains(respuesta, f'Expediente: {self.paciente.expediente}')


class RolAdicionalAccesoAPantallasTests(TestCase):
    """Un usuario con un rol adicional (ver accounts.models.RolAdicional)
    puede entrar de verdad a las pantallas de ese rol, no solo verlas
    listadas en el panel."""

    def setUp(self):
        self.tecnico = crear_usuario('tec_rol_extra', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.client.force_login(self.tecnico)

    def test_sin_rol_adicional_no_puede_ver_solicitudes_de_radiologo(self):
        respuesta = self.client.get(reverse('solicitudes_pendientes'))
        self.assertEqual(respuesta.status_code, 302)

    def test_con_rol_adicional_de_radiologo_puede_ver_solicitudes(self):
        RolAdicional.objects.create(usuario=self.tecnico, rol=Usuario.ROL_MEDICO_RADIOLOGO)

        respuesta = self.client.get(reverse('solicitudes_pendientes'))

        self.assertEqual(respuesta.status_code, 200)

    def test_sigue_pudiendo_ver_sus_propias_ordenes_pendientes_de_tecnico(self):
        RolAdicional.objects.create(usuario=self.tecnico, rol=Usuario.ROL_MEDICO_RADIOLOGO)

        respuesta = self.client.get(reverse('ordenes_pendientes'))

        self.assertEqual(respuesta.status_code, 200)


class BuscarPacientePorDpiViewTests(TestCase):
    """Endpoint que usan Agendar cita y Registrar Ticket para autocompletar
    los datos del paciente por DPI, en vez de volver a escribirlos."""

    def setUp(self):
        self.usuario = crear_usuario('recepcionista_busqueda', rol=Usuario.ROL_RECEPCIONISTA)
        self.client.force_login(self.usuario)

    def test_devuelve_los_datos_si_el_dpi_existe(self):
        crear_paciente(
            dpi='1010101010101', nombre='Ana', apellido='Ruiz', telefono='55512345',
            fecha_nacimiento=datetime.date(1995, 6, 1),
        )

        respuesta = self.client.get(reverse('buscar_paciente_por_dpi'), {'dpi': '1010101010101'})

        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        self.assertTrue(datos['encontrado'])
        self.assertEqual(datos['nombre'], 'Ana')
        self.assertEqual(datos['apellido'], 'Ruiz')
        self.assertEqual(datos['telefono'], '55512345')
        self.assertEqual(datos['fecha_nacimiento'], '1995-06-01')

    def test_no_encontrado_cuando_el_dpi_no_existe(self):
        respuesta = self.client.get(reverse('buscar_paciente_por_dpi'), {'dpi': '0000000000000'})

        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(respuesta.json()['encontrado'])

    def test_usuario_no_recepcionista_no_puede_consultar(self):
        otro_usuario = crear_usuario('tecnico_busqueda', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.client.force_login(otro_usuario)

        respuesta = self.client.get(reverse('buscar_paciente_por_dpi'), {'dpi': '1010101010101'})

        self.assertEqual(respuesta.status_code, 302)


class AgendarCitaViewTests(TestCase):

    def setUp(self):
        self.usuario = crear_usuario('recepcionista_agendar', rol=Usuario.ROL_RECEPCIONISTA)
        self.client.force_login(self.usuario)
        self.tipo_estudio = TipoEstudio.objects.create(nombre='Radiografía de tórax')
        self.radiologo = crear_usuario('radiologa_agendar', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.tipo_estudio.radiologos.add(self.radiologo)
        self.manana = timezone.localdate() + datetime.timedelta(days=1)
        self.datos_formulario = {
            'dpi': '2020202020202',
            'nombre': 'Luis',
            'apellido': 'Marroquín',
            'sexo': Paciente.SEXO_MASCULINO,
            'telefono': '55599999',
            'correo': 'luis.marroquin@correo.com',
            'fecha_nacimiento': '1988-02-14',
            'carnet_igss': '2020202020',
            'tipo_estudio': self.tipo_estudio.id,
            'radiologo': self.radiologo.id,
            'fecha': self.manana,
            'hora': '10:00',
            'notas': '',
        }

    def _url(self):
        return f"{reverse('agendar_cita_coex')}?fecha={self.manana}&hora=10:00"

    def test_agendar_cita_no_duplica_paciente_existente_por_dpi(self):
        paciente_existente = crear_paciente(dpi='2020202020202', nombre='Nombre Original')

        self.client.post(self._url(), self.datos_formulario)

        self.assertEqual(Paciente.objects.filter(dpi='2020202020202').count(), 1)
        cita = Cita.objects.get(paciente__dpi='2020202020202')
        self.assertEqual(cita.paciente_id, paciente_existente.id)

    def test_agendar_cita_no_pisa_datos_ya_guardados_pero_actualiza_contacto(self):
        crear_paciente(
            dpi='2020202020202', nombre='Nombre Viejo', telefono='00000000',
            sexo='', fecha_nacimiento=None, correo='viejo@correo.com',
        )

        self.client.post(self._url(), self.datos_formulario)

        paciente = Paciente.objects.get(dpi='2020202020202')
        # Nombre/apellido ya guardados: intactos.
        self.assertEqual(paciente.nombre, 'Nombre Viejo')
        # Teléfono y correo SÍ se corrigen desde el formulario.
        self.assertEqual(paciente.telefono, '55599999')
        self.assertEqual(paciente.correo, 'luis.marroquin@correo.com')
        # Datos que estaban vacíos: se completan.
        self.assertEqual(paciente.sexo, Paciente.SEXO_MASCULINO)

    def test_estudio_con_un_solo_radiologo_se_asigna_solo(self):
        datos = dict(self.datos_formulario, radiologo='')
        self.client.post(self._url(), datos)
        cita = Cita.objects.get(paciente__dpi='2020202020202')
        self.assertEqual(cita.radiologo, self.radiologo)

    def test_estudio_con_varios_radiologos_exige_elegir_uno(self):
        otro = crear_usuario('radiologa_2', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.tipo_estudio.radiologos.add(otro)

        datos = dict(self.datos_formulario, radiologo='')
        respuesta = self.client.post(self._url(), datos)

        self.assertFalse(Cita.objects.filter(paciente__dpi='2020202020202').exists())
        self.assertContains(respuesta, 'varios radiólogos')

        datos['radiologo'] = otro.id
        self.client.post(self._url(), datos)
        cita = Cita.objects.get(paciente__dpi='2020202020202')
        self.assertEqual(cita.radiologo, otro)

    def test_estudio_sin_radiologos_no_se_puede_agendar(self):
        sin_rad = TipoEstudio.objects.create(nombre='Estudio sin radiologo')
        datos = dict(self.datos_formulario, tipo_estudio=sin_rad.id, radiologo='')

        respuesta = self.client.post(self._url(), datos)

        self.assertFalse(Cita.objects.filter(paciente__dpi='2020202020202').exists())
        self.assertContains(respuesta, 'no tiene radiólogos asignados')

    def test_no_permite_agendar_el_mismo_estudio_dos_veces_al_mismo_horario(self):
        self.client.post(self._url(), self.datos_formulario)

        respuesta = self.client.post(self._url(), self.datos_formulario)

        self.assertEqual(
            Cita.objects.filter(
                paciente__dpi='2020202020202',
                tipo_estudio=self.tipo_estudio,
                fecha=self.manana,
                hora='10:00',
            ).count(),
            1,
        )
        self.assertContains(respuesta, 'ya tiene agendado ese mismo estudio')


class PantallaTurnosViewTests(TestCase):

    def setUp(self):
        self.usuario = crear_usuario('recepcionista_turnos', rol=Usuario.ROL_RECEPCIONISTA)
        self.client.force_login(self.usuario)

    def test_la_cola_excluye_tickets_atendidos_y_ausentes(self):
        paciente = crear_paciente(dpi='7777777777777')
        ticket_en_espera = Ticket.objects.create(
            paciente=paciente, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )
        ticket_atendido = Ticket.objects.create(
            paciente=crear_paciente(dpi='8888888888888'),
            servicio=Ticket.SERVICIO_EMERGENCIA_IGSS,
            registrado_por=self.usuario,
            estado=Ticket.ESTADO_ATENDIDO,
        )

        respuesta = self.client.get(reverse('pantalla_turnos'))

        cola = list(respuesta.context['cola'])
        self.assertIn(ticket_en_espera, cola)
        self.assertNotIn(ticket_atendido, cola)

    def test_la_cola_une_coex_privado_y_emergencia_igss(self):
        p1, p2, p3 = (crear_paciente(dpi=f'{n:013d}') for n in (7, 8, 9))
        ticket_coex = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        ticket_privado = Ticket.objects.create(
            paciente=p2, servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario,
        )
        ticket_emergencia = Ticket.objects.create(
            paciente=p3, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS,
            prioridad=Ticket.PRIORIDAD_URGENTE, registrado_por=self.usuario,
        )

        respuesta = self.client.get(reverse('pantalla_turnos'))

        cola = list(respuesta.context['cola'])
        self.assertEqual(cola, [ticket_emergencia, ticket_coex, ticket_privado])
        self.assertEqual(respuesta.context['actual'], ticket_emergencia)

    def test_avanzar_turno_marca_atendido_y_pasa_al_siguiente(self):
        p1, p2 = (crear_paciente(dpi=f'{n:013d}') for n in (10, 11))
        ticket_1 = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        ticket_2 = Ticket.objects.create(paciente=p2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)

        respuesta = self.client.post(reverse('avanzar_turno', args=[ticket_1.id]))

        self.assertRedirects(respuesta, reverse('pantalla_turnos'))
        ticket_1.refresh_from_db()
        self.assertEqual(ticket_1.estado, Ticket.ESTADO_ATENDIDO)
        self.assertIsNotNone(ticket_1.atendido_en)

        respuesta = self.client.get(reverse('pantalla_turnos'))
        self.assertEqual(respuesta.context['actual'], ticket_2)

    def test_mover_turno_sube_y_baja_una_posicion(self):
        p1, p2, p3 = (crear_paciente(dpi=f'{n:013d}') for n in (30, 31, 32))
        t1 = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        t2 = Ticket.objects.create(paciente=p2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        t3 = Ticket.objects.create(paciente=p3, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)

        self.client.post(reverse('mover_turno', args=[t3.id]), {'direccion': 'subir'})
        cola = list(Ticket.objects.filter(estado=Ticket.ESTADO_EN_ESPERA).order_by('-prioridad', 'orden'))
        self.assertEqual(cola, [t1, t3, t2])

        self.client.post(reverse('mover_turno', args=[t3.id]), {'direccion': 'bajar'})
        cola = list(Ticket.objects.filter(estado=Ticket.ESTADO_EN_ESPERA).order_by('-prioridad', 'orden'))
        self.assertEqual(cola, [t1, t2, t3])

    def test_procesar_turno_de_cita_genera_orden_y_marca_atendido(self):
        recepcion = self.usuario
        radiologo = crear_usuario('rad_turno', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        estudio = TipoEstudio.objects.create(nombre='RX turno')
        estudio.radiologos.add(radiologo)
        cita = crear_cita(
            recepcion, tipo_estudio=estudio, convenio=Cita.CONVENIO_COEX,
            estado=Cita.ESTADO_AGENDADA, radiologo=radiologo, notas='Dolor lumbar',
            hora_llegada=timezone.now(),
            paciente=crear_paciente(dpi='4040404040404'),
        )
        ticket = Ticket.objects.create(
            paciente=cita.paciente, cita=cita, servicio=Ticket.SERVICIO_COEX,
            registrado_por=recepcion,
        )

        respuesta = self.client.post(reverse('procesar_turno', args=[ticket.id]))

        self.assertRedirects(respuesta, reverse('pantalla_turnos'))
        cita.refresh_from_db()
        ticket.refresh_from_db()
        self.assertEqual(cita.estado, Cita.ESTADO_EN_PROCESO)
        self.assertTrue(OrdenTrabajo.objects.filter(cita=cita).exists())
        self.assertEqual(OrdenTrabajo.objects.get(cita=cita).motivo, 'Dolor lumbar')
        self.assertEqual(ticket.estado, Ticket.ESTADO_ATENDIDO)

    def test_procesar_turno_de_cita_ya_procesada_solo_saca_el_turno(self):
        recepcion = self.usuario
        cita = crear_cita(
            recepcion, convenio=Cita.CONVENIO_COEX, estado=Cita.ESTADO_PROCESADA,
            hora_llegada=timezone.now(), paciente=crear_paciente(dpi='6060606060606'),
        )
        ticket = Ticket.objects.create(
            paciente=cita.paciente, cita=cita, servicio=Ticket.SERVICIO_COEX,
            registrado_por=recepcion,
        )

        respuesta = self.client.post(reverse('procesar_turno', args=[ticket.id]))

        self.assertRedirects(respuesta, reverse('pantalla_turnos'))
        ticket.refresh_from_db()
        self.assertEqual(ticket.estado, Ticket.ESTADO_ATENDIDO)

    def test_procesar_turno_de_emergencia_sin_cita_va_a_su_pantalla(self):
        ticket = Ticket.objects.create(
            paciente=crear_paciente(dpi='5050505050505'),
            servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )
        respuesta = self.client.post(reverse('procesar_turno', args=[ticket.id]))
        self.assertRedirects(
            respuesta, reverse('procesar_ticket_emergencia', args=[ticket.id]),
            target_status_code=200,
        )


class PantallaSalaEsperaTests(TestCase):
    """Pantalla pública (sin login) para el televisor de la sala de espera:
    muestra el último turno llamado y los próximos en espera."""

    def setUp(self):
        self.usuario = crear_usuario('recepcionista_sala_espera', rol=Usuario.ROL_RECEPCIONISTA)

    def test_no_requiere_login(self):
        respuesta = self.client.get(reverse('pantalla_sala_espera'))
        self.assertEqual(respuesta.status_code, 200)

    def test_sin_turno_atendido_no_hay_actual(self):
        Ticket.objects.create(
            paciente=crear_paciente(dpi='1231231231231'),
            servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario,
        )

        respuesta = self.client.get(reverse('pantalla_sala_espera'))

        self.assertIsNone(respuesta.context['actual'])

    def test_actual_es_el_ultimo_ticket_atendido(self):
        Ticket.objects.create(
            paciente=crear_paciente(dpi='1112223334441', nombre='Primero', apellido='Viejo'),
            servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario,
            estado=Ticket.ESTADO_ATENDIDO, atendido_en=timezone.now() - datetime.timedelta(minutes=5),
        )
        ultimo = Ticket.objects.create(
            paciente=crear_paciente(dpi='1112223334442', nombre='Ultimo', apellido='Nuevo'),
            servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario,
            estado=Ticket.ESTADO_ATENDIDO, atendido_en=timezone.now(),
        )

        respuesta = self.client.get(reverse('pantalla_sala_espera'))

        self.assertEqual(respuesta.context['actual']['turno'], ultimo.turno)

    def test_el_paciente_se_muestra_con_nombre_completo(self):
        Ticket.objects.create(
            paciente=crear_paciente(
                dpi='1112223334449', nombre='Elmer Adrián', apellido='Melendrez Catalán',
            ),
            servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario,
            estado=Ticket.ESTADO_ATENDIDO, atendido_en=timezone.now(),
        )

        respuesta = self.client.get(reverse('pantalla_sala_espera'))

        self.assertEqual(
            respuesta.context['actual']['paciente'], 'Elmer Adrián Melendrez Catalán',
        )

    def test_estado_sala_espera_devuelve_json_con_radiologo_y_sala_por_modalidad(self):
        radiologo = crear_usuario('rad_sala', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        radiologo.first_name, radiologo.last_name = 'Juan', 'Pérez'
        radiologo.save()
        tipo_tac, _ = TipoEstudio.objects.get_or_create(
            nombre='Tomografía de prueba', defaults={'modalidad': TipoEstudio.MODALIDAD_TAC},
        )
        cita = crear_cita(
            self.usuario, radiologo=radiologo, estado=Cita.ESTADO_EN_PROCESO,
            tipo_estudio=tipo_tac,
            paciente=crear_paciente(dpi='1112223334450', nombre='Ana', apellido='Gómez'),
        )
        Ticket.objects.create(
            paciente=cita.paciente, cita=cita, servicio=Ticket.SERVICIO_PRIVADO,
            registrado_por=self.usuario, estado=Ticket.ESTADO_ATENDIDO, atendido_en=timezone.now(),
        )

        data = self.client.get(reverse('estado_sala_espera')).json()

        self.assertEqual(data['actual']['paciente'], 'Ana Gómez')
        self.assertEqual(data['actual']['radiologo'], 'Juan Pérez')
        self.assertEqual(data['actual']['sala'], 'Sala 3')
        self.assertNotIn('estudio', data['actual'])

    def test_estado_sala_espera_sin_login_y_sin_turno(self):
        data = self.client.get(reverse('estado_sala_espera')).json()
        self.assertIsNone(data['actual'])
        self.assertEqual(data['proximos'], [])

    def test_proximos_son_los_en_espera_sin_incluir_al_ya_atendido(self):
        atendido = Ticket.objects.create(
            paciente=crear_paciente(dpi='1112223334443'),
            servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario,
            estado=Ticket.ESTADO_ATENDIDO, atendido_en=timezone.now(),
        )
        urgente = Ticket.objects.create(
            paciente=crear_paciente(dpi='1112223334444'),
            servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, prioridad=Ticket.PRIORIDAD_URGENTE,
            registrado_por=self.usuario,
        )
        normal = Ticket.objects.create(
            paciente=crear_paciente(dpi='1112223334445'),
            servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario,
        )

        respuesta = self.client.get(reverse('pantalla_sala_espera'))

        proximos = list(respuesta.context['proximos'])
        self.assertEqual(proximos, [urgente, normal])
        self.assertNotIn(atendido, proximos)

    def test_proximos_se_limitan_a_cuatro(self):
        for n in range(6):
            Ticket.objects.create(
                paciente=crear_paciente(dpi=f'22233344455{n}'),
                servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario,
            )

        respuesta = self.client.get(reverse('pantalla_sala_espera'))

        self.assertEqual(len(respuesta.context['proximos']), 4)


class GuardarSeleccionImagenesTests(TestCase):
    """Al descartar imágenes de la galería: si el archivo físico está
    bloqueado (WinError 5 en Windows) la operación no revienta — el estado
    en la base de datos se actualiza igual y se avisa que quedaron huérfanos."""

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self._media = tempfile.mkdtemp()
        self._cm = override_settings(MEDIA_ROOT=self._media)
        self._cm.enable()

        self.radiologo = crear_usuario('rad_sel', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        recepcion = crear_usuario('recep_sel', rol=Usuario.ROL_RECEPCIONISTA)
        self.cita = crear_cita(recepcion, estado=Cita.ESTADO_EN_PROCESO)
        self.orden = OrdenTrabajo.objects.create(cita=self.cita, motivo='x', creada_por=recepcion)
        self.tecnico = crear_usuario('tec_sel', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.img_marcada = ImagenEstudio.objects.create(
            orden=self.orden, subida_por=self.tecnico, seleccionada=True,
            archivo=SimpleUploadedFile('a.jpg', b'aaa'),
        )
        self.img_descartada = ImagenEstudio.objects.create(
            orden=self.orden, subida_por=self.tecnico, seleccionada=True,
            archivo=SimpleUploadedFile('b.jpg', b'bbb'),
        )
        self.client.force_login(self.radiologo)

    def tearDown(self):
        import shutil

        self._cm.disable()
        shutil.rmtree(self._media, ignore_errors=True)

    def _post(self):
        return self.client.post(
            reverse('guardar_seleccion_imagenes', args=[self.orden.id]),
            {'seleccionadas': [str(self.img_marcada.id)]},
        )

    def test_descarta_la_imagen_y_borra_el_archivo(self):
        nombre = self.img_descartada.archivo.name
        storage = self.img_descartada.archivo.storage

        respuesta = self._post()

        self.assertRedirects(respuesta, reverse('ver_imagenes_jpg', args=[self.orden.id]))
        self.assertFalse(ImagenEstudio.objects.filter(id=self.img_descartada.id).exists())
        self.assertTrue(ImagenEstudio.objects.filter(id=self.img_marcada.id).exists())
        self.assertFalse(storage.exists(nombre))

    def test_archivo_bloqueado_no_revienta_y_avisa(self):
        from django.contrib.messages import get_messages
        from django.core.files.storage import FileSystemStorage

        import pacientes.views as vistas

        def denegado(self, name):
            raise PermissionError(5, 'Acceso denegado')

        original, sleep_real = FileSystemStorage.delete, vistas.time.sleep
        FileSystemStorage.delete = denegado
        vistas.time.sleep = lambda *_a, **_k: None
        try:
            respuesta = self._post()
        finally:
            FileSystemStorage.delete = original
            vistas.time.sleep = sleep_real

        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(ImagenEstudio.objects.filter(id=self.img_descartada.id).exists())
        mensajes = [str(m) for m in get_messages(respuesta.wsgi_request)]
        self.assertTrue(any('no se pudieron borrar' in m for m in mensajes))


class ProcesarTicketEmergenciaViewTests(TestCase):

    def setUp(self):
        self.usuario = crear_usuario('recepcionista_procesar', rol=Usuario.ROL_RECEPCIONISTA)
        self.client.force_login(self.usuario)
        self.tipo_estudio = TipoEstudio.objects.create(nombre='Radiografía de tórax')
        self.paciente = crear_paciente(dpi='9999999999999')
        self.ticket = Ticket.objects.create(
            paciente=self.paciente,
            servicio=Ticket.SERVICIO_EMERGENCIA_IGSS,
            registrado_por=self.usuario,
            motivo='Dolor abdominal',
        )

    def test_procesar_genera_cita_en_proceso_y_orden_de_trabajo(self):
        respuesta = self.client.post(
            reverse('procesar_ticket_emergencia', args=[self.ticket.id]),
            {'tipo_estudio': self.tipo_estudio.id, 'motivo': 'Dolor abdominal agudo, descartar apendicitis.'},
        )

        self.assertRedirects(respuesta, reverse('pantalla_turnos'))

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.estado, Ticket.ESTADO_ATENDIDO)
        self.assertIsNotNone(self.ticket.atendido_en)
        self.assertIsNotNone(self.ticket.cita)

        cita = self.ticket.cita
        self.assertEqual(cita.paciente, self.paciente)
        self.assertEqual(cita.convenio, Cita.CONVENIO_EMERGENCIA_IGSS)
        self.assertEqual(cita.estado, Cita.ESTADO_EN_PROCESO)

        orden = OrdenTrabajo.objects.get(cita=cita)
        self.assertEqual(orden.motivo, 'Dolor abdominal agudo, descartar apendicitis.')
        self.assertEqual(orden.creada_por, self.usuario)

    def test_el_ticket_procesado_sale_de_la_pantalla_de_turnos(self):
        self.client.post(
            reverse('procesar_ticket_emergencia', args=[self.ticket.id]),
            {'tipo_estudio': self.tipo_estudio.id, 'motivo': 'Control.'},
        )

        respuesta = self.client.get(reverse('pantalla_turnos'))

        self.assertNotIn(self.ticket, list(respuesta.context['cola']))

    def test_la_orden_generada_aparece_en_ordenes_pendientes_del_tecnico(self):
        self.client.post(
            reverse('procesar_ticket_emergencia', args=[self.ticket.id]),
            {'tipo_estudio': self.tipo_estudio.id, 'motivo': 'Control.'},
        )

        tecnico = crear_usuario('tecnico_emergencia', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.client.force_login(tecnico)
        respuesta = self.client.get(reverse('ordenes_pendientes'))

        ordenes = list(respuesta.context['ordenes'])
        self.assertEqual(len(ordenes), 1)
        self.assertEqual(ordenes[0].cita.paciente, self.paciente)

    def test_no_se_puede_procesar_dos_veces_el_mismo_ticket(self):
        self.client.post(
            reverse('procesar_ticket_emergencia', args=[self.ticket.id]),
            {'tipo_estudio': self.tipo_estudio.id, 'motivo': 'Control.'},
        )

        respuesta = self.client.post(
            reverse('procesar_ticket_emergencia', args=[self.ticket.id]),
            {'tipo_estudio': self.tipo_estudio.id, 'motivo': 'Otra vez.'},
        )

        self.assertRedirects(respuesta, reverse('pantalla_turnos'))
        self.assertEqual(Cita.objects.filter(paciente=self.paciente).count(), 1)


class FechaNacimientoNoFuturaTests(TestCase):
    """HU: al agendar una cita o registrar un ticket, la fecha de nacimiento
    no puede quedar en el futuro."""

    def setUp(self):
        self.tipo_estudio = TipoEstudio.objects.create(nombre='Radiografía de tórax')
        self.radiologo = crear_usuario('radiologa1', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.manana = timezone.localdate() + datetime.timedelta(days=1)
        self.ayer = timezone.localdate() - datetime.timedelta(days=1)

    def datos_agendar_cita(self, fecha_nacimiento):
        return {
            'dpi': '1234567890123',
            'nombre': 'Juana',
            'apellido': 'Pérez',
            'sexo': Paciente.SEXO_FEMENINO,
            'telefono': '',
            'correo': 'juana.perez@correo.com',
            'fecha_nacimiento': fecha_nacimiento,
            'tipo_estudio': self.tipo_estudio.id,
            'radiologo': self.radiologo.id,
            'fecha': self.manana,
            'hora': '09:00',
            'notas': '',
        }

    def datos_registrar_ticket(self, fecha_nacimiento):
        return {
            'dpi': '1234567890123',
            'nombre': 'Juana',
            'apellido': 'Pérez',
            'sexo': Paciente.SEXO_FEMENINO,
            'telefono': '',
            'correo': 'juana.perez@correo.com',
            'fecha_nacimiento': fecha_nacimiento,
            'carnet_igss': '1234567890',
            'prioridad': Ticket.PRIORIDAD_NORMAL,
            'motivo': '',
        }

    def test_agendar_cita_rechaza_fecha_de_nacimiento_futura(self):
        form = AgendarCitaForm(self.datos_agendar_cita(self.manana))
        self.assertFalse(form.is_valid())
        self.assertIn('fecha_nacimiento', form.errors)

    def test_agendar_cita_acepta_fecha_de_nacimiento_pasada(self):
        form = AgendarCitaForm(self.datos_agendar_cita(self.ayer))
        self.assertNotIn('fecha_nacimiento', form.errors)

    def test_registrar_ticket_rechaza_fecha_de_nacimiento_futura(self):
        form = RegistrarTicketForm(self.datos_registrar_ticket(self.manana))
        self.assertFalse(form.is_valid())
        self.assertIn('fecha_nacimiento', form.errors)

    def test_registrar_ticket_acepta_fecha_de_nacimiento_pasada(self):
        form = RegistrarTicketForm(self.datos_registrar_ticket(self.ayer))
        self.assertTrue(form.is_valid())


class NotificacionesTests(TestCase):
    """HU: cada hand-off del flujo (cita asignada, orden pendiente, estudio
    listo para informar, estudio completado) genera una Notificacion para
    quien tiene que actuar, que la campanita del navegador usa para avisar
    con sonido."""

    def setUp(self):
        self.recepcionista = crear_usuario('recepcionista_notif', rol=Usuario.ROL_RECEPCIONISTA)
        self.tecnico = crear_usuario('tecnico_notif', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.radiologo = crear_usuario('radiologo_notif', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.tipo_estudio = TipoEstudio.objects.create(nombre='Radiografía de tórax')
        self.tipo_estudio.radiologos.add(self.radiologo)

    def test_agendar_cita_notifica_al_radiologo_asignado(self):
        self.client.force_login(self.recepcionista)
        manana = timezone.localdate() + datetime.timedelta(days=1)
        datos = {
            'dpi': '3030303030303',
            'nombre': 'Ana',
            'apellido': 'López',
            'sexo': Paciente.SEXO_FEMENINO,
            'telefono': '',
            'correo': 'ana.lopez@correo.com',
            'fecha_nacimiento': '1990-01-01',
            'carnet_igss': '3030303030',
            'tipo_estudio': self.tipo_estudio.id,
            'radiologo': self.radiologo.id,
            'fecha': manana,
            'hora': '10:00',
            'notas': '',
        }

        self.client.post(f"{reverse('agendar_cita_coex')}?fecha={manana}&hora=10:00", datos)

        cita = Cita.objects.get(paciente__dpi='3030303030303')
        notificacion = Notificacion.objects.get(destinatario=self.radiologo)
        self.assertEqual(notificacion.tipo, Notificacion.TIPO_CITA_ASIGNADA)
        self.assertEqual(notificacion.cita, cita)
        self.assertFalse(notificacion.leida)

    def test_generar_orden_notifica_a_todos_los_tecnicos(self):
        otro_tecnico = crear_usuario('tecnico_notif_2', rol=Usuario.ROL_TECNICO_IMAGENES)
        cita = crear_cita(
            self.recepcionista, radiologo=self.radiologo, convenio=Cita.CONVENIO_COEX,
            estado=Cita.ESTADO_AGENDADA, hora_llegada=timezone.now(),
            # Fecha en el futuro: AutoMarcarAusenteMiddleware pasaría a AUSENTE
            # cualquier cita AGENDADA de hoy si ya son las 18:00 (ver
            # Cita.marcar_ausentes_vencidas), lo que le ganaría la carrera al POST.
            fecha=timezone.localdate() + datetime.timedelta(days=1),
        )
        self.client.force_login(self.recepcionista)

        self.client.post(
            reverse('generar_orden_coex', args=[cita.id]),
            {'motivo': 'Dolor torácico.'},
        )

        for tecnico in (self.tecnico, otro_tecnico):
            notificacion = Notificacion.objects.get(destinatario=tecnico, cita=cita)
            self.assertEqual(notificacion.tipo, Notificacion.TIPO_ORDEN_PENDIENTE)

    def test_adjuntar_imagenes_notifica_al_radiologo_asignado_de_la_cita(self):
        cita = crear_cita(self.recepcionista, radiologo=self.radiologo, estado=Cita.ESTADO_EN_PROCESO)
        orden = OrdenTrabajo.objects.create(cita=cita, motivo='Control.', creada_por=self.recepcionista)
        self.client.force_login(self.tecnico)

        self.client.post(
            reverse('adjuntar_imagenes', args=[orden.id]),
            {'imagenes': [SimpleUploadedFile('foto.jpg', b'contenido', content_type='image/jpeg')]},
        )

        notificacion = Notificacion.objects.get(destinatario=self.radiologo, cita=cita)
        self.assertEqual(notificacion.tipo, Notificacion.TIPO_ESTUDIO_LISTO_INFORMAR)

    def test_adjuntar_imagenes_sin_radiologo_asignado_notifica_a_todos_los_radiologos(self):
        otro_radiologo = crear_usuario('radiologo_notif_2', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        cita = crear_cita(self.recepcionista, radiologo=None, estado=Cita.ESTADO_EN_PROCESO)
        orden = OrdenTrabajo.objects.create(cita=cita, motivo='Control.', creada_por=self.recepcionista)
        self.client.force_login(self.tecnico)

        self.client.post(
            reverse('adjuntar_imagenes', args=[orden.id]),
            {'imagenes': [SimpleUploadedFile('foto.jpg', b'contenido', content_type='image/jpeg')]},
        )

        for radiologo in (self.radiologo, otro_radiologo):
            self.assertTrue(
                Notificacion.objects.filter(
                    destinatario=radiologo, cita=cita, tipo=Notificacion.TIPO_ESTUDIO_LISTO_INFORMAR,
                ).exists()
            )

    def test_adjuntar_informe_notifica_a_todos_los_recepcionistas(self):
        otro_recepcionista = crear_usuario('recepcionista_notif_2', rol=Usuario.ROL_RECEPCIONISTA)
        cita = crear_cita(self.recepcionista, radiologo=self.radiologo, estado=Cita.ESTADO_EN_PROCESO)
        orden = OrdenTrabajo.objects.create(cita=cita, motivo='Control.', creada_por=self.recepcionista)
        ImagenEstudio.objects.create(
            orden=orden,
            archivo=SimpleUploadedFile('foto.jpg', b'contenido', content_type='image/jpeg'),
            subida_por=self.tecnico,
        )
        self.client.force_login(self.radiologo)

        self.client.post(
            reverse('adjuntar_informe', args=[cita.id]),
            {'informe_texto': 'Sin hallazgos patológicos.'},
        )

        for recepcionista in (self.recepcionista, otro_recepcionista):
            notificacion = Notificacion.objects.get(destinatario=recepcionista, cita=cita)
            self.assertEqual(notificacion.tipo, Notificacion.TIPO_ESTUDIO_COMPLETADO)

    def test_procesar_ticket_emergencia_notifica_a_los_tecnicos(self):
        paciente = crear_paciente(dpi='4040404040404')
        ticket = Ticket.objects.create(
            paciente=paciente, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.recepcionista,
        )
        self.client.force_login(self.recepcionista)

        self.client.post(
            reverse('procesar_ticket_emergencia', args=[ticket.id]),
            {'tipo_estudio': self.tipo_estudio.id, 'motivo': 'Trauma.'},
        )

        self.assertTrue(
            Notificacion.objects.filter(
                destinatario=self.tecnico, tipo=Notificacion.TIPO_ORDEN_PENDIENTE,
            ).exists()
        )


class NotificacionesPendientesViewTests(TestCase):

    def setUp(self):
        self.usuario = crear_usuario('usuario_notif_api', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.otro_usuario = crear_usuario('otro_usuario_notif_api', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.client.force_login(self.usuario)

    def test_solo_devuelve_notificaciones_no_leidas_del_usuario_actual(self):
        Notificacion.notificar(
            destinatario=self.usuario, tipo=Notificacion.TIPO_ORDEN_PENDIENTE, mensaje='Para mí, sin leer',
        )
        leida = Notificacion.notificar(
            destinatario=self.usuario, tipo=Notificacion.TIPO_ORDEN_PENDIENTE, mensaje='Para mí, ya leída',
        )
        leida.leida = True
        leida.save(update_fields=['leida'])
        Notificacion.notificar(
            destinatario=self.otro_usuario, tipo=Notificacion.TIPO_ORDEN_PENDIENTE,
            mensaje='Para otro usuario',
        )

        respuesta = self.client.get(reverse('notificaciones_pendientes'))
        data = respuesta.json()

        self.assertEqual(data['no_leidas'], 1)
        self.assertEqual(len(data['notificaciones']), 1)
        self.assertEqual(data['notificaciones'][0]['mensaje'], 'Para mí, sin leer')

    def test_marcar_notificacion_leida_solo_afecta_a_esa_notificacion(self):
        n1 = Notificacion.notificar(
            destinatario=self.usuario, tipo=Notificacion.TIPO_ORDEN_PENDIENTE, mensaje='Uno',
        )
        n2 = Notificacion.notificar(
            destinatario=self.usuario, tipo=Notificacion.TIPO_ORDEN_PENDIENTE, mensaje='Dos',
        )

        self.client.post(reverse('marcar_notificacion_leida', args=[n1.id]))

        n1.refresh_from_db()
        n2.refresh_from_db()
        self.assertTrue(n1.leida)
        self.assertFalse(n2.leida)

    def test_marcar_todas_leidas_marca_todas_las_del_usuario(self):
        Notificacion.notificar(
            destinatario=self.usuario, tipo=Notificacion.TIPO_ORDEN_PENDIENTE, mensaje='Uno',
        )
        Notificacion.notificar(
            destinatario=self.usuario, tipo=Notificacion.TIPO_ORDEN_PENDIENTE, mensaje='Dos',
        )

        self.client.post(reverse('marcar_notificaciones_leidas'))

        self.assertEqual(Notificacion.objects.filter(destinatario=self.usuario, leida=False).count(), 0)

    def test_no_marca_notificaciones_de_otro_usuario(self):
        ajena = Notificacion.notificar(
            destinatario=self.otro_usuario, tipo=Notificacion.TIPO_ORDEN_PENDIENTE, mensaje='Ajena',
        )

        self.client.post(reverse('marcar_notificacion_leida', args=[ajena.id]))

        ajena.refresh_from_db()
        self.assertFalse(ajena.leida)


class ComboModelTests(TestCase):
    """Combo (portado de visual-andres): el precio se calcula al vuelo,
    nada se guarda."""

    def setUp(self):
        self.e1 = TipoEstudio.objects.create(nombre='RX Torax combo')
        self.e2 = TipoEstudio.objects.create(nombre='RX Columna combo')
        PrecioEstudio.objects.create(
            tipo_estudio=self.e1, convenio=Cita.CONVENIO_PRIVADO,
            horario_habil=True, precio=Decimal('200'),
        )
        PrecioEstudio.objects.create(
            tipo_estudio=self.e2, convenio=Cita.CONVENIO_PRIVADO,
            horario_habil=True, precio=Decimal('300'),
        )

    def test_total_para_suma_los_precios_de_sus_estudios(self):
        combo = Combo.objects.create(nombre='Combo torax-columna')
        combo.estudios.set([self.e1, self.e2])
        self.assertEqual(combo.total_para(Cita.CONVENIO_PRIVADO, True), Decimal('500.00'))

    def test_total_para_aplica_el_descuento(self):
        combo = Combo.objects.create(
            nombre='Combo con descuento', aplica_descuento=True, porcentaje_descuento=Decimal('10'),
        )
        combo.estudios.set([self.e1, self.e2])
        self.assertEqual(combo.total_para(Cita.CONVENIO_PRIVADO, True), Decimal('450.00'))

    def test_total_para_ignora_descuento_fuera_de_rango(self):
        combo = Combo.objects.create(
            nombre='Combo descuento invalido', aplica_descuento=True, porcentaje_descuento=Decimal('150'),
        )
        combo.estudios.set([self.e1, self.e2])
        self.assertEqual(combo.total_para(Cita.CONVENIO_PRIVADO, True), Decimal('500.00'))

    def test_precio_referencia_usa_privado_habil(self):
        combo = Combo.objects.create(nombre='Combo ref')
        combo.estudios.set([self.e1])
        self.assertEqual(combo.precio_referencia, Decimal('200.00'))


class ComboViewTests(TestCase):
    """Los combos (catálogo) se administran íntegro por un administrador,
    igual que Estudios."""

    def setUp(self):
        self.admin = crear_usuario('admin_combo', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.recep = crear_usuario('recep_combo', rol=Usuario.ROL_RECEPCIONISTA)
        self.estudio = TipoEstudio.objects.create(nombre='RX combo view')

    def test_lista_combos_visible_para_administrador(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('lista_combos'))
        self.assertEqual(respuesta.status_code, 200)

    def test_lista_combos_no_visible_para_recepcionista(self):
        self.client.force_login(self.recep)
        respuesta = self.client.get(reverse('lista_combos'))
        self.assertNotEqual(respuesta.status_code, 200)

    def test_crear_combo_como_administrador(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse('crear_combo'), {
            'nombre': 'Combo nuevo', 'estudios': [self.estudio.id],
            'activo': 'on', 'aplica_descuento': '', 'porcentaje_descuento': '0',
        })
        self.assertRedirects(respuesta, reverse('lista_combos'))
        self.assertTrue(Combo.objects.filter(nombre='Combo nuevo').exists())

    def test_recepcionista_no_puede_crear_combo(self):
        self.client.force_login(self.recep)
        respuesta = self.client.get(reverse('crear_combo'))
        self.assertNotEqual(respuesta.status_code, 200)


class CajaTests(TestCase):
    """Rol/permiso de Caja (portado de visual-andres, 2026-09-04): al
    generar una orden se crea un Cobro pendiente; mientras no se marque
    pagado, bloquea el envío de resultados; pagos_pendientes/marcar_cobrado
    son solo para quien tiene el permiso puede_operar_caja (o admin)."""

    def setUp(self):
        self.recepcion = crear_usuario('recep_caja', rol=Usuario.ROL_RECEPCIONISTA)
        self.caja = crear_usuario(
            'caja_operador', rol=Usuario.ROL_RECEPCIONISTA, puede_operar_caja=True,
        )

    def test_generar_orden_crea_un_cobro_pendiente(self):
        cita = crear_cita(
            self.recepcion, estado=Cita.ESTADO_AGENDADA, hora_llegada=timezone.now(),
        )
        self.client.force_login(self.recepcion)

        respuesta = self.client.post(
            reverse('generar_orden_privado', args=[cita.id]), {'motivo': 'Dolor lumbar'},
        )

        self.assertEqual(respuesta.status_code, 302)
        cobro = Cobro.objects.get(cita=cita)
        self.assertEqual(cobro.estado, Cobro.ESTADO_PENDIENTE)
        self.assertFalse(cobro.pagado)

    def test_pagos_pendientes_requiere_el_permiso_de_caja(self):
        self.client.force_login(self.recepcion)
        respuesta = self.client.get(reverse('pagos_pendientes'))
        self.assertNotEqual(respuesta.status_code, 200)

    def test_pagos_pendientes_visible_con_el_permiso(self):
        self.client.force_login(self.caja)
        respuesta = self.client.get(reverse('pagos_pendientes'))
        self.assertEqual(respuesta.status_code, 200)

    def test_pagos_pendientes_filtra_por_estado(self):
        cita_pendiente = crear_cita(self.recepcion, estado=Cita.ESTADO_EN_PROCESO)
        OrdenTrabajo.objects.create(cita=cita_pendiente, motivo='x', creada_por=self.recepcion)
        cobro_pendiente = Cobro.objects.create(cita=cita_pendiente)

        cita_pagada = crear_cita(
            self.recepcion, estado=Cita.ESTADO_PROCESADA,
            paciente=crear_paciente(dpi='9998887776665'),
        )
        OrdenTrabajo.objects.create(cita=cita_pagada, motivo='x', creada_por=self.recepcion)
        cobro_pagado = Cobro.objects.create(cita=cita_pagada)
        cobro_pagado.marcar_pagado(self.caja)

        self.client.force_login(self.caja)
        respuesta = self.client.get(reverse('pagos_pendientes'), {'estado': 'pagado'})

        cobros = list(respuesta.context['pagina'])
        self.assertIn(cobro_pagado, cobros)
        self.assertNotIn(cobro_pendiente, cobros)

    def test_marcar_cobrado_registra_forma_de_pago_y_boleta(self):
        cita = crear_cita(self.recepcion, estado=Cita.ESTADO_EN_PROCESO)
        OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.recepcion)
        Cobro.objects.create(cita=cita)
        self.client.force_login(self.caja)

        respuesta = self.client.post(reverse('marcar_cobrado', args=[cita.id]), {
            'forma_pago': Cobro.FORMA_EFECTIVO, 'numero_boleta': 'B-001', 'notas': 'Pagó en caja',
        })

        self.assertRedirects(respuesta, reverse('pagos_pendientes'))
        cobro = Cobro.objects.get(cita=cita)
        self.assertTrue(cobro.pagado)
        self.assertEqual(cobro.forma_pago, Cobro.FORMA_EFECTIVO)
        self.assertEqual(cobro.numero_boleta, 'B-001')
        self.assertEqual(cobro.cobrado_por, self.caja)
        self.assertIsNotNone(cobro.pagado_en)

    def test_boleta_pago_pdf_solo_para_cobros_pagados(self):
        cita = crear_cita(self.recepcion, estado=Cita.ESTADO_EN_PROCESO)
        OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.recepcion)
        cobro = Cobro.objects.create(cita=cita)
        self.client.force_login(self.caja)

        respuesta = self.client.get(reverse('boleta_pago_pdf', args=[cobro.id]))
        self.assertEqual(respuesta.status_code, 404)

        cobro.marcar_pagado(self.caja)
        respuesta = self.client.get(reverse('boleta_pago_pdf', args=[cobro.id]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')
        self.assertTrue(respuesta.content.startswith(b'%PDF'))

    def test_registrar_pago_guarda_comprobante_bancario(self):
        cita = crear_cita(self.recepcion, estado=Cita.ESTADO_EN_PROCESO)
        OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.recepcion)
        Cobro.objects.create(cita=cita)
        self.client.force_login(self.caja)

        archivo = SimpleUploadedFile(
            'boleta-transferencia.pdf',
            b'%PDF-1.4 comprobante de prueba',
            content_type='application/pdf',
        )
        respuesta = self.client.post(
            reverse('marcar_cobrado', args=[cita.id]),
            {
                'forma_pago': Cobro.FORMA_TRANSFERENCIA,
                'numero_boleta': 'TR-001',
                'comprobante_bancario': archivo,
                'notas': '',
            },
        )

        self.assertRedirects(respuesta, reverse('pagos_pendientes'))
        cobro = Cobro.objects.get(cita=cita)
        self.assertTrue(cobro.comprobante_bancario)
        self.assertEqual(
            self.client.get(reverse('comprobante_bancario', args=[cobro.id])).status_code,
            200,
        )

    def test_transferencia_requiere_comprobante_bancario(self):
        cita = crear_cita(self.recepcion, estado=Cita.ESTADO_EN_PROCESO)
        OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.recepcion)
        Cobro.objects.create(cita=cita)
        self.client.force_login(self.caja)

        respuesta = self.client.post(
            reverse('marcar_cobrado', args=[cita.id]),
            {
                'forma_pago': Cobro.FORMA_TRANSFERENCIA,
                'numero_boleta': 'TR-002',
                'notas': '',
            },
        )

        self.assertRedirects(respuesta, reverse('pagos_pendientes'))
        self.assertFalse(Cobro.objects.get(cita=cita).pagado)

    def test_constancia_pago_se_genera_y_constancia_firmada_se_puede_subir(self):
        cita = crear_cita(self.recepcion, estado=Cita.ESTADO_EN_PROCESO)
        OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.recepcion)
        cobro = Cobro.objects.create(cita=cita)
        cobro.marcar_pagado(self.caja)
        self.client.force_login(self.caja)

        respuesta = self.client.get(reverse('constancia_pago_pdf', args=[cobro.id]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')
        self.assertTrue(respuesta.content.startswith(b'%PDF'))

        archivo = SimpleUploadedFile(
            'constancia-firmada.pdf',
            b'%PDF-1.4 constancia firmada',
            content_type='application/pdf',
        )
        respuesta = self.client.post(
            reverse('subir_constancia_firmada', args=[cobro.id]),
            {'constancia_firmada': archivo},
        )
        self.assertRedirects(respuesta, reverse('pagos_pendientes'))
        cobro.refresh_from_db()
        self.assertTrue(cobro.constancia_firmada)
        self.assertEqual(
            self.client.get(reverse('constancia_firmada', args=[cobro.id])).status_code,
            200,
        )

    def test_documentos_de_pago_no_se_pueden_consultar_mientras_pendiente(self):
        cita = crear_cita(self.recepcion, estado=Cita.ESTADO_EN_PROCESO)
        OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.recepcion)
        cobro = Cobro.objects.create(cita=cita)
        self.client.force_login(self.caja)

        for nombre in ('comprobante_bancario', 'constancia_pago_pdf', 'constancia_firmada'):
            respuesta = self.client.get(reverse(nombre, args=[cobro.id]))
            self.assertEqual(respuesta.status_code, 404)

    def test_comprobante_pagado_visible_para_recepcion_tecnico_y_radiologo(self):
        cita = crear_cita(self.recepcion, estado=Cita.ESTADO_PROCESADA)
        OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.recepcion)
        cobro = Cobro.objects.create(cita=cita)
        cobro.marcar_pagado(self.caja)

        usuarios = [
            crear_usuario('recep_comprobante', rol=Usuario.ROL_RECEPCIONISTA),
            crear_usuario('tec_comprobante', rol=Usuario.ROL_TECNICO_IMAGENES),
            crear_usuario('rad_comprobante', rol=Usuario.ROL_MEDICO_RADIOLOGO),
        ]
        for usuario in usuarios:
            self.client.force_login(usuario)
            respuesta = self.client.get(reverse('boleta_pago_pdf', args=[cobro.id]))
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(respuesta['Content-Type'], 'application/pdf')

    def test_boleta_no_muestra_carne_igss_en_estudios_privados(self):
        from pacientes.views import datos_paciente_boleta

        paciente = crear_paciente(dpi='7778889990001', carnet_igss='IGSS-123456')
        cita_privada = crear_cita(
            self.recepcion, paciente=paciente, convenio=Cita.CONVENIO_PRIVADO,
        )
        etiquetas = [e for e, _ in datos_paciente_boleta(cita_privada)]
        self.assertNotIn('Carné IGSS:', etiquetas)

    def test_boleta_muestra_carne_igss_en_estudios_coex_y_emergencia(self):
        from pacientes.views import datos_paciente_boleta

        for i, convenio in enumerate((Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS)):
            paciente = crear_paciente(
                dpi=f'88800000000{i}', carnet_igss=f'IGSS-77{i}',
            )
            cita = crear_cita(self.recepcion, paciente=paciente, convenio=convenio)
            filas = dict(datos_paciente_boleta(cita))
            self.assertEqual(filas['Carné IGSS:'], f'IGSS-77{i}')

    def test_cobro_pendiente_bloquea_el_envio_de_resultados(self):
        paciente = crear_paciente(dpi='1112223334446', correo='paciente@example.com')
        cita = crear_cita(self.recepcion, paciente=paciente, estado=Cita.ESTADO_PROCESADA)
        orden = OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.recepcion)
        Cobro.objects.create(cita=cita)
        self.client.force_login(self.recepcion)

        self.client.post(reverse('enviar_estudio', args=[cita.id]))

        orden.refresh_from_db()
        self.assertIsNone(orden.resultados_enviados_en)

    def test_historial_paciente_desactiva_el_boton_de_enviar_si_hay_cobro_pendiente(self):
        paciente = crear_paciente(dpi='1112223334448', correo='p3@example.com')
        cita = crear_cita(self.recepcion, paciente=paciente, estado=Cita.ESTADO_PROCESADA)
        OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.recepcion)
        cobro = Cobro.objects.create(cita=cita)
        self.client.force_login(self.recepcion)

        html = self.client.get(
            reverse('historial_paciente', args=[paciente.id])
        ).content.decode('utf-8')
        self.assertIn('Cobro pendiente', html)
        self.assertIn('tiene un cobro pendiente', html)
        self.assertIn('<button type="button" class="btn btn-primary btn-sm" disabled', html)
        self.assertNotIn(f"{reverse('enviar_estudio', args=[cita.id])}", html)

        cobro.marcar_pagado(self.caja)
        html = self.client.get(
            reverse('historial_paciente', args=[paciente.id])
        ).content.decode('utf-8')
        self.assertIn(f"{reverse('enviar_estudio', args=[cita.id])}", html)
        self.assertIn('>Pagado</span>', html)

    def test_sin_cobro_no_bloquea_el_envio(self):
        paciente = crear_paciente(dpi='1112223334447', correo='paciente2@example.com')
        cita = crear_cita(self.recepcion, paciente=paciente, estado=Cita.ESTADO_PROCESADA)
        OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.recepcion)

        self.assertFalse(hasattr(cita, 'cobro'))
        from pacientes.views import _cobro_bloquea_envio
        self.assertFalse(_cobro_bloquea_envio(cita))


class EstudioExtraTests(TestCase):
    """El radiólogo avisa que le realizó al paciente un estudio extra al
    agendado (solo aplica a Privado): sube el total que ve Caja y le
    notifica a recepción."""

    def setUp(self):
        self.recepcion = crear_usuario('recep_extra', rol=Usuario.ROL_RECEPCIONISTA)
        self.radiologo = crear_usuario('rad_extra', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.estudio_agendado = TipoEstudio.objects.create(nombre='RX Torax agendado')
        PrecioEstudio.objects.create(
            tipo_estudio=self.estudio_agendado, convenio=Cita.CONVENIO_PRIVADO,
            horario_habil=True, precio=Decimal('150'),
        )
        self.estudio_extra = TipoEstudio.objects.create(nombre='RX Columna extra')
        PrecioEstudio.objects.create(
            tipo_estudio=self.estudio_extra, convenio=Cita.CONVENIO_PRIVADO,
            horario_habil=True, precio=Decimal('250'),
        )
        self.cita = crear_cita(
            self.recepcion, tipo_estudio=self.estudio_agendado,
            convenio=Cita.CONVENIO_PRIVADO, estado=Cita.ESTADO_EN_PROCESO,
            hora=datetime.time(9, 0),
        )
        OrdenTrabajo.objects.create(cita=self.cita, motivo='x', creada_por=self.recepcion)

    def _agregar(self, notas=''):
        self.client.force_login(self.radiologo)
        return self.client.post(
            reverse('agregar_estudio_extra', args=[self.cita.id]),
            {'tipo_estudio': self.estudio_extra.id, 'notas': notas},
        )

    def test_agregar_estudio_extra_suma_al_precio_de_la_cita(self):
        self.assertEqual(self.cita.precio, Decimal('150'))

        self._agregar()

        self.cita.refresh_from_db()
        self.assertEqual(self.cita.precio_base, Decimal('150'))
        self.assertEqual(self.cita.precio, Decimal('400'))
        extra = EstudioExtra.objects.get(cita=self.cita)
        self.assertEqual(extra.tipo_estudio, self.estudio_extra)
        self.assertEqual(extra.agregado_por, self.radiologo)
        self.assertEqual(extra.precio, Decimal('250'))

    def test_agregar_estudio_extra_notifica_a_recepcion(self):
        self._agregar(notas='Se detectó lesión adicional')

        notificacion = Notificacion.objects.get(
            destinatario=self.recepcion, tipo=Notificacion.TIPO_ESTUDIO_EXTRA_AGREGADO,
        )
        self.assertIn('RX Columna extra', notificacion.mensaje)
        self.assertIn('250.00', notificacion.mensaje)
        self.assertEqual(notificacion.cita, self.cita)

    def test_agregar_estudio_extra_tambien_aplica_a_coex(self):
        cita_coex = crear_cita(
            self.recepcion, tipo_estudio=self.estudio_agendado, convenio=Cita.CONVENIO_COEX,
            estado=Cita.ESTADO_EN_PROCESO, paciente=crear_paciente(dpi='5554443332221'),
        )
        OrdenTrabajo.objects.create(cita=cita_coex, motivo='x', creada_por=self.recepcion)
        self.client.force_login(self.radiologo)

        respuesta = self.client.post(
            reverse('agregar_estudio_extra', args=[cita_coex.id]),
            {'tipo_estudio': self.estudio_extra.id, 'notas': ''},
        )

        self.assertRedirects(
            respuesta,
            reverse('adjuntar_informe', args=[cita_coex.id]),
            fetch_redirect_response=False,
        )
        self.assertTrue(EstudioExtra.objects.filter(cita=cita_coex).exists())

    def test_agregar_estudio_extra_requiere_rol_radiologo(self):
        self.client.force_login(self.recepcion)

        respuesta = self.client.post(
            reverse('agregar_estudio_extra', args=[self.cita.id]),
            {'tipo_estudio': self.estudio_extra.id, 'notas': ''},
        )

        self.assertNotEqual(respuesta.status_code, 200)
        self.assertFalse(EstudioExtra.objects.filter(cita=self.cita).exists())

    def test_boleta_pago_pdf_incluye_el_total_con_estudios_extra(self):
        self._agregar()
        cobro, _ = Cobro.objects.get_or_create(cita=self.cita)
        cobro.marcar_pagado(self.recepcion)
        self.client.force_login(self.recepcion)

        respuesta = self.client.get(reverse('boleta_pago_pdf', args=[cobro.id]))

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.content.startswith(b'%PDF'))
        self.assertEqual(self.cita.precio, Decimal('400'))

    def test_guardar_informe_agrega_estudio_extra_en_el_mismo_envio(self):
        """El estudio extra ya no tiene su propio botón: se agrega al mismo
        tiempo que se guarda el informe, en un solo envío."""
        ImagenEstudio.objects.create(
            orden=self.cita.orden_trabajo, subida_por=self.radiologo,
            archivo=SimpleUploadedFile('img.jpg', b'fake'),
        )
        self.client.force_login(self.radiologo)

        respuesta = self.client.post(reverse('adjuntar_informe', args=[self.cita.id]), {
            'informe_texto': 'Hallazgos sin complicaciones.',
            'tipo_estudio': self.estudio_extra.id,
            'notas': 'agregado junto con el informe',
        })

        self.assertRedirects(respuesta, reverse('citas_procesadas'))
        self.cita.refresh_from_db()
        self.assertEqual(self.cita.estado, Cita.ESTADO_PROCESADA)
        extra = EstudioExtra.objects.get(cita=self.cita)
        self.assertEqual(extra.tipo_estudio, self.estudio_extra)
        self.assertEqual(extra.notas, 'agregado junto con el informe')
        self.assertTrue(
            Notificacion.objects.filter(
                destinatario=self.recepcion, tipo=Notificacion.TIPO_ESTUDIO_EXTRA_AGREGADO,
            ).exists()
        )

    def test_guardar_informe_sin_elegir_estudio_extra_no_crea_nada(self):
        """Elegir un estudio extra es opcional: guardar el informe sin
        tocar ese campo no debe exigirlo ni crear nada."""
        ImagenEstudio.objects.create(
            orden=self.cita.orden_trabajo, subida_por=self.radiologo,
            archivo=SimpleUploadedFile('img.jpg', b'fake'),
        )
        self.client.force_login(self.radiologo)

        respuesta = self.client.post(reverse('adjuntar_informe', args=[self.cita.id]), {
            'informe_texto': 'Hallazgos sin complicaciones.',
        })

        self.assertRedirects(respuesta, reverse('citas_procesadas'))
        self.assertFalse(EstudioExtra.objects.filter(cita=self.cita).exists())


class OrdenPagoTests(TestCase):
    def setUp(self):
        self.caja = crear_usuario('caja_orden', rol=Usuario.ROL_RECEPCIONISTA, puede_operar_caja=True)
        self.paciente = crear_paciente(dpi='7776665554443')
        self.estudio_a = TipoEstudio.objects.create(nombre='COEX Tórax frontal')
        self.estudio_b = TipoEstudio.objects.create(nombre='COEX Tórax lateral')
        for estudio, precio in ((self.estudio_a, 100), (self.estudio_b, 80)):
            PrecioEstudio.objects.create(
                tipo_estudio=estudio, convenio=Cita.CONVENIO_COEX,
                horario_habil=True, precio=Decimal(precio),
            )
        self.cita_a = crear_cita(
            self.caja, paciente=self.paciente, tipo_estudio=self.estudio_a,
            convenio=Cita.CONVENIO_COEX, estado=Cita.ESTADO_EN_PROCESO,
            hora=datetime.time(9, 0),
        )
        self.cita_b = crear_cita(
            self.caja, paciente=self.paciente, tipo_estudio=self.estudio_b,
            convenio=Cita.CONVENIO_COEX, estado=Cita.ESTADO_EN_PROCESO,
            hora=datetime.time(9, 30),
        )
        for cita in (self.cita_a, self.cita_b):
            OrdenTrabajo.objects.create(cita=cita, motivo='demo HU-058', creada_por=self.caja)
            Cobro.objects.create(cita=cita)
        self.client.force_login(self.caja)

    def test_crea_orden_agrupada_para_mismo_paciente_y_convenio(self):
        respuesta = self.client.post(reverse('crear_orden_pago'), {
            'cita_ids': [self.cita_a.id, self.cita_b.id],
            'notas': 'Orden global COEX',
        })

        self.assertRedirects(respuesta, reverse('pagos_pendientes'))
        orden = OrdenPago.objects.get()
        self.assertEqual(orden.convenio, Cita.CONVENIO_COEX)
        self.assertEqual(orden.paciente, self.paciente)
        self.assertEqual(orden.subtotal, Decimal('180.00'))
        self.assertEqual(orden.total, Decimal('180.00'))
        self.assertEqual(orden.detalles.count(), 2)

    def test_pagar_orden_agrupada_liquida_todos_los_cobros(self):
        self.client.post(reverse('crear_orden_pago'), {
            'cita_ids': [self.cita_a.id, self.cita_b.id],
        })
        orden = OrdenPago.objects.get()
        boleta = SimpleUploadedFile('boleta-global.pdf', b'pdf demo', content_type='application/pdf')
        respuesta = self.client.post(
            reverse('pagar_orden_pago', args=[orden.id]),
            {
                'forma_pago': Cobro.FORMA_TRANSFERENCIA,
                'numero_boleta': 'COEX-GLOBAL-001',
                'comprobante_bancario': boleta,
                'notas': 'Pago global',
            },
        )

        self.assertRedirects(respuesta, reverse('pagos_pendientes'))
        orden.refresh_from_db()
        self.assertEqual(orden.estado, OrdenPago.ESTADO_PAGADA)
        self.assertTrue(orden.comprobante_bancario)
        self.assertTrue(Cobro.objects.get(cita=self.cita_a).pagado)
        self.assertTrue(Cobro.objects.get(cita=self.cita_b).pagado)

    def test_no_permite_mezclar_pacientes_en_orden_agrupada(self):
        otro = crear_cita(
            self.caja, paciente=crear_paciente(dpi='7776665554444'),
            tipo_estudio=self.estudio_a, convenio=Cita.CONVENIO_COEX,
            estado=Cita.ESTADO_EN_PROCESO, hora=datetime.time(10, 0),
        )
        OrdenTrabajo.objects.create(cita=otro, motivo='demo HU-058', creada_por=self.caja)
        Cobro.objects.create(cita=otro)

        respuesta = self.client.post(reverse('crear_orden_pago'), {
            'cita_ids': [self.cita_a.id, otro.id],
        })

        self.assertRedirects(respuesta, reverse('pagos_pendientes'))
        self.assertFalse(OrdenPago.objects.exists())

    def test_orden_pendiente_mantiene_bloqueado_el_envio(self):
        self.client.post(reverse('crear_orden_pago'), {'cita_ids': [self.cita_a.id]})
        from pacientes.views import _cobro_bloquea_envio

        self.assertTrue(_cobro_bloquea_envio(self.cita_a))

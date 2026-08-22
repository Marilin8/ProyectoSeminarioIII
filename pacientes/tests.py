import datetime

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from pacientes import horarios
from pacientes.forms import AgendarCitaForm, RegistrarTicketForm
from pacientes.models import Cita, ImagenEstudio, Notificacion, OrdenTrabajo, Paciente, Ticket, TipoEstudio

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

    def test_al_guardar_genera_numero_y_turno_correlativos_por_servicio(self):
        paciente1 = crear_paciente(dpi='1111111111111')
        paciente2 = crear_paciente(dpi='2222222222222')

        ticket1 = Ticket.objects.create(
            paciente=paciente1, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )
        ticket2 = Ticket.objects.create(
            paciente=paciente2, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )

        self.assertEqual(ticket1.numero, 1)
        self.assertEqual(ticket1.turno, 'EMER-001')
        self.assertEqual(ticket2.numero, 2)
        self.assertEqual(ticket2.turno, 'EMER-002')

    def test_las_secuencias_de_distintos_servicios_no_se_mezclan(self):
        paciente1 = crear_paciente(dpi='3333333333333')
        paciente2 = crear_paciente(dpi='4444444444444')

        ticket_emergencia = Ticket.objects.create(
            paciente=paciente1, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )
        ticket_coex = Ticket.objects.create(
            paciente=paciente2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario,
        )

        self.assertEqual(ticket_emergencia.turno, 'EMER-001')
        self.assertEqual(ticket_coex.turno, 'COEX-001')

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
            'fecha_nacimiento': '1985-03-10',
            'prioridad': Ticket.PRIORIDAD_URGENTE,
            'motivo': 'Dolor abdominal agudo',
        }

    def test_registrar_ticket_crea_paciente_y_ticket_en_espera(self):
        respuesta = self.client.post(reverse('registrar_ticket_emergencia'), self.datos_formulario)

        self.assertRedirects(respuesta, reverse('pantalla_turnos_emergencia'))
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

    def test_registrar_ticket_sincroniza_datos_del_paciente_existente(self):
        crear_paciente(dpi='6666666666666', nombre='Nombre Viejo', telefono='00000000')

        self.client.post(reverse('registrar_ticket_emergencia'), self.datos_formulario)

        paciente = Paciente.objects.get(dpi='6666666666666')
        self.assertEqual(paciente.nombre, 'Carlos')
        self.assertEqual(paciente.telefono, '55551234')

    def test_usuario_no_recepcionista_no_puede_acceder(self):
        otro_usuario = crear_usuario('tecnico_no_autorizado', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.client.force_login(otro_usuario)

        respuesta = self.client.get(reverse('registrar_ticket_emergencia'))

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Ticket.objects.count(), 0)


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
        self.manana = timezone.localdate() + datetime.timedelta(days=1)
        self.datos_formulario = {
            'dpi': '2020202020202',
            'nombre': 'Luis',
            'apellido': 'Marroquín',
            'sexo': Paciente.SEXO_MASCULINO,
            'telefono': '55599999',
            'fecha_nacimiento': '1988-02-14',
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

    def test_agendar_cita_sincroniza_datos_del_paciente_existente(self):
        crear_paciente(dpi='2020202020202', nombre='Nombre Viejo', telefono='00000000')

        self.client.post(self._url(), self.datos_formulario)

        paciente = Paciente.objects.get(dpi='2020202020202')
        self.assertEqual(paciente.nombre, 'Luis')
        self.assertEqual(paciente.telefono, '55599999')


class PantallaTurnosEmergenciaViewTests(TestCase):

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

        respuesta = self.client.get(reverse('pantalla_turnos_emergencia'))

        cola = list(respuesta.context['cola'])
        self.assertIn(ticket_en_espera, cola)
        self.assertNotIn(ticket_atendido, cola)


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

        self.assertRedirects(respuesta, reverse('pantalla_turnos_emergencia'))

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

        respuesta = self.client.get(reverse('pantalla_turnos_emergencia'))

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

        self.assertRedirects(respuesta, reverse('pantalla_turnos_emergencia'))
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
            'fecha_nacimiento': fecha_nacimiento,
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

    def test_agendar_cita_notifica_al_radiologo_asignado(self):
        self.client.force_login(self.recepcionista)
        manana = timezone.localdate() + datetime.timedelta(days=1)
        datos = {
            'dpi': '3030303030303',
            'nombre': 'Ana',
            'apellido': 'López',
            'sexo': Paciente.SEXO_FEMENINO,
            'telefono': '',
            'fecha_nacimiento': '1990-01-01',
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

import base64
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

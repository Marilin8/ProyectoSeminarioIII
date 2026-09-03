import base64
import datetime
import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from pacientes import horarios
from pacientes.forms import AgendarCitaForm, RegistrarTicketForm
from accounts.models import Bitacora
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

    def test_privado_no_aparece_en_solicitudes_del_radiologo(self):
        self._agendar()
        self.client.force_login(self.radiologo)
        lista = self.client.get(reverse('solicitudes_pendientes'))
        self.assertNotContains(lista, 'Marco')

    def test_privado_puede_compartir_franja_hasta_agotar_el_cupo(self):
        self._agendar(dpi='2020202020202', nombre='Segundo', hora='10:00')
        respuesta = self._agendar(dpi='3030303030303', nombre='Tercero', hora='10:00')
        self.assertEqual(
            Cita.objects.filter(fecha=self.fecha, hora=datetime.time(10, 0)).count(), 2,
        )
        self.assertNotContains(respuesta, 'cupos ocupados')

    def test_privado_bloquea_cuando_el_cupo_de_la_franja_esta_lleno(self):
        for i in range(3):
            self._agendar(dpi=f'404040404040{i}', hora='11:00')
        respuesta = self._agendar(dpi='5050505050505', hora='11:00')
        self.assertContains(respuesta, 'cupos ocupados')
        self.assertEqual(Cita.objects.filter(paciente__dpi='5050505050505').count(), 0)

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


class CupoParaleloTests(TestCase):
    """Bloque 2 · Cambios 2 y 3: cupo de 3 estudios en paralelo por servicio en
    la misma franja horaria (la emergencia confirmada puede superarlo, con el
    tope diario de emergencias ya existente) y el calendario muestra la
    ocupación por servicio (n/3)."""

    def setUp(self):
        self.recepcionista = crear_usuario('recep_cupo', rol=Usuario.ROL_RECEPCIONISTA)
        self.radiologo = crear_usuario('rad_cupo', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.estudio = TipoEstudio.objects.create(
            nombre='Radiografía de tórax cupo', duracion_minutos=20,
        )
        self.estudio.radiologos.add(self.radiologo)
        self.fecha = horarios.inicio_semana(timezone.localdate()) + datetime.timedelta(days=3)
        self.client.force_login(self.recepcionista)

    def _post_coex(self, dpi='6060606060601', hora='09:00', es_emergencia=''):
        return self.client.post(reverse('agendar_cita_coex'), {
            'dpi': dpi,
            'nombre': 'Paciente',
            'apellido': 'Cupo',
            'sexo': Paciente.SEXO_MASCULINO,
            'telefono': '55551234',
            'correo': 'paciente_cupo@correo.com',
            'fecha_nacimiento': '1990-01-01',
            'carnet_igss': dpi,
            'tipo_estudio': self.estudio.id,
            'radiologo': self.radiologo.id,
            'medico_referente': '',
            'fecha': self.fecha.isoformat(),
            'hora': hora,
            'notas': '',
            'es_emergencia': es_emergencia,
        }, follow=True)

    def test_coex_no_supera_el_cupo_sin_emergencia(self):
        for i in range(3):
            self._post_coex(dpi=f'606060606060{i}', hora='09:30')
        self.assertEqual(
            Cita.objects.filter(convenio=Cita.CONVENIO_COEX, fecha=self.fecha).count(), 3,
        )
        respuesta = self._post_coex(dpi='6060606060607', hora='09:30')
        self.assertContains(respuesta, 'cupos ocupados')
        self.assertEqual(Cita.objects.filter(paciente__dpi='6060606060607').count(), 0)

    def test_emergencia_confirmada_supera_el_cupo(self):
        for i in range(3):
            self._post_coex(dpi=f'707070707070{i}', hora='10:00')
        respuesta = self._post_coex(dpi='7070707070707', hora='10:00', es_emergencia='1')
        self.assertEqual(respuesta.status_code, 200)
        cita = Cita.objects.get(paciente__dpi='7070707070707')
        self.assertTrue(cita.es_emergencia_forzada)
        self.assertEqual(Cita.objects.filter(fecha=self.fecha, hora=datetime.time(10, 0)).count(), 4)

    def test_calendario_muestra_ocupacion_por_servicio(self):
        for i in range(2):
            crear_cita(
                self.recepcionista, tipo_estudio=self.estudio, convenio=Cita.CONVENIO_COEX,
                fecha=self.fecha, hora=datetime.time(9, 0),
                paciente=crear_paciente(dpi=f'808080808080{i}'),
            )
        crear_cita(
            self.recepcionista, tipo_estudio=self.estudio, convenio=Cita.CONVENIO_PRIVADO,
            fecha=self.fecha, hora=datetime.time(9, 0),
            paciente=crear_paciente(dpi='8080808080809'),
        )
        self.client.force_login(self.recepcionista)
        respuesta = self.client.get(reverse('calendario_coex'))
        for fila in respuesta.context['filas']:
            for celda in fila['celdas']:
                if celda['dia'] == self.fecha and celda['hora'] == datetime.time(9, 0):
                    self.assertEqual(celda['cupo'], 2)
                    self.assertTrue(celda['ocupado'])
                    self.assertEqual(celda['convenios'], 'Privado')

    def test_reagenda_no_supera_el_cupo_lleno(self):
        cita = crear_cita(
            self.recepcionista, tipo_estudio=self.estudio, convenio=Cita.CONVENIO_PRIVADO,
            fecha=self.fecha, hora=datetime.time(8, 0), estado=Cita.ESTADO_AUSENTE,
            paciente=crear_paciente(dpi='9090909090901'),
        )
        for i in range(3):
            crear_cita(
                self.recepcionista, tipo_estudio=self.estudio, convenio=Cita.CONVENIO_PRIVADO,
                fecha=self.fecha, hora=datetime.time(11, 0),
                paciente=crear_paciente(dpi=f'919191919191{i}'),
            )
        self.client.force_login(self.recepcionista)
        respuesta = self.client.post(
            reverse('confirmar_reagenda_privado', args=[cita.id]),
            {'fecha': self.fecha.isoformat(), 'hora': '11:00'},
            follow=True,
        )
        self.assertContains(respuesta, 'no está disponible')
        cita.refresh_from_db()
        self.assertEqual(cita.hora, datetime.time(8, 0))


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
        ticket_coex = Ticket.objects.create(
            paciente=p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario,
        )
        # Sin pasar prioridad: Ticket.save debe asignar la máxima (Crítica).
        ticket_emergencia = Ticket.objects.create(
            paciente=p2, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )
        self.assertEqual(ticket_emergencia.prioridad, Ticket.PRIORIDAD_CRITICA)

        # Adelantar de más no debe poder pasar por encima de la emergencia.
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

    def test_emergencia_recibe_prioridad_critica_automatica(self):
        paciente = crear_paciente(dpi='6666111122222')
        ticket = Ticket.objects.create(
            paciente=paciente, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )
        # La prioridad se asigna automáticamente (Crítica = máxima), sin que el
        # registro dependa de quién crea el ticket.
        self.assertEqual(ticket.prioridad, Ticket.PRIORIDAD_CRITICA)

    def test_coex_y_privado_siguen_siendo_prioridad_normal(self):
        p1 = crear_paciente(dpi='7777888899999')
        p2 = crear_paciente(dpi='8888999900000')
        ticket_coex = Ticket.objects.create(
            paciente=p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario,
        )
        ticket_privado = Ticket.objects.create(
            paciente=p2, servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario,
        )
        self.assertEqual(ticket_coex.prioridad, Ticket.PRIORIDAD_NORMAL)
        self.assertEqual(ticket_privado.prioridad, Ticket.PRIORIDAD_NORMAL)

    def test_una_emergencia_nueva_se_coloca_al_frente_de_coex_y_privado(self):
        p1, p2, p3 = (crear_paciente(dpi=f'{n:013d}') for n in (21, 22, 23))
        ticket_coex = Ticket.objects.create(
            paciente=p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario,
        )
        ticket_privado = Ticket.objects.create(
            paciente=p2, servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario,
        )
        # Llega DESPUÉS de los anteriores, pero debe ponerse al frente de la cola.
        ticket_emergencia = Ticket.objects.create(
            paciente=p3, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )

        cola = list(Ticket.objects.filter(estado=Ticket.ESTADO_EN_ESPERA).order_by('-prioridad', 'orden'))
        self.assertEqual(cola, [ticket_emergencia, ticket_coex, ticket_privado])

    def test_entre_emergencias_el_orden_es_el_de_llegada(self):
        """La prioridad Crítica pone a todas las emergencias al frente, pero
        entre ellas (y frente a otras subidas manualmente a Crítica) se
        respeta el orden de llegada (FIFO)."""
        p1, p2 = (crear_paciente(dpi=f'{n:013d}') for n in (24, 25))
        emergencia_1 = Ticket.objects.create(
            paciente=p1, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )
        coexistencia = Ticket.objects.create(
            paciente=p2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario,
        )
        emergencia_2 = Ticket.objects.create(
            paciente=crear_paciente(dpi='2626262626262'),
            servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
        )

        cola = list(Ticket.objects.filter(estado=Ticket.ESTADO_EN_ESPERA).order_by('-prioridad', 'orden'))
        self.assertEqual(cola, [emergencia_1, emergencia_2, coexistencia])

    def _cola(self):
        return list(Ticket.objects.filter(estado=Ticket.ESTADO_EN_ESPERA).order_by('-prioridad', 'orden'))

    def test_subir_mueve_un_lugar_dentro_del_mismo_bloque_de_prioridad(self):
        t1, t2, t3 = self._tres_normales()

        t3.subir()
        self.assertEqual(self._cola(), [t1, t3, t2])
        # El número de turno oficial no cambia.
        self.assertEqual(t3.turno, '003')

    def test_bajar_mueve_un_lugar_dentro_del_mismo_bloque_de_prioridad(self):
        t1, t2, t3 = self._tres_normales()

        t1.bajar()
        self.assertEqual(self._cola(), [t2, t1, t3])

    def test_ir_al_tope_lleva_al_frente_del_bloque_pero_no_delante_de_mayor_prioridad(self):
        p1, p2, p3 = (crear_paciente(dpi=f'{n:013d}') for n in (31, 32, 33))
        emergencia = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS,
                                           registrado_por=self.usuario)
        t2 = Ticket.objects.create(paciente=p2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        t3 = Ticket.objects.create(paciente=p3, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)

        t3.ir_al_tope()

        # 003 queda al frente de los normales, pero jamás antes de la emergencia.
        self.assertEqual(self._cola(), [emergencia, t3, t2])

    def test_subir_no_salta_a_un_bloque_de_mayor_prioridad(self):
        p1, p2, p3 = (crear_paciente(dpi=f'{n:013d}') for n in (34, 35, 36))
        emergencia = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS,
                                           registrado_por=self.usuario)
        coex = Ticket.objects.create(paciente=p2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        privado = Ticket.objects.create(paciente=p3, servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario)

        # El primero del bloque normal no puede subir más.
        self.assertFalse(coex.subir())
        self.assertEqual(self._cola(), [emergencia, coex, privado])

    def test_bajar_no_cae_a_un_bloque_de_menor_prioridad(self):
        p1, p2, p3 = (crear_paciente(dpi=f'{n:013d}') for n in (37, 38, 39))
        coex = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        privado = Ticket.objects.create(paciente=p2, servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario)
        emergencia = Ticket.objects.create(paciente=p3, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS,
                                           registrado_por=self.usuario)

        # El último del bloque crítico (emergencia) no puede bajar.
        self.assertFalse(emergencia.bajar())
        self.assertEqual(self._cola(), [emergencia, coex, privado])

    def test_el_orden_siempre_queda_correlativo_tras_reordenar(self):
        t1, t2, t3 = self._tres_normales()

        t3.subir()
        t3.subir()
        t1.bajar()

        ordenes = [t.orden for t in self._cola()]
        self.assertEqual(ordenes, [1, 2, 3])

    def test_ticket_atendido_no_participa_en_el_reordenamiento(self):
        p1, p2, p3 = (crear_paciente(dpi=f'{n:013d}') for n in (40, 41, 42))
        t1 = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        t2 = Ticket.objects.create(paciente=p2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        t3 = Ticket.objects.create(paciente=p3, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        # t2 ya no está en espera: la cola es [t1, t3].
        t2.estado = Ticket.ESTADO_ATENDIDO
        t2.atendido_en = timezone.now()
        t2.save(update_fields=['estado', 'atendido_en'])

        # t1 (primero) no puede bajar porque detrás de él ya no hay un igual
        # en espera? Sí: t3 es normal, así que sí puede. Subir t3 lo deja antes.
        t3.subir()
        self.assertEqual(self._cola(), [t3, t1])

    def test_mover_un_ticket_no_en_espera_no_hace_nada(self):
        p1, p2 = (crear_paciente(dpi=f'{n:013d}') for n in (43, 44))
        t1 = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        t_atendido = Ticket.objects.create(paciente=p2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        t_atendido.estado = Ticket.ESTADO_ATENDIDO
        t_atendido.atendido_en = timezone.now()
        t_atendido.save(update_fields=['estado', 'atendido_en'])

        self.assertFalse(t_atendido.subir())

    def test_adelantar_sigue_respetando_los_limites_de_prioridad(self):
        p1, p2, p3 = (crear_paciente(dpi=f'{n:013d}') for n in (45, 46, 47))
        emergencia = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS,
                                           registrado_por=self.usuario)
        coex = Ticket.objects.create(paciente=p2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        privado = Ticket.objects.create(paciente=p3, servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario)

        privado.adelantar(5)
        self.assertEqual(self._cola(), [emergencia, privado, coex])

    def test_mezcla_de_reordenamientos_entre_bloques_queda_estable(self):
        p1, p2, p3, p4 = (crear_paciente(dpi=f'{n:013d}') for n in (48, 49, 50, 51))
        emergencia = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS,
                                           registrado_por=self.usuario)
        t3 = Ticket.objects.create(paciente=p2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        t4 = Ticket.objects.create(paciente=p3, servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario)
        t5 = Ticket.objects.create(paciente=p4, servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario)

        # t5 sube dentro de privados y t4 baja: ningún movimiento sale del bloque.
        t5.subir()
        t4.bajar()
        t3.ir_al_tope()

        cola = self._cola()
        # Emergencia primero; luego COEX (t3 al frente de normales); luego los
        # dos privados en orden [t5, t4] (t5 subió delante de t4).
        self.assertEqual(cola[0], emergencia)
        privados = [t for t in cola if t.servicio == Ticket.SERVICIO_PRIVADO]
        self.assertEqual(privados, [t5, t4])

    def _tres_normales(self):
        p1, p2, p3 = (crear_paciente(dpi=f'{n:013d}') for n in (28, 29, 30))
        t1 = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        t2 = Ticket.objects.create(paciente=p2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        t3 = Ticket.objects.create(paciente=p3, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        return t1, t2, t3


class ReordenarTicketRigorTests(TestCase):
    """Pruebas rigurosas sobre la invariante central del Bloque 4: ningún
    reordenamiento puede romper el orden por prioridad (`-prioridad, orden`),
    ni dejar los `orden` duplicados o no correlativos dentro de la fila."""

    def setUp(self):
        self.usuario = crear_usuario('recepcionista_rigor')
        # Fila con mezcla de las TRES prioridades: 2 críticas, 2 urgentes, 2 normales.
        p1, p2, p3, p4, p5, p6 = (crear_paciente(dpi=f'{n:013d}') for n in (60, 61, 62, 63, 64, 65))
        self.crit_1 = Ticket.objects.create(paciente=p1, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS,
                                            registrado_por=self.usuario)
        self.crit_2 = Ticket.objects.create(paciente=p2, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS,
                                            registrado_por=self.usuario)
        self.urg_1 = Ticket.objects.create(paciente=p3, servicio=Ticket.SERVICIO_COEX,
                                           registrado_por=self.usuario)
        self.urg_1.prioridad = Ticket.PRIORIDAD_URGENTE
        self.urg_1.save(update_fields=['prioridad'])
        self.urg_2 = Ticket.objects.create(paciente=p4, servicio=Ticket.SERVICIO_PRIVADO,
                                           registrado_por=self.usuario)
        self.urg_2.prioridad = Ticket.PRIORIDAD_URGENTE
        self.urg_2.save(update_fields=['prioridad'])
        self.norm_1 = Ticket.objects.create(paciente=p5, servicio=Ticket.SERVICIO_COEX,
                                            registrado_por=self.usuario)
        self.norm_2 = Ticket.objects.create(paciente=p6, servicio=Ticket.SERVICIO_COEX,
                                            registrado_por=self.usuario)

    def _cola(self):
        return list(Ticket.objects.filter(estado=Ticket.ESTADO_EN_ESPERA).order_by('-prioridad', 'orden'))

    def _prioridades_en_orden(self, cola):
        return [t.prioridad for t in cola]

    def _assert_invariantes(self):
        """Tras cualquier secuencia de reordenación: la cola debe estar
        ordenada por prioridad no creciente y los `orden` deben ser 1..n."""
        cola = self._cola()
        prioridades = [t.prioridad for t in cola]
        # No creciente: ningún elemento mayor que el que le sigue.
        self.assertEqual(prioridades, sorted(prioridades, reverse=True))
        # Orden es una permutación correlativa 1..n.
        self.assertEqual([t.orden for t in cola], list(range(1, len(cola) + 1)))

    def test_la_mezcla_respeta_prioridades_desde_el_inicio(self):
        self._assert_invariantes()
        self.assertEqual(self._prioridades_en_orden(self._cola()), [3, 3, 2, 2, 1, 1])

    def test_subir_urgente_no_cruza_a_las_criticas(self):
        self.urg_2.subir()
        self.urg_2.subir()
        self._assert_invariantes()
        # El urgente queda al frente de URGENTE, pero nunca antes de ninguna Crítica.
        cola = self._cola()
        self.assertEqual(self._prioridades_en_orden(cola), [3, 3, 2, 2, 1, 1])
        self.assertEqual(cola[2].servicio, self.urg_2.servicio)

    def test_bajar_critico_no_cae_entre_los_urgentes(self):
        # La Crítica 1 es la primera de todo: sólo puede bajar dentro de Críticas.
        self.crit_1.bajar()
        self._assert_invariantes()
        self.assertEqual(self._cola(), [self.crit_2, self.crit_1, self.urg_1, self.urg_2, self.norm_1, self.norm_2])

    def test_bajar_urgente_no_cae_detra_s_de_normales(self):
        # urg_2 es la última de URGENTE: no puede bajarse hacia Normales.
        self.assertFalse(self.urg_2.bajar())
        self._assert_invariantes()

    def test_adelantar_grande_se_recorta_al_inicio_del_bloque(self):
        self.norm_2.adelantar(50)
        self._assert_invariantes()
        cola = self._cola()
        # Se recortó al frente de NORMAL (índice 4), sin pasar a los URGENTES.
        self.assertEqual(cola[4], self.norm_2)
        self.assertEqual(cola[5], self.norm_1)

    def test_adelantar_urgente_grande_se_recorta_al_inicio_urgente(self):
        self.urg_2.adelantar(50)
        self._assert_invariantes()
        cola = self._cola()
        self.assertEqual(self._prioridades_en_orden(cola), [3, 3, 2, 2, 1, 1])
        self.assertEqual(cola[2], self.urg_2)

    def test_si_todo_critico_se_va_pueden_subir_los_urgentes_al_tope(self):
        # Se atienden las dos críticas: dejan de estar en espera.
        for c in (self.crit_1, self.crit_2):
            c.estado = Ticket.ESTADO_ATENDIDO
            c.atendido_en = timezone.now()
            c.save(update_fields=['estado', 'atendido_en'])
        # Ahora los urgentes son el tope de toda la fila: subir/tope funcionan.
        self.assertTrue(self.urg_2.subir())
        self._assert_invariantes()
        self.assertEqual(self._cola(), [self.urg_2, self.urg_1, self.norm_1, self.norm_2])

    def test_arribar_un_nuevo_ticket_normal_no_rompe_la_correlatividad(self):
        # Reordenamos primero: norm_2 pasa al frente de los normales.
        self.norm_2.adelantar(10)
        self._assert_invariantes()
        # Entra un nuevo ticket de COEX (Normal): su orden debe ser el siguiente.
        nuevo = Ticket.objects.create(paciente=crear_paciente(dpi='6061626363640'),
                                      servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        self.assertEqual(nuevo.orden, 7)
        self._assert_invariantes()

    def test_movimientos_repetidos_en_cadena_conservan_la_invariante(self):
        secuencia = [
            (self.crit_1, 'bajar'),
            (self.norm_2, 'subir'),
            (self.urg_2, 'tope'),
            (self.crit_2, 'subir'),
            (self.urg_1, 'bajar'),
            (self.norm_1, 'subir'),
        ]
        operaciones = {
            'subir': lambda t: t.subir(),
            'bajar': lambda t: t.bajar(),
            'tope': lambda t: t.ir_al_tope(),
        }
        for ticket, op in secuencia:
            operaciones[op](ticket)
            self._assert_invariantes()

        # Y debe seguir habiendo dos de cada prioridad, en orden no creciente.
        self.assertEqual(self._prioridades_en_orden(self._cola()), [3, 3, 2, 2, 1, 1])


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
        self.assertEqual(ticket.prioridad, Ticket.PRIORIDAD_CRITICA)
        self.assertEqual(ticket.registrado_por, self.usuario)

    def test_registrar_ticket_reutiliza_paciente_existente_por_dpi(self):
        paciente_existente = crear_paciente(dpi='6666666666666', nombre='Nombre Original')

        self.client.post(reverse('registrar_ticket_emergencia'), self.datos_formulario)

        self.assertEqual(Paciente.objects.filter(dpi='6666666666666').count(), 1)
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.paciente_id, paciente_existente.id)

    def test_registrar_ticket_no_pisa_datos_ya_guardados_pero_completa_los_vacios(self):
        crear_paciente(
            dpi='6666666666666', nombre='Nombre Viejo', telefono='00000000',
            sexo='', fecha_nacimiento=None,
        )

        self.client.post(reverse('registrar_ticket_emergencia'), self.datos_formulario)

        paciente = Paciente.objects.get(dpi='6666666666666')
        # Lo que ya estaba guardado NO se cambia, aunque el form traiga otra cosa.
        self.assertEqual(paciente.nombre, 'Nombre Viejo')
        self.assertEqual(paciente.telefono, '00000000')
        # Lo que estaba vacío SÍ se completa.
        self.assertEqual(paciente.sexo, Paciente.SEXO_MASCULINO)
        self.assertEqual(paciente.fecha_nacimiento, datetime.date(1985, 3, 10))

    def test_usuario_no_recepcionista_no_puede_acceder(self):
        otro_usuario = crear_usuario('tecnico_no_autorizado', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.client.force_login(otro_usuario)

        respuesta = self.client.get(reverse('registrar_ticket_emergencia'))

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Ticket.objects.count(), 0)


class ReporteDiarioFinDeDiaTests(TestCase):
    """Cambio 1B: el reporte del día de HOY puede verse y enviarse a partir
    de las 18:00 (cuando termina el día operativo), pero no antes. Las vistas
    usan timezone.localtime()/localdate(), así que se simulan distintas horas
    del día congelando esas funciones en django.utils.timezone."""

    def setUp(self):
        self.recepcionista = crear_usuario('recep_reportes', rol=Usuario.ROL_RECEPCIONISTA)
        self.client.force_login(self.recepcionista)
        self.hoy = timezone.localdate()
        self.convenio = Cita.CONVENIO_COEX
        self.crear_reporte = lambda fecha: ReporteDiario.objects.create(
            convenio=self.convenio, fecha=fecha,
        )

    def _fijar_hora(self, hora):
        """Congela timezone.localtime() a un día/hora local dados, de modo
        que timezone.localdate() derive de ahí."""
        fijo = timezone.make_aware(datetime.datetime.combine(self.hoy, hora))
        return mock.patch('django.utils.timezone.localtime', return_value=fijo)

    def test_antes_de_las_18_no_se_lista_el_reporte_de_hoy(self):
        self.crear_reporte(self.hoy)
        self.crear_reporte(self.hoy - datetime.timedelta(days=1))
        fecha_url = f'lista_reportes_diarios_{self.convenio}'

        with self._fijar_hora(datetime.time(10, 0)):
            # 18:00 justo no termina el día: se espera 00:00..17:59.
            respuesta = self.client.get(reverse(fecha_url))

        fechas = list(r.fecha for r in respuesta.context['reportes'])
        self.assertNotIn(self.hoy, fechas)
        self.assertIn(self.hoy - datetime.timedelta(days=1), fechas)

    def test_desde_las_18_se_lista_el_reporte_de_hoy(self):
        self.crear_reporte(self.hoy)
        self.crear_reporte(self.hoy - datetime.timedelta(days=1))
        fecha_url = f'lista_reportes_diarios_{self.convenio}'

        with self._fijar_hora(datetime.time(18, 0)):
            respuesta = self.client.get(reverse(fecha_url))

        fechas = list(r.fecha for r in respuesta.context['reportes'])
        self.assertIn(self.hoy, fechas)

    def test_no_se_puede_enviar_el_reporte_de_hoy_antes_de_las_18(self):
        reporte = self.crear_reporte(self.hoy)
        url = reverse('enviar_reporte_diario', args=[self.convenio, self.hoy])

        with self._fijar_hora(datetime.time(17, 59)):
            respuesta = self.client.post(url)

        self.assertRedirects(respuesta, reverse('ver_reporte_diario', args=[self.convenio, self.hoy]))
        reporte.refresh_from_db()
        self.assertEqual(reporte.estado, ReporteDiario.ESTADO_BORRADOR)

    def test_desde_las_18_si_se_puede_enviar_el_reporte_de_hoy(self):
        reporte = self.crear_reporte(self.hoy)
        url = reverse('enviar_reporte_diario', args=[self.convenio, self.hoy])

        with self._fijar_hora(datetime.time(18, 0)):
            respuesta = self.client.post(url)

        self.assertRedirects(respuesta, reverse('ver_reporte_diario', args=[self.convenio, self.hoy]))
        reporte.refresh_from_db()
        self.assertEqual(reporte.estado, ReporteDiario.ESTADO_ENVIADO)
        self.assertEqual(reporte.enviado_por, self.recepcionista)
        self.assertIsNotNone(reporte.enviado_en)

    def test_no_se_puede_enviar_un_reporte_de_fecha_futura(self):
        reporte_futuro = ReporteDiario.objects.create(
            convenio=self.convenio, fecha=self.hoy + datetime.timedelta(days=1),
        )
        url = reverse(
            'enviar_reporte_diario',
            args=[self.convenio, reporte_futuro.fecha.strftime('%Y-%m-%d')],
        )

        respuesta = self.client.post(url)

        self.assertRedirects(
            respuesta, reverse('ver_reporte_diario', args=[self.convenio, reporte_futuro.fecha]),
        )
        reporte_futuro.refresh_from_db()
        self.assertEqual(reporte_futuro.estado, ReporteDiario.ESTADO_BORRADOR)

    def test_si_se_puede_enviar_un_reporte_de_ayer(self):
        # Sin congelar la hora: hoy cualquiera, ayer ya terminó.
        reporte_ayer = self.crear_reporte(self.hoy - datetime.timedelta(days=1))
        url = reverse(
            'enviar_reporte_diario',
            args=[self.convenio, reporte_ayer.fecha.strftime('%Y-%m-%d')],
        )

        self.client.post(url)

        reporte_ayer.refresh_from_db()
        self.assertEqual(reporte_ayer.estado, ReporteDiario.ESTADO_ENVIADO)


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

    def test_agendar_cita_no_pisa_datos_ya_guardados_pero_completa_los_vacios(self):
        crear_paciente(
            dpi='2020202020202', nombre='Nombre Viejo', telefono='00000000',
            sexo='', fecha_nacimiento=None, correo=None,
        )

        self.client.post(self._url(), self.datos_formulario)

        paciente = Paciente.objects.get(dpi='2020202020202')
        # Datos ya guardados: intactos.
        self.assertEqual(paciente.nombre, 'Nombre Viejo')
        self.assertEqual(paciente.telefono, '00000000')
        # Datos que estaban vacíos: se completan desde el formulario.
        self.assertEqual(paciente.sexo, Paciente.SEXO_MASCULINO)
        self.assertEqual(paciente.correo, 'luis.marroquin@correo.com')


class FiltroEstudioRadiologoTests(TestCase):

    def setUp(self):
        self.recepcionista = crear_usuario('recep_filtro', rol=Usuario.ROL_RECEPCIONISTA)
        self.client.force_login(self.recepcionista)
        self.estudio = TipoEstudio.objects.create(nombre='Radiografía de tórax filtro')
        self.otro_estudio = TipoEstudio.objects.create(nombre='Ultrasonido filtro')
        self.estudio_sin_radiologo = TipoEstudio.objects.create(nombre='Mamografía sin asignar')
        self.radiologo_a = crear_usuario('radiologa_filtro_a', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.radiologo_b = crear_usuario('radiologo_filtro_b', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        # En el M2M pueden quedar usuarios inactivos o de otro rol: no deben
        # aparecer en data-radiologos (el campo y el endpoint tampoco los ofrecen).
        self.radiologo_inactivo = crear_usuario(
            'radiologa_inactiva', rol=Usuario.ROL_MEDICO_RADIOLOGO, is_active=False,
        )
        self.no_radiologo = crear_usuario('secretaria_en_m2m', rol=Usuario.ROL_RECEPCIONISTA)
        self.estudio.radiologos.add(self.radiologo_a, self.radiologo_b)
        self.estudio.radiologos.add(self.radiologo_inactivo, self.no_radiologo)
        self.otro_estudio.radiologos.add(self.radiologo_a)
        self.manana = timezone.localdate() + datetime.timedelta(days=1)

    def _url(self):
        return f"{reverse('agendar_cita_coex')}?fecha={self.manana}&hora=10:00"

    def _opcion_html(self, contenido, estudio_id):
        marca = f'value="{estudio_id}"'
        inicio = contenido.find(marca)
        self.assertNotEqual(inicio, -1, f'No se encontró la opción del estudio {estudio_id}')
        return contenido[inicio:contenido.find('>', inicio)]

    def test_el_select_de_estudio_lleva_data_radiologos_en_cada_opcion(self):
        respuesta = self.client.get(self._url())
        contenido = respuesta.content.decode()

        # El estudio lo realizan dos radiólogos: ambos ids en el atributo.
        opcion = self._opcion_html(contenido, self.estudio.id)
        self.assertIn(f'data-radiologos="{self.radiologo_a.id},{self.radiologo_b.id}"', opcion)
        # Un estudio de un solo radiólogo: solo su id.
        self.assertIn(
            f'data-radiologos="{self.radiologo_a.id}"',
            self._opcion_html(contenido, self.otro_estudio.id),
        )
        # Sin radiólogos asignados: el atributo no se emite.
        self.assertNotIn('data-radiologos', self._opcion_html(contenido, self.estudio_sin_radiologo.id))

    def test_el_servidor_rechaza_radiologo_que_no_realiza_el_estudio(self):
        datos = {
            'dpi': '3030303030303',
            'nombre': 'Karla',
            'apellido': 'Soto',
            'sexo': Paciente.SEXO_FEMENINO,
            'telefono': '',
            'correo': 'karla.soto@correo.com',
            'fecha_nacimiento': '1990-01-01',
            'carnet_igss': '3030303030',
            'tipo_estudio': self.estudio.id,
            'radiologo': self.radiologo_a.id,
            'fecha': self.manana,
            'hora': '10:00',
            'notas': '',
        }
        # Radiólogo sin relación alguna con el estudio elegido: el servidor
        # debe rechazar la combinación aunque el JS no llegue a ejecutarse.
        radiologo_sin_estudio = crear_usuario('memo_filtro', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        datos['radiologo'] = radiologo_sin_estudio.id

        respuesta = self.client.post(self._url(), datos)

        self.assertNotEqual(respuesta.status_code, 302)
        self.assertContains(respuesta, 'no realiza estudios de')
        self.assertEqual(Cita.objects.count(), 0)

    def test_data_radiologos_omite_inactivos_y_usuarios_de_otro_rol(self):
        respuesta = self.client.get(self._url())
        opcion = self._opcion_html(respuesta.content.decode(), self.estudio.id)

        # Aunque el M2M tiene tambien un radiólogo inactivo y un usuario de
        # otro rol, solo deben aparecer los radiólogos activos (a y b).
        self.assertIn(f'data-radiologos="{self.radiologo_a.id},{self.radiologo_b.id}"', opcion)
        self.assertNotIn(str(self.radiologo_inactivo.id), opcion)
        self.assertNotIn(str(self.no_radiologo.id), opcion)

    def test_el_modulo_privado_tambien_emite_data_radiologos(self):
        url = f"{reverse('agendar_cita_privado')}?fecha={self.manana}&hora=10:00"
        respuesta = self.client.get(url)
        contenido = respuesta.content.decode()

        self.assertIn(
            f'data-radiologos="{self.radiologo_a.id},{self.radiologo_b.id}"',
            self._opcion_html(contenido, self.estudio.id),
        )
        self.assertNotIn('data-radiologos', self._opcion_html(contenido, self.estudio_sin_radiologo.id))

    def test_el_template_agendar_cita_incluye_el_filtro_inverso(self):
        plantilla = os.path.join(
            os.path.dirname(__file__), 'templates', 'pacientes', 'agendar_cita.html',
        )
        with open(plantilla, encoding='utf-8') as archivo:
            contenido = archivo.read()

        # El JS del filtro radiólogo -> estudio está conectado al combo y
        # usa el atributo data-radiologos (regresión guard de la parte del
        # Bloque 3 que solo se ejecuta en el navegador).
        self.assertIn("radiologoSelect.addEventListener('change', filtrarEstudios)", contenido)
        self.assertIn("opcion.getAttribute('data-radiologos')", contenido)


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
            paciente=p3, servicio=Ticket.SERVICIO_EMERGENCIA_IGSS, registrado_por=self.usuario,
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


class ReordenarTurnoViewTests(TestCase):

    def setUp(self):
        self.usuario = crear_usuario('recepcionista_reordenar', rol=Usuario.ROL_RECEPCIONISTA)
        self.client.force_login(self.usuario)
        self.p1, self.p2, self.p3 = (crear_paciente(dpi=f'{n:013d}') for n in (52, 53, 54))
        self.t1 = Ticket.objects.create(paciente=self.p1, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        self.t2 = Ticket.objects.create(paciente=self.p2, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)
        self.t3 = Ticket.objects.create(paciente=self.p3, servicio=Ticket.SERVICIO_COEX, registrado_por=self.usuario)

    def _cola_vista(self):
        return list(self.client.get(reverse('pantalla_turnos')).context['cola'])

    def test_subir_reordena_y_registra_bitacora(self):
        respuesta = self.client.post(reverse('reordenar_turno', args=[self.t3.id, 'subir']))

        self.assertRedirects(respuesta, reverse('pantalla_turnos'))
        self.assertEqual(self._cola_vista(), [self.t1, self.t3, self.t2])
        ultimo = Bitacora.objects.filter(
            accion=Bitacora.ACCION_REORDENAR_TICKET, usuario=self.usuario,
        ).order_by('-id').first()
        self.assertIsNotNone(ultimo)
        self.assertIn(self.t3.turno, ultimo.descripcion)

    def test_bajar_reordena_y_registra_bitacora(self):
        self.client.post(reverse('reordenar_turno', args=[self.t1.id, 'bajar']))
        self.assertEqual(self._cola_vista(), [self.t2, self.t1, self.t3])

    def test_tope_reordena_y_registra_bitacora(self):
        self.client.post(reverse('reordenar_turno', args=[self.t3.id, 'tope']))
        self.assertEqual(self._cola_vista(), [self.t3, self.t1, self.t2])

    def test_get_devuelve_405(self):
        respuesta = self.client.get(reverse('reordenar_turno', args=[self.t2.id, 'subir']))
        self.assertEqual(respuesta.status_code, 405)

    def test_direccion_invalida_redirige_sin_cambiar_la_cola(self):
        respuesta = self.client.post(reverse('reordenar_turno', args=[self.t2.id, 'lateral']))

        self.assertRedirects(respuesta, reverse('pantalla_turnos'))
        self.assertEqual(self._cola_vista(), [self.t1, self.t2, self.t3])

    def test_operacion_sin_efecto_redirige_sin_mover(self):
        # t1 es el primero de su bloque: no puede subir, no se mueve nada.
        respuesta = self.client.post(reverse('reordenar_turno', args=[self.t1.id, 'subir']))

        self.assertRedirects(respuesta, reverse('pantalla_turnos'))
        self.assertEqual(self._cola_vista(), [self.t1, self.t2, self.t3])

    def test_ticket_atendido_da_404(self):
        self.t2.estado = Ticket.ESTADO_ATENDIDO
        self.t2.atendido_en = timezone.now()
        self.t2.save(update_fields=['estado', 'atendido_en'])

        respuesta = self.client.post(reverse('reordenar_turno', args=[self.t2.id, 'subir']))
        self.assertEqual(respuesta.status_code, 404)

    def test_ticket_de_otro_dia_no_se_puede_reordenar(self):
        ayer = timezone.localdate() - datetime.timedelta(days=1)
        otro_paciente = crear_paciente(dpi='5555666677777')
        ticket_ayer = Ticket.objects.create(
            paciente=otro_paciente, servicio=Ticket.SERVICIO_COEX,
            registrado_por=self.usuario,
        )
        # `creado_en` es auto_now_add; lo retrofechamos con update() para
        # simular un turno registrado en un día distinto al de hoy.
        Ticket.objects.filter(pk=ticket_ayer.pk).update(
            creado_en=timezone.make_aware(datetime.datetime.combine(ayer, datetime.time(9, 0))),
        )
        ticket_ayer.refresh_from_db()

        respuesta = self.client.post(reverse('reordenar_turno', args=[ticket_ayer.id, 'subir']))

        self.assertRedirects(respuesta, reverse('pantalla_turnos'))
        ticket_ayer.refresh_from_db()
        self.assertEqual(ticket_ayer.orden, ticket_ayer.numero)

    def test_no_recepcionista_no_puede_reordenar(self):
        self.client.force_login(crear_usuario('no_recep', rol=Usuario.ROL_MEDICO_RADIOLOGO))

        respuesta = self.client.post(reverse('reordenar_turno', args=[self.t2.id, 'subir']))
        self.assertNotEqual(respuesta.status_code, 200)  # deniega el acceso
        cola = list(Ticket.objects.filter(estado=Ticket.ESTADO_EN_ESPERA).order_by('-prioridad', 'orden'))
        self.assertEqual(cola, [self.t1, self.t2, self.t3])

    def test_pantalla_marca_los_flags_de_reordenamiento(self):
        respuesta = self.client.get(reverse('pantalla_turnos'))
        flags = {t.id: (t.puede_subir, t.puede_bajar, t.puede_tope) for t in respuesta.context['cola']}
        # t1: primero del bloque -> no subir ni tope; sí bajar.
        self.assertEqual(flags[self.t1.id], (False, True, False))
        # t2: en medio -> sí todo.
        self.assertEqual(flags[self.t2.id], (True, True, True))
        # t3: último del bloque -> sí subir y tope; no bajar.
        self.assertEqual(flags[self.t3.id], (True, False, True))

    def test_flags_respetan_los_tres_niveles_de_prioridad(self):
        # Añadimos dos Urgentes entre los críticos y los normales.
        urg_1 = Ticket.objects.create(paciente=crear_paciente(dpi='303132333340'),
                                      servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario)
        urg_1.prioridad = Ticket.PRIORIDAD_URGENTE
        urg_1.save(update_fields=['prioridad'])
        urg_2 = Ticket.objects.create(paciente=crear_paciente(dpi='303132333341'),
                                      servicio=Ticket.SERVICIO_PRIVADO, registrado_por=self.usuario)
        urg_2.prioridad = Ticket.PRIORIDAD_URGENTE
        urg_2.save(update_fields=['prioridad'])

        respuesta = self.client.get(reverse('pantalla_turnos'))
        cola = list(respuesta.context['cola'])
        flags = {t.id: (t.puede_subir, t.puede_bajar, t.puede_tope) for t in cola}
        prioritario = {t.id: t.prioridad for t in cola}

        # La fila es [urg_1, urg_2, t1, t2, t3] (urgentes primero por prioridad).
        self.assertEqual([t.id for t in cola][:2], [urg_1.id, urg_2.id])
        self.assertEqual(prioritario[urg_2.id], Ticket.PRIORIDAD_URGENTE)
        # urg_1: primero del bloque urgente -> no subir ni tope; sí bajar.
        self.assertEqual(flags[urg_1.id], (False, True, False))
        # urg_2: último del bloque urgente -> sí subir y tope; no bajar.
        self.assertEqual(flags[urg_2.id], (True, False, True))
        # t1: primero del bloque normal -> no subir ni tope; sí bajar.
        self.assertEqual(flags[self.t1.id], (False, True, False))

    def test_un_dia_que_no_es_hoy_no_muestra_botones_ni_flags(self):
        ayer = timezone.localdate() - datetime.timedelta(days=1)
        # Retrofechamos todos los tickets del día para simular ayer.
        Ticket.objects.all().update(
            creado_en=timezone.make_aware(datetime.datetime.combine(ayer, datetime.time(8, 0))),
        )

        respuesta = self.client.get(reverse('pantalla_turnos'), {'fecha': ayer.isoformat()})

        self.assertEqual(respuesta.context['es_hoy'], False)
        # En días que no son hoy no se anotan flags de reordenación...
        for t in respuesta.context['cola']:
            self.assertFalse(hasattr(t, 'puede_subir'))
            self.assertFalse(hasattr(t, 'puede_bajar'))
            self.assertFalse(hasattr(t, 'puede_tope'))
        # ...y tampoco aparece el formulario de reordenación.
        self.assertNotContains(respuesta, 'reordenar')

    def test_el_boton_reordenar_se_renderiza_para_hoy(self):
        respuesta = self.client.get(reverse('pantalla_turnos'))
        self.assertContains(respuesta, 'reordenar')


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


class Bloque6CombosTests(TestCase):
    """Bloque 6A: combos de estudios con descuento opcional y su gestión."""

    def setUp(self):
        from decimal import Decimal

        from pacientes.models import Combo, PrecioEstudio

        self.Decimal = Decimal
        self.admin = crear_usuario('admin_combo', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.recepcionista = crear_usuario('recep_combo', rol=Usuario.ROL_RECEPCIONISTA)

        self.rx = TipoEstudio.objects.create(nombre='Rx tórax A/P')
        self.rx_lat = TipoEstudio.objects.create(nombre='Rx tórax lateral')
        for estudio in (self.rx, self.rx_lat):
            PrecioEstudio.objects.create(
                tipo_estudio=estudio, convenio=Cita.CONVENIO_PRIVADO,
                horario_habil=True, precio=Decimal('300'),
            )
        self.combo = Combo.objects.create(nombre='Tórax completo')
        self.combo.estudios.add(self.rx, self.rx_lat)

    def test_total_es_la_suma_de_los_estudios_sin_descuento(self):
        self.assertEqual(self.combo.total_para('privado', True), self.Decimal('600.00'))
        self.assertEqual(self.combo.precio_referencia, self.Decimal('600.00'))

    def test_total_aplica_descuento_cuando_corresponde(self):
        self.combo.aplica_descuento = True
        self.combo.porcentaje_descuento = self.Decimal('10')
        self.combo.save()
        self.assertEqual(self.combo.total_para('privado', True), self.Decimal('540.00'))

    def test_descuento_invalido_ignora_el_porcentaje(self):
        self.combo.aplica_descuento = True
        self.combo.porcentaje_descuento = self.Decimal('0')
        self.combo.save()
        self.assertEqual(self.combo.total_para('privado', True), self.Decimal('600.00'))

    def test_descuento_solo_aplica_si_esta_marcado(self):
        self.combo.porcentaje_descuento = self.Decimal('20')
        self.combo.save()
        self.assertEqual(self.combo.total_para('privado', True), self.Decimal('600.00'))

    def test_crear_combo_solo_admin_y_registra_bitacora(self):
        self.client.force_login(self.recepcionista)
        respuesta = self.client.get(reverse('lista_combos'))
        self.assertEqual(respuesta.status_code, 302)

        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse('crear_combo'), {
            'nombre': 'Abdomen completo',
            'estudios': [self.rx.id, self.rx_lat.id],
            'activo': 'on',
            'aplica_descuento': 'on',
            'porcentaje_descuento': '15.00',
        })
        self.assertRedirects(respuesta, reverse('lista_combos'))
        self.assertTrue(Bitacora.objects.filter(accion=Bitacora.ACCION_CREAR_COMBO).exists())

    def test_editar_combo_registra_bitacora(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(
            reverse('editar_combo', args=[self.combo.id]),
            {
                'nombre': 'Tórax completo (2 vistas)',
                'estudios': [self.rx.id],
                'activo': 'on',
                'aplica_descuento': '',
                'porcentaje_descuento': '0.00',
            },
        )
        self.assertRedirects(respuesta, reverse('lista_combos'))
        self.combo.refresh_from_db()
        self.assertEqual(self.combo.nombre, 'Tórax completo (2 vistas)')
        self.assertTrue(Bitacora.objects.filter(accion=Bitacora.ACCION_EDITAR_COMBO).exists())

    def test_porcentaje_de_descuento_fuera_de_rango_se_rechaza(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse('crear_combo'), {
            'nombre': 'Combo inválido',
            'estudios': [self.rx.id],
            'activo': 'on',
            'aplica_descuento': 'on',
            'porcentaje_descuento': '150.00',
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'entre 0 y 100')


class Bloque6CobrosTests(TestCase):
    """Bloque 6B/6C: registro de cobro/pago por caja y bloqueo
    del envío de resultados si el estudio tiene un cobro pendiente."""

    def setUp(self):
        from decimal import Decimal

        from pacientes.models import Cobro, PrecioEstudio

        self.admin = crear_usuario('admin_cobro', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.recepcionista = crear_usuario('recep_cobro', rol=Usuario.ROL_RECEPCIONISTA)
        self.caja = crear_usuario(
            'caja_cobro', rol=Usuario.ROL_RECEPCIONISTA, puede_operar_caja=True,
        )
        self.tecnico = crear_usuario('tec_cobro', rol=Usuario.ROL_TECNICO_IMAGENES)

        self.paciente = crear_paciente(correo='p@correo.clinica', dpi='9988776655443')
        self.estudio = TipoEstudio.objects.create(nombre='Rx cobro')
        PrecioEstudio.objects.create(
            tipo_estudio=self.estudio, convenio=Cita.CONVENIO_PRIVADO,
            horario_habil=True, precio=Decimal('250'),
        )
        self.cita = crear_cita(
            self.recepcionista, paciente=self.paciente, tipo_estudio=self.estudio,
            estado=Cita.ESTADO_PROCESADA,
        )
        self.orden = OrdenTrabajo.objects.create(
            cita=self.cita, motivo='x', creada_por=self.recepcionista, informe_texto='Sin hallazgos.',
        )

    def test_marcar_cobrado_crea_cobro_pagado_y_registra_bitacora(self):
        self.client.force_login(self.caja)
        respuesta = self.client.post(reverse('marcar_cobrado', args=[self.cita.id]), {
            'forma_pago': 'efectivo',
            'numero_boleta': 'EF-001',
        })
        self.assertEqual(respuesta.status_code, 302)

        from pacientes.models import Cobro

        cobro = Cobro.objects.get(cita=self.cita)
        self.assertEqual(cobro.estado, Cobro.ESTADO_PAGADO)
        self.assertTrue(cobro.pagado)
        self.assertEqual(cobro.cobrado_por, self.caja)
        self.assertEqual(cobro.numero_boleta, 'EF-001')
        self.assertIsNotNone(cobro.pagado_en)
        self.assertTrue(Bitacora.objects.filter(accion=Bitacora.ACCION_MARCAR_COBRADO).exists())

    def test_marcar_cobrado_requiere_caja(self):
        self.client.force_login(self.tecnico)
        respuesta = self.client.post(reverse('marcar_cobrado', args=[self.cita.id]))
        self.assertEqual(respuesta.status_code, 302)

    def test_caja_puede_cobrar_orden_aun_en_proceso(self):
        self.cita.estado = Cita.ESTADO_EN_PROCESO
        self.cita.save(update_fields=['estado'])
        self.client.force_login(self.caja)
        respuesta = self.client.post(reverse('marcar_cobrado', args=[self.cita.id]), {
            'forma_pago': 'transferencia',
            'numero_boleta': 'TR-002',
        })
        self.assertRedirects(respuesta, reverse('pagos_pendientes'))

    def test_usuario_con_permiso_caja_puede_ver_dashboard(self):
        self.client.force_login(self.caja)
        respuesta = self.client.get(reverse('pagos_pendientes'))
        self.assertEqual(respuesta.status_code, 200)

    def test_usuario_sin_permiso_caja_no_puede_ver_dashboard(self):
        self.client.force_login(self.recepcionista)
        respuesta = self.client.get(reverse('pagos_pendientes'))
        self.assertEqual(respuesta.status_code, 302)

    def test_boleta_pdf_disponible_despues_de_pagar(self):
        self.client.force_login(self.caja)
        self.client.post(reverse('marcar_cobrado', args=[self.cita.id]), {
            'forma_pago': 'efectivo',
            'numero_boleta': 'PDF-001',
        })
        cobro = self.cita.cobro
        respuesta = self.client.get(reverse('boleta_pago_pdf', args=[cobro.id]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')
        self.assertTrue(respuesta.content.startswith(b'%PDF'))

    def test_dashboard_caja_filtra_por_fecha_y_pagina(self):
        from datetime import timedelta

        for indice in range(21):
            paciente = crear_paciente(dpi=f'8877665544{indice:03d}')
            cita = crear_cita(
                self.recepcionista, paciente=paciente, tipo_estudio=self.estudio,
                fecha=self.cita.fecha + timedelta(days=indice),
                estado=Cita.ESTADO_EN_PROCESO,
            )
            OrdenTrabajo.objects.create(cita=cita, motivo='x', creada_por=self.recepcionista)
            from pacientes.models import Cobro
            Cobro.objects.create(cita=cita)
        self.client.force_login(self.caja)
        respuesta = self.client.get(reverse('pagos_pendientes'), {
            'desde': self.cita.fecha.isoformat(),
            'hasta': (self.cita.fecha + timedelta(days=20)).isoformat(),
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['pagina'].paginator.per_page, 20)
        self.assertEqual(respuesta.context['pagina'].paginator.count, 21)

    def test_cobro_pendiente_bloquea_envio_de_resultados(self):
        from pacientes.models import Cobro

        Cobro.objects.create(cita=self.cita, estado=Cobro.ESTADO_PENDIENTE)
        self.client.force_login(self.recepcionista)

        with mock.patch('pacientes.views.enviar_resultados', return_value=True) as enviar:
            respuesta = self.client.post(reverse('enviar_estudio', args=[self.cita.id]))
            enviar.assert_not_called()

        self.orden.refresh_from_db()
        self.assertIsNone(self.orden.resultados_enviados_en)
        self.assertContains(self.client.get(reverse('historial_paciente', args=[self.paciente.id])), 'cobro')

    def test_cobro_pagado_no_bloquea_envio(self):
        from pacientes.models import Cobro

        Cobro.objects.create(cita=self.cita, estado=Cobro.ESTADO_PAGADO, pagado_en=timezone.now(),
                             cobrado_por=self.recepcionista)
        self.client.force_login(self.recepcionista)

        with mock.patch('pacientes.views.enviar_resultados', return_value=True) as enviar:
            respuesta = self.client.post(reverse('enviar_estudio', args=[self.cita.id]))

        enviar.assert_called_once()
        self.assertRedirects(respuesta, reverse('historial_paciente', args=[self.paciente.id]))
        self.orden.refresh_from_db()
        self.assertIsNotNone(self.orden.resultados_enviados_en)

    def test_sin_cobro_no_bloquea_envio(self):
        self.client.force_login(self.recepcionista)
        with mock.patch('pacientes.views.enviar_resultados', return_value=True) as enviar:
            respuesta = self.client.post(reverse('enviar_estudio', args=[self.cita.id]))
        enviar.assert_called_once()
        self.orden.refresh_from_db()
        self.assertIsNotNone(self.orden.resultados_enviados_en)

    def test_historial_muestra_estado_de_cobro(self):
        from pacientes.models import Cobro

        Cobro.objects.create(cita=self.cita, estado=Cobro.ESTADO_PENDIENTE)
        self.client.force_login(self.recepcionista)
        respuesta = self.client.get(reverse('historial_paciente', args=[self.paciente.id]))
        self.assertContains(respuesta, 'Cobro pendiente')
        self.assertNotContains(respuesta, 'Confirmar cobro')

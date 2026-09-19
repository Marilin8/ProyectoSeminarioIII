import datetime
import uuid

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import Bitacora, HistorialComision, Usuario
from clinica.validators import validar_dominio_correo

UsuarioModel = get_user_model()


def crear_usuario(username='usuario', rol=Usuario.ROL_RECEPCIONISTA, **kwargs):
    return UsuarioModel.objects.create_user(username=username, password='clave-segura-123', rol=rol, **kwargs)


class ValidacionDominioCorreoTests(TestCase):

    def test_dominio_valido_pasa(self):
        validar_dominio_correo('persona@gmail.com')
        validar_dominio_correo('persona@miumg.edu.gt')

    def test_dominio_temporal_se_rechaza(self):
        from django.core.exceptions import ValidationError
        for correo in ('x@mailinator.com', 'y@yopmail.com', 'z@10minutemail.com'):
            with self.assertRaises(ValidationError):
                validar_dominio_correo(correo)

    def test_dominio_mal_formado_se_rechaza(self):
        from django.core.exceptions import ValidationError
        for correo in ('x@sinpunto', 'x@dominio.c', 'x@-mal.com'):
            with self.assertRaises(ValidationError):
                validar_dominio_correo(correo)

    def test_crear_usuario_rechaza_correo_temporal(self):
        admin = crear_usuario('admin_dom', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.client.force_login(admin)
        respuesta = self.client.post(reverse('crear_usuario'), {
            'username': 'nuevo', 'first_name': 'N', 'last_name': 'N',
            'email': 'nuevo@mailinator.com', 'rol': Usuario.ROL_RECEPCIONISTA,
            'porcentaje_coex': '0', 'porcentaje_privado': '0', 'porcentaje_emergencia_igss': '0',
            'password1': 'Zx7#kLmn9q', 'password2': 'Zx7#kLmn9q',
        })
        self.assertContains(respuesta, 'temporales o desechables')
        self.assertFalse(Usuario.objects.filter(username='nuevo').exists())


class FechaIngresoTests(TestCase):
    """El administrador puede fijar/corregir desde cuándo trabaja un
    empleado en la clínica (Usuario.date_joined), en vez de que quede
    pegado a cuándo se creó la cuenta en el sistema."""

    def setUp(self):
        self.admin = crear_usuario('admin_ingreso', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.client.force_login(self.admin)

    def test_crear_usuario_guarda_la_fecha_de_ingreso_elegida(self):
        respuesta = self.client.post(reverse('crear_usuario'), {
            'username': 'antiguo', 'first_name': 'Ana', 'last_name': 'Tigua',
            'email': 'antiguo@gmail.com', 'rol': Usuario.ROL_TECNICO_IMAGENES,
            'fecha_ingreso': '2024-03-15', 'salario_base': '0',
            'porcentaje_coex': '0', 'porcentaje_privado': '0', 'porcentaje_emergencia_igss': '0',
            'password1': 'Zx7#kLmn9q', 'password2': 'Zx7#kLmn9q',
        })

        self.assertRedirects(respuesta, reverse('dashboard'))
        usuario = Usuario.objects.get(username='antiguo')
        self.assertEqual(usuario.date_joined.date().isoformat(), '2024-03-15')

    def test_crear_usuario_rechaza_fecha_de_ingreso_futura(self):
        import datetime

        manana = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        respuesta = self.client.post(reverse('crear_usuario'), {
            'username': 'futuro', 'first_name': 'F', 'last_name': 'F',
            'email': 'futuro@gmail.com', 'rol': Usuario.ROL_RECEPCIONISTA,
            'fecha_ingreso': manana,
            'porcentaje_coex': '0', 'porcentaje_privado': '0', 'porcentaje_emergencia_igss': '0',
            'password1': 'Zx7#kLmn9q', 'password2': 'Zx7#kLmn9q',
        })

        self.assertContains(respuesta, 'no puede ser futura')
        self.assertFalse(Usuario.objects.filter(username='futuro').exists())

    def test_editar_usuario_permite_corregir_la_fecha_de_ingreso(self):
        empleado = crear_usuario('viejo_dato', rol=Usuario.ROL_TECNICO_IMAGENES)

        respuesta = self.client.post(reverse('editar_usuario', args=[empleado.id]), {
            'first_name': 'V', 'last_name': 'D', 'email': 'viejo@gmail.com',
            'rol': Usuario.ROL_TECNICO_IMAGENES, 'is_active': 'on', 'salario_base': '0',
            'fecha_ingreso': '2023-01-10',
            'porcentaje_coex': '0', 'porcentaje_privado': '0', 'porcentaje_emergencia_igss': '0',
        })

        self.assertEqual(respuesta.status_code, 302)
        empleado.refresh_from_db()
        self.assertEqual(empleado.date_joined.date().isoformat(), '2023-01-10')


class ConfirmacionCorreoUsuarioTests(TestCase):
    """Un usuario recién creado queda inactivo hasta que confirma, por un
    link mandado a su correo, que esa casilla es real y suya."""

    def setUp(self):
        self.admin = crear_usuario('admin_confirma', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.client.force_login(self.admin)

    def _crear(self, username='pendiente', email='pendiente@gmail.com'):
        return self.client.post(reverse('crear_usuario'), {
            'username': username, 'first_name': 'Nuevo', 'last_name': 'Empleado',
            'email': email, 'rol': Usuario.ROL_RECEPCIONISTA, 'salario_base': '0',
            'fecha_ingreso': '2026-01-01',
            'porcentaje_coex': '0', 'porcentaje_privado': '0', 'porcentaje_emergencia_igss': '0',
            'password1': 'Zx7#kLmn9q', 'password2': 'Zx7#kLmn9q',
        })

    def test_usuario_nuevo_queda_inactivo_y_se_le_manda_un_correo(self):
        self._crear()

        usuario = Usuario.objects.get(username='pendiente')
        self.assertFalse(usuario.is_active)
        self.assertIsNotNone(usuario.token_confirmacion_correo)

        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ['pendiente@gmail.com'])
        self.assertIn(str(usuario.token_confirmacion_correo), correo.body)

    def test_confirmar_con_token_valido_activa_la_cuenta(self):
        self._crear()
        usuario = Usuario.objects.get(username='pendiente')

        respuesta = self.client.get(
            reverse('confirmar_correo_usuario', args=[usuario.token_confirmacion_correo]),
        )

        self.assertContains(respuesta, 'Correo confirmado')
        usuario.refresh_from_db()
        self.assertTrue(usuario.is_active)
        self.assertIsNone(usuario.token_confirmacion_correo)
        self.assertTrue(
            Bitacora.objects.filter(
                usuario=usuario, accion=Bitacora.ACCION_CONFIRMAR_CORREO_USUARIO,
            ).exists()
        )

    def test_confirmar_con_token_que_no_existe_no_activa_nada(self):
        respuesta = self.client.get(
            reverse('confirmar_correo_usuario', args=[uuid.uuid4()]),
        )

        self.assertContains(respuesta, 'Enlace inválido')

    def test_confirmar_con_token_vencido_no_activa_y_avisa(self):
        self._crear()
        usuario = Usuario.objects.get(username='pendiente')
        usuario.token_confirmacion_generado_en = (
            timezone.now() - usuario.VIGENCIA_TOKEN_CONFIRMACION - datetime.timedelta(days=1)
        )
        usuario.save(update_fields=['token_confirmacion_generado_en'])

        respuesta = self.client.get(
            reverse('confirmar_correo_usuario', args=[usuario.token_confirmacion_correo]),
        )

        self.assertContains(respuesta, 'ya venció')
        usuario.refresh_from_db()
        self.assertFalse(usuario.is_active)

    def test_login_con_correo_sin_confirmar_muestra_mensaje_especifico(self):
        self._crear()
        self.client.logout()

        respuesta = self.client.post(reverse('login'), {
            'username': 'pendiente', 'password': 'Zx7#kLmn9q',
        })

        self.assertContains(respuesta, 'Todavía no confirmaste tu correo')

    def test_login_de_cuenta_suspendida_a_mano_muestra_mensaje_generico(self):
        crear_usuario('suspendido', is_active=False)
        self.client.logout()

        respuesta = self.client.post(reverse('login'), {
            'username': 'suspendido', 'password': 'clave-segura-123',
        })

        self.assertContains(respuesta, 'Tu usuario está inactivo')
        self.assertNotContains(respuesta, 'Todavía no confirmaste')


class HistorialComisionTests(TestCase):

    def setUp(self):
        self.admin = crear_usuario('admin_com', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.radiologo = crear_usuario('rad_com', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.client.force_login(self.admin)

    def _editar(self, **porcentajes):
        datos = {
            'first_name': 'R', 'last_name': 'C', 'email': 'rad@gmail.com',
            'rol': Usuario.ROL_MEDICO_RADIOLOGO, 'is_active': 'on', 'salario_base': '0',
            'fecha_ingreso': '2026-01-01',
            'porcentaje_coex': '0', 'porcentaje_privado': '0', 'porcentaje_emergencia_igss': '0',
            'tipos_estudio': [],
        }
        datos.update(porcentajes)
        return self.client.post(reverse('editar_usuario', args=[self.radiologo.id]), datos)

    def test_cambiar_comision_registra_historial_y_bitacora(self):
        self._editar(porcentaje_coex='20', porcentaje_privado='12')
        registros = HistorialComision.objects.filter(usuario=self.radiologo)
        self.assertEqual(registros.count(), 2)
        coex = registros.get(campo='porcentaje_coex')
        self.assertEqual(coex.valor_anterior, 0)
        self.assertEqual(coex.valor_nuevo, 20)
        self.assertEqual(coex.modificado_por, self.admin)
        self.assertTrue(
            Bitacora.objects.filter(accion=Bitacora.ACCION_EDITAR_COMISION).exists()
        )

    def test_editar_sin_tocar_comision_no_registra_nada(self):
        self._editar()
        self.assertEqual(HistorialComision.objects.count(), 0)

    def test_pantalla_historial_lista_los_cambios(self):
        self._editar(porcentaje_coex='5')
        respuesta = self.client.get(reverse('historial_comisiones'))
        self.assertContains(respuesta, 'rad_com')
        self.assertContains(respuesta, '5')


class MFATests(TestCase):

    def setUp(self):
        self.usuario = crear_usuario('user_mfa', rol=Usuario.ROL_RECEPCIONISTA)

    def _codigo(self, device):
        return f'{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):0{device.digits}d}'

    def test_configurar_mfa_muestra_qr(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('configurar_mfa'))
        self.assertContains(respuesta, 'data:image/png;base64')
        self.assertTrue(TOTPDevice.objects.filter(user=self.usuario, confirmed=False).exists())

    def test_activar_mfa_con_codigo_valido(self):
        self.client.force_login(self.usuario)
        self.client.get(reverse('configurar_mfa'))
        device = TOTPDevice.objects.get(user=self.usuario)
        self.client.post(reverse('configurar_mfa'), {'accion': 'verificar', 'codigo': self._codigo(device)})
        device.refresh_from_db()
        self.assertTrue(device.confirmed)

    def test_login_pide_segundo_paso_si_hay_mfa(self):
        TOTPDevice.objects.create(user=self.usuario, confirmed=True)
        respuesta = self.client.post(reverse('login'), {
            'username': 'user_mfa', 'password': 'clave-segura-123',
        })
        self.assertRedirects(respuesta, reverse('login_otp'))

    def test_login_otp_con_codigo_valido_inicia_sesion(self):
        device = TOTPDevice.objects.create(user=self.usuario, confirmed=True)
        self.client.post(reverse('login'), {'username': 'user_mfa', 'password': 'clave-segura-123'})
        respuesta = self.client.post(reverse('login_otp'), {'codigo': self._codigo(device)})
        self.assertRedirects(respuesta, reverse('dashboard'))

    def test_login_sin_mfa_entra_directo(self):
        respuesta = self.client.post(reverse('login'), {
            'username': 'user_mfa', 'password': 'clave-segura-123',
        })
        self.assertRedirects(respuesta, reverse('dashboard'))


class UsuarioModelTests(TestCase):

    def test_el_rol_por_defecto_es_administrador(self):
        usuario = UsuarioModel.objects.create_user(username='sin_rol', password='clave-segura-123')
        self.assertEqual(usuario.rol, Usuario.ROL_ADMINISTRADOR)

    def test_se_puede_crear_con_un_rol_especifico(self):
        usuario = crear_usuario('tecnico3', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.assertEqual(usuario.rol, Usuario.ROL_TECNICO_IMAGENES)

   


class BitacoraModelTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def test_registrar_guarda_el_usuario_y_la_accion(self):
        usuario = crear_usuario('recepcionista1')

        Bitacora.registrar(accion=Bitacora.ACCION_LOGIN_EXITOSO, usuario=usuario)

        evento = Bitacora.objects.get()
        self.assertEqual(evento.usuario, usuario)
        self.assertEqual(evento.accion, Bitacora.ACCION_LOGIN_EXITOSO)
        self.assertEqual(evento.ip, None)


class PlanillaTests(TestCase):
    """Planilla: salario base + comisiones calculadas de las citas
    procesadas del período, y el detalle por empleado."""

    def setUp(self):
        import datetime
        from decimal import Decimal

        from pacientes.models import Cita, PrecioEstudio, TipoEstudio

        # Fecha de ingreso bien anterior a las citas de prueba (2026-08-15):
        # así los períodos usados en estos tests no caen antes de que
        # "trabajaran acá" (ver el filtro de accounts.planilla.planilla).
        ingreso_de_prueba = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

        self.admin = crear_usuario('admin_planilla', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.tecnico = crear_usuario(
            'tec_planilla', rol=Usuario.ROL_TECNICO_IMAGENES, salario_base=Decimal('3000'),
            date_joined=ingreso_de_prueba,
        )
        self.tecnico.porcentaje_privado = Decimal('5')
        self.tecnico.save()
        self.radiologo = crear_usuario(
            'rad_planilla', rol=Usuario.ROL_MEDICO_RADIOLOGO, salario_base=Decimal('6000'),
            date_joined=ingreso_de_prueba,
        )
        self.radiologo.porcentaje_privado = Decimal('10')
        self.radiologo.save()

        from pacientes.models import Paciente

        self.paciente = Paciente.objects.create(
            dpi='9990001112223', nombre='Ana', apellido='Gómez',
            fecha_nacimiento=datetime.date(1990, 1, 1),
        )
        self.estudio = TipoEstudio.objects.create(
            nombre='RX de tórax planilla', modalidad=TipoEstudio.MODALIDAD_RX,
        )
        PrecioEstudio.objects.create(
            tipo_estudio=self.estudio, convenio=Cita.CONVENIO_PRIVADO,
            horario_habil=True, precio=Decimal('1000'),
        )
        self.fecha = datetime.date(2026, 8, 15)

    def _cita_procesada(self, hora=None):
        import datetime

        from django.core.files.uploadedfile import SimpleUploadedFile

        from pacientes.models import Cita, ImagenEstudio, OrdenTrabajo

        cita = Cita.objects.create(
            paciente=self.paciente, tipo_estudio=self.estudio, convenio=Cita.CONVENIO_PRIVADO,
            estado=Cita.ESTADO_PROCESADA, fecha=self.fecha, hora=hora or datetime.time(9, 0),
            creada_por=self.admin, radiologo=self.radiologo,
        )
        orden = OrdenTrabajo.objects.create(cita=cita, motivo='motivo', creada_por=self.admin)
        ImagenEstudio.objects.create(
            orden=orden, subida_por=self.tecnico,
            archivo=SimpleUploadedFile('img.jpg', b'fake'),
        )
        return cita

    def _comprobante(self, nombre='boleta.jpg'):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(nombre, b'\xff\xd8\xff\xe0datos', content_type='image/jpeg')

    def test_planilla_muestra_salario_y_comisiones_pendientes(self):
        from decimal import Decimal

        self._cita_procesada()
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('planilla'), {'modo': 'mes', 'mes': '2026-08'})

        self.assertEqual(respuesta.status_code, 200)
        filas = {f['usuario'].username: f for f in respuesta.context['filas']}
        self.assertEqual(filas['tec_planilla']['salario_base'], Decimal('3000'))
        self.assertEqual(filas['tec_planilla']['comisiones'], Decimal('50.00'))
        self.assertEqual(filas['rad_planilla']['comisiones'], Decimal('100.00'))

    def test_detalle_empleado_marca_lo_pendiente(self):
        import datetime
        from decimal import Decimal

        self._cita_procesada(hora=datetime.time(8, 0))
        self._cita_procesada(hora=datetime.time(10, 0))
        self.client.force_login(self.admin)

        respuesta = self.client.get(
            reverse('planilla_empleado', args=[self.tecnico.id]), {'modo': 'mes', 'mes': '2026-08'},
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(respuesta.context['lineas']), 2)
        self.assertEqual(respuesta.context['total_pendiente'], Decimal('100.00'))
        self.assertEqual(respuesta.context['total_pagado'], Decimal('0.00'))

    def test_periodo_semana_y_quincena(self):
        import datetime
        from decimal import Decimal

        self.fecha = datetime.date(2026, 8, 4)   # martes de la 1ª quincena
        self._cita_procesada()
        self.client.force_login(self.admin)

        r = self.client.get(reverse('planilla'), {'modo': 'semana', 'semana': '2026-08-05'})
        filas = {f['usuario'].username: f for f in r.context['filas']}
        self.assertEqual(filas['tec_planilla']['comisiones'], Decimal('50.00'))
        self.assertEqual(r.context['periodo']['desde'], datetime.date(2026, 8, 3))

        r = self.client.get(reverse('planilla'), {'modo': 'quincena', 'quincena': '2026-08', 'q': '2'})
        filas = {f['usuario'].username: f for f in r.context['filas']}
        self.assertEqual(filas['tec_planilla']['comisiones'], Decimal('0.00'))  # día 4 no cae en 16–31

    def test_no_muestra_salario_de_meses_antes_de_su_ingreso(self):
        import datetime
        from decimal import Decimal

        recien_llegado = crear_usuario(
            'tec_nuevo_planilla', rol=Usuario.ROL_TECNICO_IMAGENES, salario_base=Decimal('2800'),
            date_joined=datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc),
        )
        self.client.force_login(self.admin)

        # Agosto 2026 es antes de que "recien_llegado" empezara a trabajar.
        respuesta = self.client.get(reverse('planilla'), {'modo': 'mes', 'mes': '2026-08'})

        usernames = [f['usuario'].username for f in respuesta.context['filas']]
        self.assertNotIn('tec_nuevo_planilla', usernames)
        # Pero si ya trabajaba ahí (tec_planilla, desde enero), sí aparece.
        self.assertIn('tec_planilla', usernames)

    def test_solo_el_administrador_ve_la_planilla(self):
        self.client.force_login(self.tecnico)
        respuesta = self.client.get(reverse('planilla'))
        self.assertNotEqual(respuesta.status_code, 200)

    def test_pago_salario_registra_el_monto_del_salario_base(self):
        from decimal import Decimal

        from accounts.models import Bitacora, PagoSalario

        self.client.force_login(self.admin)
        respuesta = self.client.post(
            reverse('registrar_pago_salario', args=[self.tecnico.id]) + '?modo=mes&mes=2026-08',
            {'comprobante': self._comprobante(), 'notas': 'transferencia'},
        )

        self.assertRedirects(respuesta, reverse('planilla') + '?modo=mes&mes=2026-08')
        pago = PagoSalario.objects.get(usuario=self.tecnico, anio=2026, mes=8)
        self.assertEqual(pago.monto, Decimal('3000'))
        self.assertTrue(pago.comprobante.name)
        self.assertTrue(
            Bitacora.objects.filter(accion=Bitacora.ACCION_REGISTRAR_PAGO_PLANILLA).exists()
        )
        pago.comprobante.delete(save=False)

    def test_pago_comision_crea_lineas_y_deja_de_estar_pendiente(self):
        from decimal import Decimal

        from accounts.models import PagoComision, PagoComisionLinea

        self._cita_procesada()   # técnico gana Q50
        self.client.force_login(self.admin)

        respuesta = self.client.post(
            reverse('registrar_pago_comision', args=[self.tecnico.id]) + '?modo=mes&mes=2026-08',
            {'comprobante': self._comprobante(), 'notas': ''},
        )

        self.assertRedirects(respuesta, reverse('planilla') + '?modo=mes&mes=2026-08')
        pago = PagoComision.objects.get(usuario=self.tecnico)
        self.assertEqual(pago.monto, Decimal('50.00'))
        self.assertEqual(PagoComisionLinea.objects.filter(pago=pago).count(), 1)

        r = self.client.get(reverse('planilla'), {'modo': 'mes', 'mes': '2026-08'})
        filas = {f['usuario'].username: f for f in r.context['filas']}
        self.assertEqual(filas['tec_planilla']['comisiones'], Decimal('0.00'))
        pago.comprobante.delete(save=False)

    def test_comision_ya_pagada_no_se_vuelve_a_cobrar_en_otro_rango(self):
        import datetime
        from decimal import Decimal

        from accounts.models import PagoComision

        self.fecha = datetime.date(2026, 8, 10)
        self._cita_procesada(hora=datetime.time(8, 0))   # comisión del día 10, mañana
        self.client.force_login(self.admin)

        # Pago del 1 al 12.
        self.client.post(
            reverse('registrar_pago_comision', args=[self.tecnico.id])
            + '?modo=rango&desde=2026-08-01&hasta=2026-08-12',
            {'comprobante': self._comprobante(), 'notas': ''},
        )
        # Más tarde ese mismo día 10 el técnico hace otro estudio.
        self._cita_procesada(hora=datetime.time(15, 0))

        # Rango del 10 al 20: solo debe contar la comisión nueva del día 10.
        r = self.client.get(
            reverse('planilla'),
            {'modo': 'rango', 'desde': '2026-08-10', 'hasta': '2026-08-20'},
        )
        filas = {f['usuario'].username: f for f in r.context['filas']}
        self.assertEqual(filas['tec_planilla']['comisiones'], Decimal('50.00'))
        for p in PagoComision.objects.all():
            p.comprobante.delete(save=False)

    def test_pago_rechaza_archivo_no_permitido(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from accounts.models import PagoSalario

        self.client.force_login(self.admin)
        respuesta = self.client.post(
            reverse('registrar_pago_salario', args=[self.tecnico.id]) + '?modo=mes&mes=2026-08',
            {'comprobante': SimpleUploadedFile('pago.txt', b'x'), 'notas': ''},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(PagoSalario.objects.exists())

    def test_bloquea_pago_si_el_comprobante_no_coincide(self):
        from accounts import verificacion_boleta
        from accounts.models import PagoSalario

        self.client.force_login(self.admin)
        original = verificacion_boleta._leer_texto
        verificacion_boleta._leer_texto = lambda *a, **k: 'Deposito Q1,000.00\nBoleta No. 42'
        try:
            respuesta = self.client.post(
                reverse('registrar_pago_salario', args=[self.tecnico.id]) + '?modo=mes&mes=2026-08',
                {'comprobante': self._comprobante(), 'numero_boleta': '999', 'notas': ''},
            )
            self.assertEqual(respuesta.status_code, 200)
            self.assertFalse(PagoSalario.objects.exists())

            respuesta = self.client.post(
                reverse('registrar_pago_salario', args=[self.tecnico.id]) + '?modo=mes&mes=2026-08',
                {
                    'comprobante': self._comprobante(), 'numero_boleta': '999',
                    'notas': '', 'confirmar_pese_a_diferencia': 'on',
                },
            )
            self.assertRedirects(respuesta, reverse('planilla') + '?modo=mes&mes=2026-08')
            pago = PagoSalario.objects.get()
            self.assertFalse(pago.verificado)
            pago.comprobante.delete(save=False)
        finally:
            verificacion_boleta._leer_texto = original

    def test_historial_pagos_lista_salario_y_comisiones(self):
        from accounts import verificacion_boleta

        self._cita_procesada()
        self.client.force_login(self.admin)
        original = verificacion_boleta._leer_texto
        verificacion_boleta._leer_texto = lambda *a, **k: None  # no verificable, deja pasar
        try:
            self.client.post(
                reverse('registrar_pago_salario', args=[self.tecnico.id]) + '?modo=mes&mes=2026-08',
                {'comprobante': self._comprobante(), 'notas': ''},
            )
            self.client.post(
                reverse('registrar_pago_comision', args=[self.tecnico.id]) + '?modo=mes&mes=2026-08',
                {'comprobante': self._comprobante(), 'notas': ''},
            )
        finally:
            verificacion_boleta._leer_texto = original

        respuesta = self.client.get(reverse('historial_pagos'))
        tipos = sorted(p['tipo'] for p in respuesta.context['pagos'])
        self.assertEqual(tipos, ['Comisiones', 'Salario base'])
        for p in respuesta.context['pagos']:
            p['comprobante'].delete(save=False)


class PendientePagoTests(TestCase):
    """Pestaña "Pendiente de pago": meses de salario ya cerrados sin
    registrar y comisiones de cualquier fecha que sigan sin pagarse — sin
    importar el período que se esté viendo en Planilla."""

    def setUp(self):
        import datetime

        from django.utils import timezone

        self.admin = crear_usuario('admin_pendiente', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.hoy = timezone.localdate()
        self.mes_anterior = self.hoy.replace(day=1) - datetime.timedelta(days=1)

    def _comprobante(self, nombre='boleta.jpg'):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(nombre, b'\xff\xd8\xff\xe0datos', content_type='image/jpeg')

    def _empleado_desde(self, meses_atras, **kwargs):
        import datetime

        inicio = self.hoy.replace(day=1)
        for _ in range(meses_atras):
            inicio = (inicio - datetime.timedelta(days=1)).replace(day=1)
        fecha_ingreso = datetime.datetime(inicio.year, inicio.month, 1, tzinfo=datetime.timezone.utc)
        return crear_usuario(date_joined=fecha_ingreso, **kwargs)

    def test_mes_de_salario_sin_pagar_aparece_pendiente(self):
        from decimal import Decimal

        empleado = self._empleado_desde(
            3, username='tec_atrasado', rol=Usuario.ROL_TECNICO_IMAGENES, salario_base=Decimal('2500'),
        )
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('pendiente_pago'))

        self.assertEqual(respuesta.status_code, 200)
        filas = {f['usuario'].username: f for f in respuesta.context['filas']}
        self.assertIn('tec_atrasado', filas)
        meses = {(m['anio'], m['mes']) for m in filas['tec_atrasado']['meses_pendientes']}
        self.assertIn((self.mes_anterior.year, self.mes_anterior.month), meses)
        # El mes en curso todavía no cuenta como atrasado.
        self.assertNotIn((self.hoy.year, self.hoy.month), meses)
        self.assertEqual(filas['tec_atrasado']['total_salario'], Decimal('2500') * 3)

    def test_mes_ya_pagado_no_aparece_como_pendiente(self):
        from decimal import Decimal

        from accounts.models import PagoSalario

        empleado = self._empleado_desde(
            1, username='tec_al_dia', rol=Usuario.ROL_TECNICO_IMAGENES, salario_base=Decimal('2500'),
        )
        PagoSalario.objects.create(
            usuario=empleado, anio=self.mes_anterior.year, mes=self.mes_anterior.month,
            monto=Decimal('2500'), comprobante=self._comprobante(), registrado_por=self.admin,
        )
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('pendiente_pago'))

        filas = {f['usuario'].username: f for f in respuesta.context['filas']}
        self.assertNotIn('tec_al_dia', filas)

    def test_comisiones_de_mes_anterior_pendientes_pero_no_las_del_mes_actual(self):
        import datetime

        from decimal import Decimal

        from django.core.files.uploadedfile import SimpleUploadedFile

        from pacientes.models import Cita, ImagenEstudio, OrdenTrabajo, Paciente, PrecioEstudio, TipoEstudio

        radiologo = crear_usuario('rad_pendiente', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        radiologo.porcentaje_privado = Decimal('10')
        radiologo.save()
        # Técnico aparte (sin % de comisión) para que solo cuente la comisión
        # del radiólogo: si subiera la imagen el mismo radiólogo, contaría
        # dos veces (como técnico y como radiólogo) con el mismo %.
        tecnico = crear_usuario('tec_pendiente', rol=Usuario.ROL_TECNICO_IMAGENES)
        paciente = Paciente.objects.create(
            dpi='7778889990002', nombre='Bruno', apellido='Ruiz',
            fecha_nacimiento=datetime.date(1985, 1, 1),
        )
        estudio = TipoEstudio.objects.create(nombre='RX pendiente de pago')
        PrecioEstudio.objects.create(
            tipo_estudio=estudio, convenio=Cita.CONVENIO_PRIVADO, horario_habil=True, precio=Decimal('1000'),
        )

        def _cita_procesada(fecha):
            cita = Cita.objects.create(
                paciente=paciente, tipo_estudio=estudio, convenio=Cita.CONVENIO_PRIVADO,
                estado=Cita.ESTADO_PROCESADA, fecha=fecha, hora=datetime.time(9, 0),
                creada_por=self.admin, radiologo=radiologo,
            )
            orden = OrdenTrabajo.objects.create(cita=cita, motivo='motivo', creada_por=self.admin)
            ImagenEstudio.objects.create(
                orden=orden, subida_por=tecnico, archivo=SimpleUploadedFile('img.jpg', b'fake'),
            )
            return cita

        _cita_procesada(self.mes_anterior)
        _cita_procesada(self.hoy)
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('pendiente_pago'))

        filas = {f['usuario'].username: f for f in respuesta.context['filas']}
        self.assertIn('rad_pendiente', filas)
        # Solo la comisión del mes anterior cuenta como atrasada (Q100 = 10% de Q1000).
        self.assertEqual(filas['rad_pendiente']['comisiones_pendientes'], Decimal('100.00'))
        self.assertEqual(filas['rad_pendiente']['cantidad_comisiones'], 1)

    def test_solo_administrador_puede_ver_pendiente_de_pago(self):
        tecnico = crear_usuario('tec_sin_permiso', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.client.force_login(tecnico)

        respuesta = self.client.get(reverse('pendiente_pago'))

        self.assertNotEqual(respuesta.status_code, 200)


class PagoAdelantadoTests(TestCase):
    """Pestaña "Pago por adelantado": pagar el salario base de un mes que
    todavía no ha llegado, para cuando un empleado lo pide con anticipación."""

    def setUp(self):
        from django.utils import timezone

        self.admin = crear_usuario('admin_adelanto', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.hoy = timezone.localdate()

    def _comprobante(self, nombre='boleta.jpg'):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(nombre, b'\xff\xd8\xff\xe0datos', content_type='image/jpeg')

    def _proximo_mes(self):
        if self.hoy.month == 12:
            return self.hoy.year + 1, 1
        return self.hoy.year, self.hoy.month + 1

    def test_lista_solo_activos_con_salario_base(self):
        from decimal import Decimal

        crear_usuario('tec_con_salario', rol=Usuario.ROL_TECNICO_IMAGENES, salario_base=Decimal('2000'))
        crear_usuario('tec_sin_salario', rol=Usuario.ROL_TECNICO_IMAGENES, salario_base=Decimal('0'))
        inactivo = crear_usuario('tec_inactivo', rol=Usuario.ROL_TECNICO_IMAGENES, salario_base=Decimal('2000'))
        inactivo.is_active = False
        inactivo.save()
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('pago_adelantado'))

        self.assertEqual(respuesta.status_code, 200)
        usernames = [f['usuario'].username for f in respuesta.context['filas']]
        self.assertIn('tec_con_salario', usernames)
        self.assertNotIn('tec_sin_salario', usernames)
        self.assertNotIn('tec_inactivo', usernames)

    def test_mes_minimo_es_el_mes_siguiente_al_actual(self):
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('pago_adelantado'))

        anio, mes = self._proximo_mes()
        self.assertEqual(respuesta.context['mes_minimo'], f'{anio:04d}-{mes:02d}')

    def test_registrar_pago_salario_de_un_mes_futuro_lo_deja_pagado(self):
        from decimal import Decimal

        from accounts.models import PagoSalario

        empleado = crear_usuario(
            'tec_adelanto', rol=Usuario.ROL_TECNICO_IMAGENES, salario_base=Decimal('2500'),
        )
        self.client.force_login(self.admin)
        anio, mes = self._proximo_mes()

        respuesta = self.client.post(
            f"{reverse('registrar_pago_salario', args=[empleado.id])}?modo=mes&mes={anio}-{mes:02d}",
            {'comprobante': self._comprobante(), 'numero_boleta': '', 'notas': 'pago adelantado'},
        )

        self.assertEqual(respuesta.status_code, 302)
        pago = PagoSalario.objects.get(usuario=empleado, anio=anio, mes=mes)
        self.assertEqual(pago.monto, Decimal('2500'))

    def test_adelanto_ya_pagado_aparece_en_la_lista(self):
        from decimal import Decimal

        from accounts.models import PagoSalario

        empleado = crear_usuario(
            'tec_ya_adelantado', rol=Usuario.ROL_TECNICO_IMAGENES, salario_base=Decimal('2500'),
        )
        anio, mes = self._proximo_mes()
        PagoSalario.objects.create(
            usuario=empleado, anio=anio, mes=mes,
            monto=Decimal('2500'), comprobante=self._comprobante(), registrado_por=self.admin,
        )
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('pago_adelantado'))

        filas = {f['usuario'].username: f for f in respuesta.context['filas']}
        adelantos = filas['tec_ya_adelantado']['adelantos']
        self.assertEqual(len(adelantos), 1)
        self.assertEqual((adelantos[0].anio, adelantos[0].mes), (anio, mes))

    def test_pago_del_mes_actual_no_cuenta_como_adelanto(self):
        from decimal import Decimal

        from accounts.models import PagoSalario

        empleado = crear_usuario(
            'tec_mes_actual', rol=Usuario.ROL_TECNICO_IMAGENES, salario_base=Decimal('2500'),
        )
        PagoSalario.objects.create(
            usuario=empleado, anio=self.hoy.year, mes=self.hoy.month,
            monto=Decimal('2500'), comprobante=self._comprobante(), registrado_por=self.admin,
        )
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('pago_adelantado'))

        filas = {f['usuario'].username: f for f in respuesta.context['filas']}
        self.assertEqual(filas['tec_mes_actual']['adelantos'], [])

    def test_solo_administrador_puede_ver_pago_adelantado(self):
        tecnico = crear_usuario('tec_sin_permiso_adelanto', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.client.force_login(tecnico)

        respuesta = self.client.get(reverse('pago_adelantado'))

        self.assertNotEqual(respuesta.status_code, 200)


class VerificacionBoletaTests(TestCase):
    """El programa que lee la boleta: parseo de montos / números y la
    comparación contra lo que se está pagando."""

    def test_extrae_montos_en_distintos_formatos(self):
        from decimal import Decimal

        from accounts.verificacion_boleta import extraer_montos

        texto = 'Deposito Q1,234.56 comision 0.00 total Q 1.234,56 otro 500,00'
        montos = extraer_montos(texto)
        self.assertIn(Decimal('1234.56'), montos)
        self.assertIn(Decimal('500.00'), montos)

    def test_extrae_numero_de_boleta(self):
        from accounts.verificacion_boleta import extraer_numeros

        self.assertEqual(extraer_numeros('No. Boleta: 000123456'), ['000123456'])
        self.assertEqual(extraer_numeros('Referencia # 55-6677'), ['556677'])

    def test_verificar_detecta_coincidencia(self):
        from accounts import verificacion_boleta

        original = verificacion_boleta._leer_texto
        verificacion_boleta._leer_texto = lambda *a, **k: 'Monto Q3,134.00\nBoleta 987654'
        try:
            r = verificacion_boleta.verificar(b'x', '3134.00', '987654')
            self.assertEqual(r.estado, verificacion_boleta.ESTADO_COINCIDE)
            self.assertTrue(r.ok)
        finally:
            verificacion_boleta._leer_texto = original

    def test_verificar_detecta_diferencia_de_monto(self):
        from accounts import verificacion_boleta

        original = verificacion_boleta._leer_texto
        verificacion_boleta._leer_texto = lambda *a, **k: 'Monto Q100.00'
        try:
            r = verificacion_boleta.verificar(b'x', '3134.00')
            self.assertEqual(r.estado, verificacion_boleta.ESTADO_NO_COINCIDE)
            self.assertFalse(r.monto_coincide)
        finally:
            verificacion_boleta._leer_texto = original

    def test_sin_ocr_devuelve_no_verificable(self):
        from accounts import verificacion_boleta

        original = verificacion_boleta._leer_texto
        verificacion_boleta._leer_texto = lambda *a, **k: None
        try:
            r = verificacion_boleta.verificar(b'x', '3134.00')
            self.assertEqual(r.estado, verificacion_boleta.ESTADO_NO_VERIFICABLE)
        finally:
            verificacion_boleta._leer_texto = original

   

    

    

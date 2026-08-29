from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
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


class HistorialComisionTests(TestCase):

    def setUp(self):
        self.admin = crear_usuario('admin_com', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.radiologo = crear_usuario('rad_com', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.client.force_login(self.admin)

    def _editar(self, **porcentajes):
        datos = {
            'first_name': 'R', 'last_name': 'C', 'email': 'rad@gmail.com',
            'rol': Usuario.ROL_MEDICO_RADIOLOGO, 'is_active': 'on', 'salario_base': '0',
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

        self.admin = crear_usuario('admin_planilla', rol=Usuario.ROL_ADMINISTRADOR, is_superuser=True)
        self.tecnico = crear_usuario(
            'tec_planilla', rol=Usuario.ROL_TECNICO_IMAGENES, salario_base=Decimal('3000'),
        )
        self.tecnico.porcentaje_privado = Decimal('5')
        self.tecnico.save()
        self.radiologo = crear_usuario(
            'rad_planilla', rol=Usuario.ROL_MEDICO_RADIOLOGO, salario_base=Decimal('6000'),
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

    def test_planilla_suma_salario_base_y_comisiones_del_mes(self):
        from decimal import Decimal

        self._cita_procesada()
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('planilla'), {'mes': '2026-08'})

        self.assertEqual(respuesta.status_code, 200)
        filas = {f['usuario'].username: f for f in respuesta.context['filas']}
        self.assertEqual(filas['tec_planilla']['comisiones'], Decimal('50.00'))
        self.assertEqual(filas['tec_planilla']['total'], Decimal('3050.00'))
        self.assertEqual(filas['rad_planilla']['comisiones'], Decimal('100.00'))
        self.assertEqual(filas['rad_planilla']['total'], Decimal('6100.00'))

    def test_detalle_empleado_lista_cada_comision_y_agrupa(self):
        import datetime
        from decimal import Decimal

        self._cita_procesada(hora=datetime.time(8, 0))
        self._cita_procesada(hora=datetime.time(10, 0))
        self.client.force_login(self.admin)

        respuesta = self.client.get(
            reverse('planilla_empleado', args=[self.tecnico.id]), {'mes': '2026-08'},
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(respuesta.context['lineas']), 2)
        self.assertEqual(respuesta.context['total_comisiones'], Decimal('100.00'))
        self.assertEqual(len(respuesta.context['resumen']), 1)
        grupo = respuesta.context['resumen'][0]
        self.assertEqual(grupo['cantidad'], 2)
        self.assertEqual(grupo['pct'], Decimal('5.00'))
        horas = [hora.strftime('%H:%M') for _, hora in grupo['momentos']]
        self.assertEqual(horas, ['08:00', '10:00'])

    def test_cita_fuera_del_periodo_no_cuenta(self):
        import datetime
        from decimal import Decimal

        self.fecha = datetime.date(2026, 7, 15)
        self._cita_procesada()
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('planilla'), {'mes': '2026-08'})

        filas = {f['usuario'].username: f for f in respuesta.context['filas']}
        self.assertEqual(filas['tec_planilla']['comisiones'], Decimal('0.00'))

    def test_rango_de_fechas_personalizado(self):
        import datetime
        from decimal import Decimal

        self.fecha = datetime.date(2026, 8, 10)
        self._cita_procesada()
        self.fecha = datetime.date(2026, 8, 20)
        self._cita_procesada()
        self.client.force_login(self.admin)

        respuesta = self.client.get(
            reverse('planilla'), {'desde': '2026-08-01', 'hasta': '2026-08-15'},
        )

        filas = {f['usuario'].username: f for f in respuesta.context['filas']}
        self.assertEqual(filas['tec_planilla']['comisiones'], Decimal('50.00'))

    def test_solo_el_administrador_ve_la_planilla(self):
        self.client.force_login(self.tecnico)
        respuesta = self.client.get(reverse('planilla'))
        self.assertNotEqual(respuesta.status_code, 200)

   

    

    

from unittest.mock import patch

import dns.exception
import dns.resolver
from django import forms
from django.contrib.messages import get_messages
from django.contrib.messages.storage.cookie import CookieStorage
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from .validators import (
    CODIGO_CORREO_NO_EXISTENTE,
    avisar_si_correo_no_existe,
    dominio_puede_recibir_correo,
    validar_correo_existente,
)


class DominioPuedeRecibirCorreoTests(SimpleTestCase):
    """clinica/validators.py: el chequeo de DNS en sí (sin tocar la red de
    verdad, todo con dns.resolver.resolve mockeado)."""

    @patch('clinica.validators.dns.resolver.resolve')
    def test_con_mx_puede_recibir(self, mock_resolve):
        mock_resolve.return_value = ['algún.mx.']
        self.assertTrue(dominio_puede_recibir_correo('gmail.com'))
        mock_resolve.assert_called_once_with('gmail.com', 'MX', lifetime=5)

    @patch('clinica.validators.dns.resolver.resolve')
    def test_dominio_inexistente_no_puede_recibir(self, mock_resolve):
        mock_resolve.side_effect = dns.resolver.NXDOMAIN()
        self.assertFalse(dominio_puede_recibir_correo('esto-no-existe-de-verdad.com'))

    @patch('clinica.validators.dns.resolver.resolve')
    def test_sin_mx_pero_con_a_puede_recibir(self, mock_resolve):
        # Primera llamada (MX) sin respuesta, segunda (A) sí responde.
        mock_resolve.side_effect = [dns.resolver.NoAnswer(), ['1.2.3.4']]
        self.assertTrue(dominio_puede_recibir_correo('sin-mx-pero-con-a.com'))

    @patch('clinica.validators.dns.resolver.resolve')
    def test_sin_ningun_registro_no_puede_recibir(self, mock_resolve):
        mock_resolve.side_effect = dns.resolver.NoAnswer()
        self.assertFalse(dominio_puede_recibir_correo('sin-nada.com'))

    @patch('clinica.validators.dns.resolver.resolve')
    def test_timeout_se_propaga_sin_convertirse_en_false(self, mock_resolve):
        # dominio_puede_recibir_correo no decide qué hacer con una falla de
        # red -- eso lo resuelve validar_correo_existente (fail-open).
        mock_resolve.side_effect = dns.exception.Timeout()
        with self.assertRaises(dns.exception.Timeout):
            dominio_puede_recibir_correo('dominio-cualquiera.com')


class ValidarCorreoExistenteTests(SimpleTestCase):
    """clinica/validators.py: la parte que decide si eso bloquea el
    formulario o no."""

    def test_correo_vacio_no_hace_nada(self):
        validar_correo_existente('')

    @patch('clinica.validators.dominio_puede_recibir_correo')
    def test_con_verificar_correo_existente_apagado_no_consulta_dns(self, mock_check):
        # Es lo que dejan las pruebas en clinica/settings_test.py -- ver
        # también que el resto de la suite (que llena el campo correo con
        # valores comunes tipo "juan@correo.com") no tarda segundos por
        # cada uno haciendo una consulta DNS real.
        validar_correo_existente('alguien@example.com')
        mock_check.assert_not_called()

    @override_settings(VERIFICAR_CORREO_EXISTENTE=True)
    @patch('clinica.validators.dominio_puede_recibir_correo')
    def test_dominio_que_no_puede_recibir_rechaza_el_correo(self, mock_check):
        mock_check.return_value = False
        with self.assertRaises(ValidationError):
            validar_correo_existente('alguien@no-existe.com')
        mock_check.assert_called_once_with('no-existe.com')

    @override_settings(VERIFICAR_CORREO_EXISTENTE=True)
    @patch('clinica.validators.dominio_puede_recibir_correo')
    def test_dominio_que_puede_recibir_no_rechaza_el_correo(self, mock_check):
        mock_check.return_value = True
        validar_correo_existente('alguien@gmail.com')

    @override_settings(VERIFICAR_CORREO_EXISTENTE=True)
    @patch('clinica.validators.dominio_puede_recibir_correo')
    def test_si_falla_el_dns_no_bloquea_el_formulario(self, mock_check):
        mock_check.side_effect = dns.exception.Timeout()
        # No debe propagar la falla de DNS como si el correo fuera malo.
        validar_correo_existente('alguien@example.com')


class _FormularioDePrueba(forms.Form):
    correo = forms.CharField(required=False)


def _request_con_messages():
    """Un request con el storage de mensajes ya armado, como lo tendría
    cualquier vista real (el middleware de messages lo hace por nosotros)."""
    request = RequestFactory().post('/algun-formulario/')
    request._messages = CookieStorage(request)
    return request


class AvisarSiCorreoNoExisteTests(SimpleTestCase):
    """La parte que conecta validar_correo_existente con un aviso más
    visible (banner) en la pantalla, sin duplicar el error normal bajo el
    campo."""

    def test_agrega_el_banner_cuando_el_error_es_correo_no_existente(self):
        form = _FormularioDePrueba(data={'correo': 'no-existe@example.com'})
        form.is_valid()
        form.add_error(
            'correo',
            ValidationError('no existe', code=CODIGO_CORREO_NO_EXISTENTE),
        )
        request = _request_con_messages()

        avisar_si_correo_no_existe(request, form)

        mensajes = [str(m) for m in get_messages(request)]
        self.assertEqual(mensajes, ['El correo ingresado no fue encontrado.'])

    def test_no_agrega_nada_si_el_correo_no_tiene_ese_error(self):
        form = _FormularioDePrueba(data={'correo': 'raro'})
        form.is_valid()
        form.add_error('correo', 'algún otro error, sin ese código')
        request = _request_con_messages()

        avisar_si_correo_no_existe(request, form)

        self.assertEqual(list(get_messages(request)), [])

    def test_no_agrega_nada_si_el_formulario_no_tiene_errores(self):
        form = _FormularioDePrueba(data={'correo': 'alguien@example.com'})
        form.is_valid()
        request = _request_con_messages()

        avisar_si_correo_no_existe(request, form)

        self.assertEqual(list(get_messages(request)), [])


class AdminDjangoConMfaTests(TestCase):
    """clinica/admin_site.py: /admin/ no tiene login propio (sin OTP) y solo
    deja entrar a una sesión de staff que pasó el código OTP."""

    def setUp(self):
        from accounts.models import Usuario
        self.ti = Usuario.objects.create_user(
            username='ti_admin', password='clave-segura-123', is_staff=True, is_superuser=True,
            rol=Usuario.ROL_ADMINISTRADOR,
        )
        self.device = TOTPDevice.objects.create(user=self.ti, confirmed=True)

    def _codigo(self):
        d = self.device
        return f'{totp(d.bin_key, step=d.step, t0=d.t0, digits=d.digits):0{d.digits}d}'

    def _entrar_con_otp(self):
        self.client.post(reverse('login'), {'username': 'ti_admin', 'password': 'clave-segura-123'})
        self.client.post(reverse('login_otp'), {'codigo': self._codigo()})

    def test_login_propio_del_admin_manda_al_login_de_la_clinica(self):
        respuesta = self.client.get('/admin/login/')
        self.assertRedirects(respuesta, reverse('login'), fetch_redirect_response=False)

    def test_superusuario_sin_otp_no_entra_al_admin(self):
        self.client.force_login(self.ti)
        respuesta = self.client.get('/admin/')
        self.assertEqual(respuesta.status_code, 302)

    def test_staff_con_otp_entra_al_admin(self):
        self._entrar_con_otp()
        self.assertEqual(self.client.get('/admin/').status_code, 200)

    def test_superusuario_sin_staff_no_entra_aunque_pase_el_otp(self):
        self.ti.is_staff = False
        self.ti.save(update_fields=['is_staff'])
        self._entrar_con_otp()
        self.assertEqual(self.client.get('/admin/').status_code, 302)


class LoginNextSeguroTests(TestCase):
    """El ?next= del login solo puede llevar a una página de este sitio."""

    def setUp(self):
        from accounts.models import Usuario
        Usuario.objects.create_user(username='recep_next', password='clave-segura-123',
                                    rol=Usuario.ROL_RECEPCIONISTA)

    def _entrar(self, siguiente):
        return self.client.post(
            f"{reverse('login')}?next={siguiente}",
            {'username': 'recep_next', 'password': 'clave-segura-123'},
        )

    def test_next_a_otro_sitio_se_ignora(self):
        respuesta = self._entrar('https://sitio-falso.com/')
        self.assertRedirects(respuesta, reverse('dashboard'), fetch_redirect_response=False)

    def test_next_interno_se_respeta(self):
        respuesta = self._entrar(reverse('dashboard') + '?x=1')
        self.assertRedirects(respuesta, reverse('dashboard') + '?x=1', fetch_redirect_response=False)


class CollectstaticDeProduccionTests(TestCase):
    """Las pruebas usan el storage de estáticos simple (settings_test), así
    que esto corre collectstatic con el storage con manifest de producción:
    falla si un CSS/JS referencia un archivo que no existe (pasó con el
    `sourceMappingURL=chart.umd.js.map` de Chart.js, que tumbaba el
    despliegue)."""

    def test_collectstatic_con_manifest_no_falla(self):
        import tempfile

        from django.core.management import call_command

        with tempfile.TemporaryDirectory() as destino, override_settings(
            STATIC_ROOT=destino,
            STORAGES={
                'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
            },
        ):
            call_command('collectstatic', interactive=False, verbosity=0)


class EncabezadosDeSeguridadTests(TestCase):
    """Ajustes por el escaneo de OWASP ZAP: páginas con sesión sin caché del
    navegador, cookie CSRF fuera del alcance de JavaScript y /static/ sin
    Access-Control-Allow-Origin: *."""

    def setUp(self):
        from accounts.models import Usuario
        self.usuario = Usuario.objects.create_user(
            username='recep_cache', password='clave-segura-123', rol=Usuario.ROL_RECEPCIONISTA,
        )

    def test_pagina_con_sesion_no_se_guarda_en_cache(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('dashboard'))
        self.assertIn('no-store', respuesta['Cache-Control'])
        self.assertIn('private', respuesta['Cache-Control'])

    def test_pagina_sin_sesion_no_lleva_no_store(self):
        respuesta = self.client.get(reverse('login'))
        self.assertNotIn('no-store', respuesta.get('Cache-Control', ''))

    def test_cookie_csrf_es_httponly(self):
        respuesta = self.client.get(reverse('login'))
        self.assertTrue(respuesta.cookies['csrftoken']['httponly'])

    def test_whitenoise_no_permite_todos_los_origenes(self):
        from django.conf import settings
        self.assertFalse(settings.WHITENOISE_ALLOW_ALL_ORIGINS)

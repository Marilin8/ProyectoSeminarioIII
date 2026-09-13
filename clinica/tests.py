from unittest.mock import patch

import dns.exception
import dns.resolver
from django import forms
from django.contrib.messages import get_messages
from django.contrib.messages.storage.cookie import CookieStorage
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase, override_settings

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

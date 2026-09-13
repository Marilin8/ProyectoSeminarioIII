import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError

from django import forms
from django.contrib.messages import get_messages
from django.contrib.messages.storage.cookie import CookieStorage
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase, override_settings

from .didit import DiditError, verificar_correo as verificar_correo_didit
from .validators import CODIGO_CORREO_NO_EXISTENTE, avisar_si_correo_no_existe, validar_correo_existente


def _respuesta_json(datos):
    """Simula lo que devuelve urllib.request.urlopen(...) como context
    manager: un objeto con .read() que da los bytes del body."""
    cuerpo = BytesIO(json.dumps(datos).encode('utf-8'))
    cuerpo.__enter__ = lambda self=cuerpo: self
    cuerpo.__exit__ = lambda self, *a: None
    return cuerpo


def _respuesta_didit(**email_overrides):
    email = {
        'status': 'Approved', 'email': 'alguien@example.com',
        'is_breached': False, 'breaches': [], 'is_disposable': False,
        'is_undeliverable': False,
    }
    email.update(email_overrides)
    return {'request_id': 'abc-123', 'status': 'Approved', 'email': email}


class VerificarCorreoDiditTests(SimpleTestCase):
    """clinica/didit.py: la llamada cruda a la API (sin tocar la red de
    verdad, todo con urlopen mockeado)."""

    @override_settings(DIDIT_API_KEY='')
    def test_sin_api_key_no_consulta_nada(self):
        with self.assertRaises(DiditError):
            verificar_correo_didit('alguien@example.com')

    @override_settings(DIDIT_API_KEY='clave-de-prueba')
    @patch('clinica.didit.urllib.request.urlopen')
    def test_devuelve_el_bloque_email_de_la_respuesta(self, mock_urlopen):
        mock_urlopen.return_value = _respuesta_json(_respuesta_didit(is_undeliverable=True))
        resultado = verificar_correo_didit('alguien@example.com')
        self.assertTrue(resultado['is_undeliverable'])

    @override_settings(DIDIT_API_KEY='clave-de-prueba')
    @patch('clinica.didit.urllib.request.urlopen')
    def test_error_de_red_se_convierte_en_diditerror(self, mock_urlopen):
        mock_urlopen.side_effect = URLError('sin conexión')
        with self.assertRaises(DiditError):
            verificar_correo_didit('alguien@example.com')

    @override_settings(DIDIT_API_KEY='clave-de-prueba')
    @patch('clinica.didit.urllib.request.urlopen')
    def test_respuesta_sin_bloque_email_es_error(self, mock_urlopen):
        mock_urlopen.return_value = _respuesta_json({'request_id': 'abc-123', 'status': 'Approved'})
        with self.assertRaises(DiditError):
            verificar_correo_didit('alguien@example.com')


class ValidarCorreoExistenteTests(SimpleTestCase):
    """clinica/validators.py: la parte que decide si eso bloquea el
    formulario o no."""

    @override_settings(DIDIT_API_KEY='')
    def test_sin_api_key_no_bloquea_nada(self):
        # No debe intentar red ni tronar solo porque falta la key.
        validar_correo_existente('alguien@example.com')

    def test_correo_vacio_no_hace_nada(self):
        validar_correo_existente('')

    @override_settings(DIDIT_API_KEY='clave-de-prueba')
    @patch('clinica.validators.verificar_correo')
    def test_undeliverable_rechaza_el_correo(self, mock_verificar):
        mock_verificar.return_value = _respuesta_didit(is_undeliverable=True)['email']
        with self.assertRaises(ValidationError):
            validar_correo_existente('no-existe@example.com')

    @override_settings(DIDIT_API_KEY='clave-de-prueba')
    @patch('clinica.validators.verificar_correo')
    def test_deliverable_no_rechaza_el_correo(self, mock_verificar):
        mock_verificar.return_value = _respuesta_didit(is_undeliverable=False)['email']
        validar_correo_existente('alguien@example.com')

    @override_settings(DIDIT_API_KEY='clave-de-prueba')
    @patch('clinica.validators.verificar_correo')
    def test_sin_el_campo_no_rechaza_el_correo(self, mock_verificar):
        # email_intelligence es "best effort": puede faltar is_undeliverable
        # del todo para un dominio sin cobertura. Ausente != True.
        mock_verificar.return_value = {'status': 'Approved', 'email': 'alguien@example.com'}
        validar_correo_existente('alguien@example.com')

    @override_settings(DIDIT_API_KEY='clave-de-prueba')
    @patch('clinica.validators.verificar_correo')
    def test_si_la_api_falla_no_bloquea_el_formulario(self, mock_verificar):
        mock_verificar.side_effect = DiditError('timeout')
        # No debe propagar el error de la API como si fuera un correo malo.
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

import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from .didit import DiditError, verificar_correo as verificar_correo_didit
from .validators import validar_correo_existente


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

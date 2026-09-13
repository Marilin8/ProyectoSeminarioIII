import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from .abstractapi import AbstractApiError, verificar_correo
from .validators import validar_correo_existente


def _respuesta_json(datos):
    """Simula lo que devuelve urllib.request.urlopen(...) como context
    manager: un objeto con .read() que da los bytes del body."""
    cuerpo = BytesIO(json.dumps(datos).encode('utf-8'))
    cuerpo.__enter__ = lambda self=cuerpo: self
    cuerpo.__exit__ = lambda self, *a: None
    return cuerpo


class VerificarCorreoAbstractApiTests(SimpleTestCase):
    """clinica/abstractapi.py: la llamada cruda a la API (sin tocar la red
    de verdad, todo con urlopen mockeado)."""

    @override_settings(ABSTRACT_API_KEY='')
    def test_sin_api_key_no_consulta_nada(self):
        with self.assertRaises(AbstractApiError):
            verificar_correo('alguien@example.com')

    @override_settings(ABSTRACT_API_KEY='clave-de-prueba')
    @patch('clinica.abstractapi.urllib.request.urlopen')
    def test_devuelve_el_dict_de_la_api_si_responde_bien(self, mock_urlopen):
        mock_urlopen.return_value = _respuesta_json({
            'email': 'alguien@example.com', 'deliverability': 'DELIVERABLE',
        })
        resultado = verificar_correo('alguien@example.com')
        self.assertEqual(resultado['deliverability'], 'DELIVERABLE')

    @override_settings(ABSTRACT_API_KEY='clave-de-prueba')
    @patch('clinica.abstractapi.urllib.request.urlopen')
    def test_error_de_red_se_convierte_en_abstractapierror(self, mock_urlopen):
        mock_urlopen.side_effect = URLError('sin conexión')
        with self.assertRaises(AbstractApiError):
            verificar_correo('alguien@example.com')


class ValidarCorreoExistenteTests(SimpleTestCase):
    """clinica/validators.py: la parte que decide si eso bloquea el
    formulario o no."""

    @override_settings(ABSTRACT_API_KEY='')
    def test_sin_api_key_no_bloquea_nada(self):
        # No debe intentar red ni tronar solo porque falta la key.
        validar_correo_existente('alguien@example.com')

    def test_correo_vacio_no_hace_nada(self):
        validar_correo_existente('')

    @override_settings(ABSTRACT_API_KEY='clave-de-prueba')
    @patch('clinica.validators.verificar_correo')
    def test_undeliverable_rechaza_el_correo(self, mock_verificar):
        mock_verificar.return_value = {'deliverability': 'UNDELIVERABLE'}
        with self.assertRaises(ValidationError):
            validar_correo_existente('no-existe@example.com')

    @override_settings(ABSTRACT_API_KEY='clave-de-prueba')
    @patch('clinica.validators.verificar_correo')
    def test_deliverable_no_rechaza_el_correo(self, mock_verificar):
        mock_verificar.return_value = {'deliverability': 'DELIVERABLE'}
        validar_correo_existente('alguien@example.com')

    @override_settings(ABSTRACT_API_KEY='clave-de-prueba')
    @patch('clinica.validators.verificar_correo')
    def test_risky_y_unknown_no_rechazan_el_correo(self, mock_verificar):
        for valor in ('RISKY', 'UNKNOWN'):
            mock_verificar.return_value = {'deliverability': valor}
            validar_correo_existente('alguien@example.com')

    @override_settings(ABSTRACT_API_KEY='clave-de-prueba')
    @patch('clinica.validators.verificar_correo')
    def test_si_la_api_falla_no_bloquea_el_formulario(self, mock_verificar):
        mock_verificar.side_effect = AbstractApiError('timeout')
        # No debe propagar el error de la API como si fuera un correo malo.
        validar_correo_existente('alguien@example.com')

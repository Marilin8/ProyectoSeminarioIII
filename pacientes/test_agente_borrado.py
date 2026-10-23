"""Huella SHA-256 al subir imágenes, API del agente de borrado y el agente
PowerShell real (agente_borrado/agente_borrado.ps1) contra un servidor de prueba."""
import hashlib
import io
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import AgenteEquipo, Usuario
from pacientes.models import Cita, ImagenEstudio, OrdenTrabajo
from pacientes.tests import crear_cita, crear_usuario
from pacientes.views.estudios import _guardar_imagen_o_convertir_dicom

URL = '/api/agente/huellas/'


def sha(datos):
    return hashlib.sha256(datos).hexdigest()


class DatosOrden:
    def crear_orden(self):
        self.tecnico = crear_usuario('tec_agente', rol=Usuario.ROL_TECNICO_IMAGENES)
        cita = crear_cita(self.tecnico, estado=Cita.ESTADO_EN_PROCESO)
        self.orden = OrdenTrabajo.objects.create(cita=cita, motivo='Control', creada_por=self.tecnico)

    def imagen(self, datos, **extra):
        return ImagenEstudio.objects.create(
            orden=self.orden, tipo_estudio=self.orden.cita.tipo_estudio, subida_por=self.tecnico,
            archivo=extra.pop('archivo', ContentFile(datos, name='a.jpg')), huella_sha256=sha(datos), **extra,
        )

    def crear_agente(self, nombre='PC prueba'):
        agente = AgenteEquipo(nombre=nombre)
        token = agente.generar_token()
        agente.save()
        return agente, token


class HuellaAlSubirTests(DatosOrden, TestCase):
    def setUp(self):
        self.crear_orden()

    def test_jpg_guarda_la_huella_de_los_bytes_subidos(self):
        datos = b'\xff\xd8 jpg de prueba \xff\xd9'
        _guardar_imagen_o_convertir_dicom(
            SimpleUploadedFile('placa.jpg', datos, 'image/jpeg'), self.orden, self.tecnico, None,
        )
        self.assertEqual(ImagenEstudio.objects.get().huella_sha256, sha(datos))

    def test_dicom_guarda_la_huella_del_original_no_del_jpg_convertido(self):
        datos = b'DICM contenido original del equipo'
        with mock.patch('pacientes.views.estudios.dicom_a_jpg_memoria',
                        return_value=ContentFile(b'jpg convertido', name='x.jpg')):
            _guardar_imagen_o_convertir_dicom(
                SimpleUploadedFile('I0001', datos), self.orden, self.tecnico, None,
            )
        imagen = ImagenEstudio.objects.get()
        self.assertEqual(imagen.huella_sha256, sha(datos))
        self.assertEqual(imagen.archivo_original.read(), datos)


class ApiConfirmarHuellasTests(DatosOrden, TestCase):
    def setUp(self):
        self.crear_orden()
        self.agente, self.token = self.crear_agente()

    def pedir(self, huellas, token=None):
        return self.client.post(
            URL, json.dumps({'huellas': huellas}), content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.token if token is None else token}',
        )

    def test_la_url_es_la_esperada(self):
        self.assertEqual(reverse('agente_confirmar_huellas'), URL)

    def test_sin_token_o_con_token_malo_responde_401(self):
        self.assertEqual(self.client.post(URL, '{}', content_type='application/json').status_code, 401)
        self.assertEqual(self.pedir([], token='otro').status_code, 401)

    def test_token_revocado_responde_401(self):
        self.agente.activo = False
        self.agente.save()
        self.assertEqual(self.pedir([]).status_code, 401)

    def test_confirma_solo_las_huellas_que_el_sistema_tiene(self):
        self.imagen(b'uno')
        respuesta = self.pedir([sha(b'uno'), sha(b'no subido'), 'cualquier cosa'])
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json(), {'confirmadas': [sha(b'uno')]})

    def test_no_confirma_un_jpg_descartado_pero_si_un_dicom_con_original(self):
        descartado = self.imagen(b'jpg descartado')
        descartado.archivo = ''
        descartado.save()
        dicom = self.imagen(b'dicom', archivo='')
        dicom.archivo_original.save('I0001.dcm', ContentFile(b'dicom'))
        respuesta = self.pedir([sha(b'jpg descartado'), sha(b'dicom')])
        self.assertEqual(respuesta.json(), {'confirmadas': [sha(b'dicom')]})

    def test_acepta_huellas_en_mayusculas(self):
        self.imagen(b'uno')
        self.assertEqual(self.pedir([sha(b'uno').upper()]).json(), {'confirmadas': [sha(b'uno')]})

    def test_rechaza_json_invalido_y_listas_demasiado_grandes(self):
        malo = self.client.post(URL, 'no es json', content_type='application/json',
                                HTTP_AUTHORIZATION=f'Bearer {self.token}')
        self.assertEqual(malo.status_code, 400)
        self.assertEqual(self.pedir(['a' * 64] * 1001).status_code, 400)

    def test_solo_acepta_post_y_registra_el_ultimo_uso(self):
        self.assertEqual(self.client.get(URL, HTTP_AUTHORIZATION=f'Bearer {self.token}').status_code, 405)
        self.pedir([])
        self.agente.refresh_from_db()
        self.assertIsNotNone(self.agente.ultimo_uso)


class ComandoTokenAgenteTests(TestCase):
    def test_crear_renovar_y_revocar(self):
        salida = io.StringIO()
        call_command('token_agente', 'crear', 'Sala 1', stdout=salida)
        token = salida.getvalue().strip().splitlines()[-1]
        self.assertEqual(AgenteEquipo.autenticar(token).nombre, 'Sala 1')

        salida = io.StringIO()
        call_command('token_agente', 'renovar', 'Sala 1', stdout=salida)
        nuevo = salida.getvalue().strip().splitlines()[-1]
        self.assertIsNone(AgenteEquipo.autenticar(token))
        self.assertIsNotNone(AgenteEquipo.autenticar(nuevo))

        call_command('token_agente', 'revocar', 'Sala 1', stdout=io.StringIO())
        self.assertIsNone(AgenteEquipo.autenticar(nuevo))


SCRIPT = Path(settings.BASE_DIR) / 'agente_borrado' / 'agente_borrado.ps1'


@unittest.skipUnless(sys.platform == 'win32' and shutil.which('powershell'), 'requiere PowerShell de Windows')
class PuenteHTTP:
    """Servidor HTTP mínimo para el agente: cada pedido se pasa al hilo del test,
    que lo responde con el cliente de prueba de Django (la vista real, dentro de la
    transacción del TestCase). Así no hace falta LiveServerTestCase, que vacía las
    tablas al terminar y rompe a los demás tests con --reuse-db."""

    def __init__(self):
        self.pedidos = queue.Queue()
        puente = self

        class Manejador(BaseHTTPRequestHandler):
            def do_POST(self):
                pedido = {
                    'ruta': self.path,
                    'cuerpo': self.rfile.read(int(self.headers.get('Content-Length') or 0)),
                    'auth': self.headers.get('Authorization', ''),
                    'listo': threading.Event(),
                }
                puente.pedidos.put(pedido)
                pedido['listo'].wait(60)
                self.send_response(pedido['estado'])
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(pedido['respuesta'])

            def log_message(self, *args):
                pass

        self.servidor = ThreadingHTTPServer(('127.0.0.1', 0), Manejador)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.servidor.server_address[1]}'

    def cerrar(self):
        self.servidor.shutdown()
        self.servidor.server_close()


class AgentePowerShellTests(DatosOrden, TestCase):
    """Corre el agente real (PowerShell) contra la vista real, en modo "borrar"."""

    def setUp(self):
        self.crear_orden()
        _agente, self.token = self.crear_agente()
        self.puente = PuenteHTTP()
        self.dir_agente = Path(tempfile.mkdtemp())
        shutil.copy(SCRIPT, self.dir_agente)
        self.carpeta = self.dir_agente / 'radiant'
        (self.carpeta / 'estudio1').mkdir(parents=True)
        (self.dir_agente / 'agente.json').write_text(json.dumps({
            'url_sistema': self.puente.url, 'token': self.token, 'carpetas': [str(self.carpeta)],
            'modo': 'borrar', 'minutos_sin_cambios': 5,
        }), encoding='utf-8')

    def tearDown(self):
        self.puente.cerrar()
        shutil.rmtree(self.dir_agente, ignore_errors=True)

    def archivo(self, ruta, datos, viejo=True):
        p = self.carpeta / ruta
        p.write_bytes(datos)
        if viejo:
            hace_rato = time.time() - 3600
            os.utime(p, (hace_rato, hace_rato))
        return p

    def correr(self, *extra):
        proceso = subprocess.Popen(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
             str(self.dir_agente / 'agente_borrado.ps1'), *extra],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        limite = time.time() + 120
        while proceso.poll() is None and time.time() < limite:
            try:
                pedido = self.puente.pedidos.get(timeout=0.2)
            except queue.Empty:
                continue
            respuesta = self.client.generic(
                'POST', pedido['ruta'], pedido['cuerpo'], content_type='application/json',
                HTTP_AUTHORIZATION=pedido['auth'],
            )
            pedido['estado'], pedido['respuesta'] = respuesta.status_code, respuesta.content
            pedido['listo'].set()
        salida, errores = proceso.communicate(timeout=30)
        return subprocess.CompletedProcess(proceso.args, proceso.returncode, salida, errores)

    def test_borra_solo_lo_que_el_sistema_confirma(self):
        subido = self.archivo('estudio1/I0001', b'dicom subido')
        no_subido = self.archivo('I0002', b'dicom que no se subio')
        recien = self.archivo('I0003', b'recien copiado', viejo=False)
        self.imagen(b'dicom subido')
        self.imagen(b'recien copiado')

        resultado = self.correr()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertFalse(subido.exists())
        self.assertFalse(subido.parent.exists())  # carpeta que quedó vacía
        self.assertTrue(no_subido.exists())
        self.assertTrue(recien.exists())  # modificado hace menos de 5 minutos
        log = (self.dir_agente / 'agente_borrado.log').read_text(encoding='utf-8-sig')
        self.assertIn('Borrado (borrar)', log)

    def test_simular_no_borra(self):
        subido = self.archivo('I0001', b'dicom subido')
        self.imagen(b'dicom subido')
        resultado = self.correr('-Simular')
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertTrue(subido.exists())
        self.assertIn('SIMULACION', resultado.stdout)

    def test_con_token_malo_no_borra_nada(self):
        subido = self.archivo('I0001', b'dicom subido')
        self.imagen(b'dicom subido')
        config = json.loads((self.dir_agente / 'agente.json').read_text(encoding='utf-8'))
        config['token'] = 'token-equivocado'
        (self.dir_agente / 'agente.json').write_text(json.dumps(config), encoding='utf-8')
        resultado = self.correr()
        self.assertEqual(resultado.returncode, 1)
        self.assertTrue(subido.exists())

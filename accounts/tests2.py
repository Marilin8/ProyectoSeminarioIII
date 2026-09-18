from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from accounts.models import Bitacora, Usuario

UsuarioModel = get_user_model()


def crear_usuario(username='usuario', rol=Usuario.ROL_RECEPCIONISTA, **kwargs):
    return UsuarioModel.objects.create_user(username=username, password='clave-segura-123', rol=rol, **kwargs)


class UsuarioModelTests(TestCase):

    def test_el_rol_por_defecto_es_administrador(self):
        usuario = UsuarioModel.objects.create_user(username='sin_rol', password='clave-segura-123')
        self.assertEqual(usuario.rol, Usuario.ROL_ADMINISTRADOR)

    def test_se_puede_crear_con_un_rol_especifico(self):
        usuario = crear_usuario('tecnico1', rol=Usuario.ROL_TECNICO_IMAGENES)
        self.assertEqual(usuario.rol, Usuario.ROL_TECNICO_IMAGENES)

    def test_los_porcentajes_de_comision_inician_en_cero(self):
        usuario = crear_usuario('radiologo1', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.assertEqual(usuario.porcentaje_coex, 0)
        self.assertEqual(usuario.porcentaje_privado, 0)
        self.assertEqual(usuario.porcentaje_emergencia_igss, 0)



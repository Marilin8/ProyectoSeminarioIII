from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.menu_lateral import arbol_para

Usuario = get_user_model()


class MenuLateralTests(TestCase):
    def _usuario(self, username, rol):
        return Usuario.objects.create_user(username=username, password='clave-segura-123', rol=rol)

    def test_el_admin_tiene_todas_sus_opciones_y_los_submenus(self):
        admin = self._usuario('admin-menu', Usuario.ROL_ADMINISTRADOR)

        arbol = arbol_para(admin, reverse('panel_financiero'))

        nombres = [n['nombre'] for n in arbol]
        self.assertEqual(nombres[0], 'Paneles')
        for esperado in ('Usuarios activos', 'Respaldos', 'Reportes diarios', 'Planilla'):
            self.assertIn(esperado, nombres)
        paneles = arbol[0]
        self.assertEqual([h['nombre'] for h in paneles['hijos']], ['Estadísticas', 'Finanzas', 'Estado de la Clínica'])
        self.assertTrue(paneles['activo'])  # estamos en Finanzas
        self.assertFalse(paneles['hijos'][0]['activo'])  # /dashboard/ no se marca en /dashboard/finanzas/
        self.assertTrue(paneles['hijos'][1]['activo'])

    def test_cada_rol_ve_solo_lo_suyo(self):
        recepcion = self._usuario('recep-menu', Usuario.ROL_RECEPCIONISTA)

        nombres = [n['nombre'] for n in arbol_para(recepcion)]

        self.assertIn('COEX', nombres)
        self.assertNotIn('Paneles', nombres)
        self.assertNotIn('Respaldos', nombres)

    def test_la_barra_muestra_el_menu_desplegable(self):
        admin = self._usuario('admin-menu2', Usuario.ROL_ADMINISTRADOR)
        self.client.force_login(admin)

        respuesta = self.client.get(reverse('mi_perfil'))

        self.assertContains(respuesta, 'class="menu-columna"')
        self.assertContains(respuesta, 'data-abre="menu-reportes_diarios-0"')
        self.assertContains(respuesta, reverse('lista_reportes_diarios_privado'))
        self.assertContains(respuesta, reverse('respaldos'))

    def test_sin_sesion_no_hay_menu(self):
        respuesta = self.client.get(reverse('login'))

        self.assertNotContains(respuesta, 'menu-columna')

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Bitacora, Sucursal
from pacientes.models import Cita, Paciente, TipoEstudio

Usuario = get_user_model()


class SucursalesTests(TestCase):
    def setUp(self):
        self.principal = Sucursal.objects.get(es_principal=True)  # la crea la migración 0056
        self.admin = Usuario.objects.create_user(
            username='admin-suc', password='clave-segura-123', rol=Usuario.ROL_ADMINISTRADOR,
        )
        self.recep = Usuario.objects.create_user(
            username='recep-suc', password='clave-segura-123', rol=Usuario.ROL_RECEPCIONISTA,
        )

    def test_la_migracion_crea_la_principal_y_las_citas_nuevas_caen_ahi(self):
        paciente = Paciente.objects.create(
            dpi='3000000000001', nombre='P', apellido='S', sexo=Paciente.SEXO_FEMENINO,
            fecha_nacimiento=datetime.date(1990, 1, 1),
        )
        cita = Cita.objects.create(
            paciente=paciente, tipo_estudio=TipoEstudio.objects.create(nombre='RX suc'),
            convenio=Cita.CONVENIO_PRIVADO, fecha=timezone.localdate(), hora=datetime.time(9, 0),
            creada_por=self.admin,
        )
        self.assertEqual(self.principal.nombre, 'Sucursal principal')
        self.assertEqual(cita.sucursal, self.principal)

    def test_el_admin_crea_una_sucursal_y_le_asigna_usuarios(self):
        self.client.force_login(self.admin)

        respuesta = self.client.post(reverse('crear_sucursal'), {
            'nombre': 'Sucursal Norte', 'direccion': 'Zona 18', 'telefono': '2222-0000',
            'activa': 'on', 'usuarios': [self.recep.id],
        })

        self.assertRedirects(respuesta, reverse('lista_sucursales'))
        norte = Sucursal.objects.get(nombre='Sucursal Norte')
        self.assertIn(norte, self.recep.sucursales.all())
        self.assertTrue(Bitacora.objects.filter(accion=Bitacora.ACCION_GESTIONAR_SUCURSAL).exists())
        self.assertContains(self.client.get(reverse('lista_sucursales')), 'Sucursal Norte')

    def test_editar_quita_a_un_usuario_de_la_sucursal(self):
        norte = Sucursal.objects.create(nombre='Norte')
        self.recep.sucursales.add(norte, self.principal)
        self.client.force_login(self.admin)

        self.client.post(reverse('editar_sucursal', args=[norte.id]), {'nombre': 'Norte', 'activa': 'on'})

        self.assertEqual(list(self.recep.sucursales.all()), [self.principal])

    def test_la_principal_no_se_puede_desactivar(self):
        self.client.force_login(self.admin)

        self.client.post(reverse('editar_sucursal', args=[self.principal.id]), {'nombre': 'Central'})

        self.principal.refresh_from_db()
        self.assertTrue(self.principal.activa)
        self.assertEqual(self.principal.nombre, 'Central')

    def test_solo_el_administrador_gestiona_sucursales(self):
        self.client.force_login(self.recep)
        self.assertEqual(self.client.get(reverse('lista_sucursales')).status_code, 302)
        self.assertEqual(self.client.post(reverse('crear_sucursal'), {'nombre': 'X'}).status_code, 302)
        self.assertFalse(Sucursal.objects.filter(nombre='X').exists())

    def test_usuario_con_varias_sucursales_elige_la_activa(self):
        norte = Sucursal.objects.create(nombre='Norte')
        ajena = Sucursal.objects.create(nombre='Ajena')
        self.recep.sucursales.add(self.principal, norte)
        self.client.force_login(self.recep)

        pagina = self.client.get(reverse('mi_perfil'))
        self.assertContains(pagina, 'id="selector-sucursal"')
        self.assertEqual(pagina.context['sucursal_activa'], self.principal)

        self.client.post(reverse('cambiar_sucursal'), {'sucursal': norte.id, 'siguiente': reverse('mi_perfil')})
        self.assertEqual(self.client.get(reverse('mi_perfil')).context['sucursal_activa'], norte)

        # Una sucursal que no es suya no se puede elegir.
        self.client.post(reverse('cambiar_sucursal'), {'sucursal': ajena.id})
        self.assertEqual(self.client.get(reverse('mi_perfil')).context['sucursal_activa'], norte)
        # Tampoco "todas".
        self.client.post(reverse('cambiar_sucursal'), {'sucursal': 'todas'})
        self.assertEqual(self.client.get(reverse('mi_perfil')).context['sucursal_activa'], norte)

    def test_con_una_sola_sucursal_no_hay_selector(self):
        self.recep.sucursales.add(self.principal)
        self.client.force_login(self.recep)

        pagina = self.client.get(reverse('mi_perfil'))

        self.assertNotContains(pagina, 'id="selector-sucursal"')
        self.assertContains(pagina, 'sidebar-sucursal-fija')

    def test_el_admin_puede_ver_todas_o_una(self):
        Sucursal.objects.create(nombre='Norte')
        self.client.force_login(self.admin)

        self.assertIsNone(self.client.get(reverse('mi_perfil')).context['sucursal_activa'])
        self.client.post(reverse('cambiar_sucursal'), {'sucursal': self.principal.id})
        self.assertEqual(self.client.get(reverse('mi_perfil')).context['sucursal_activa'], self.principal)
        self.client.post(reverse('cambiar_sucursal'), {'sucursal': 'todas'})
        self.assertIsNone(self.client.get(reverse('mi_perfil')).context['sucursal_activa'])

    def test_cambiar_no_redirige_a_otro_sitio(self):
        self.client.force_login(self.admin)

        respuesta = self.client.post(reverse('cambiar_sucursal'), {'sucursal': 'todas', 'siguiente': 'https://malo.com/'})

        self.assertRedirects(respuesta, reverse('dashboard'))

    def test_sin_marcar_sucursal_queda_en_la_principal(self):
        from accounts.forms import _sucursales_o_principal
        norte = Sucursal.objects.create(nombre='Norte')

        self.assertEqual(_sucursales_o_principal([]), [self.principal])
        self.assertEqual(_sucursales_o_principal([norte]), [norte])

"""Etapa 2 de sucursales: agenda, citas, turnos, caja, órdenes y reportes diarios
trabajan con la sucursal activa del usuario."""
import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Sucursal
from pacientes.models import (
    Cita, Notificacion, OrdenTrabajo, Paciente, ReporteDiario, Ticket, TipoEstudio,
)
from pacientes.tests import Usuario, crear_cita, crear_paciente, crear_usuario


class SucursalesOperacionTests(TestCase):
    def setUp(self):
        self.principal = Sucursal.objects.get(es_principal=True)
        self.norte = Sucursal.objects.create(nombre='Norte')
        self.recep_norte = crear_usuario('recep_norte', rol=Usuario.ROL_RECEPCIONISTA)
        self.recep_norte.sucursales.set([self.norte])
        self.recep_central = crear_usuario('recep_central', rol=Usuario.ROL_RECEPCIONISTA)
        self.recep_central.sucursales.set([self.principal])
        self.rad_norte = crear_usuario('rad_norte', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.rad_norte.sucursales.set([self.norte])
        self.rad_central = crear_usuario('rad_central', rol=Usuario.ROL_MEDICO_RADIOLOGO)
        self.rad_central.sucursales.set([self.principal])
        self.estudio = TipoEstudio.objects.create(nombre='RX sucursal')
        self.estudio.radiologos.add(self.rad_norte, self.rad_central)
        self.fecha = timezone.localdate() + datetime.timedelta(days=2)

    def _agendar_privado(self, usuario, dpi='7070707070701', hora='10:00'):
        self.client.force_login(usuario)
        return self.client.post(reverse('agendar_cita_privado'), {
            'dpi': dpi, 'nombre': 'Ana', 'apellido': 'Suc', 'sexo': Paciente.SEXO_FEMENINO,
            'telefono': '55550000', 'correo': '', 'fecha_nacimiento': '1990-01-01',
            'tipo_estudio': self.estudio.id, 'fecha': self.fecha.isoformat(), 'hora': hora,
            'motivo': 'Control',
        }, follow=True)

    def test_la_cita_queda_en_la_sucursal_activa_con_un_radiologo_de_ahi(self):
        self._agendar_privado(self.recep_norte)

        cita = Cita.objects.get(paciente__dpi='7070707070701')
        self.assertEqual(cita.sucursal, self.norte)
        # Hay dos radiólogos para el estudio, pero en Norte solo trabaja uno: se asigna solo.
        self.assertEqual(cita.radiologo, self.rad_norte)
        self.assertTrue(ReporteDiario.objects.filter(
            fecha=self.fecha, convenio=Cita.CONVENIO_PRIVADO, sucursal=self.norte,
        ).exists())

    def test_cada_sucursal_tiene_su_propia_agenda(self):
        self._agendar_privado(self.recep_central, dpi='7070707070702')

        calendario = self.client.get(reverse('calendario_privado'), {'semana': self.fecha.isoformat()})
        self.assertContains(calendario, 'Ana Suc')

        self.client.force_login(self.recep_norte)
        calendario = self.client.get(reverse('calendario_privado'), {'semana': self.fecha.isoformat()})
        self.assertNotContains(calendario, 'Ana Suc')

    def test_no_se_ven_ni_abren_citas_de_otra_sucursal(self):
        ajena = crear_cita(self.recep_central, fecha=timezone.localdate(), sucursal=self.principal)
        self.client.force_login(self.recep_norte)

        lista = self.client.get(reverse('procesar_citas_privado'))
        self.assertNotIn(ajena, list(lista.context['citas']))
        respuesta = self.client.post(reverse('marcar_llegada_privado', args=[ajena.id]))
        self.assertEqual(respuesta.status_code, 404)

    def test_turnos_numerados_y_en_fila_por_sucursal(self):
        cita_norte = crear_cita(self.recep_norte, fecha=timezone.localdate(), sucursal=self.norte,
                                paciente=crear_paciente(dpi='7070707070703'))
        cita_central = crear_cita(self.recep_central, fecha=timezone.localdate(), sucursal=self.principal,
                                  paciente=crear_paciente(dpi='7070707070704'))
        self.client.force_login(self.recep_norte)
        self.client.post(reverse('marcar_llegada_privado', args=[cita_norte.id]))
        self.client.force_login(self.recep_central)
        self.client.post(reverse('marcar_llegada_privado', args=[cita_central.id]))

        t_norte = Ticket.objects.get(cita=cita_norte)
        t_central = Ticket.objects.get(cita=cita_central)
        self.assertEqual((t_norte.sucursal, t_norte.turno), (self.norte, '001'))
        self.assertEqual((t_central.sucursal, t_central.turno), (self.principal, '001'))

        cola = self.client.get(reverse('pantalla_turnos')).context['cola']
        self.assertEqual(list(cola), [t_central])

        sala = self.client.get(reverse('estado_sala_espera'), {'sucursal': self.norte.id}).json()
        self.assertEqual([p['turno'] for p in sala['proximos']], ['001'])

    def test_reportes_diarios_separados_por_sucursal(self):
        hoy = timezone.localdate()
        crear_cita(self.recep_norte, fecha=hoy, sucursal=self.norte, paciente=crear_paciente(dpi='7070707070705'))
        crear_cita(self.recep_central, fecha=hoy, sucursal=self.principal, paciente=crear_paciente(dpi='7070707070706'))
        ReporteDiario.asegurar_del_dia(hoy)
        self.assertEqual(ReporteDiario.objects.filter(fecha=hoy, convenio=Cita.CONVENIO_PRIVADO).count(), 2)

        self.client.force_login(self.recep_norte)
        lista = self.client.get(reverse('lista_reportes_diarios_privado'))
        self.assertEqual({r.sucursal for r in lista.context['reportes']}, {self.norte})
        reporte = self.client.get(
            reverse('ver_reporte_diario', args=['privado', hoy.isoformat()]), {'sucursal': self.norte.id},
        )
        self.assertEqual(reporte.context['reporte'].sucursal, self.norte)
        self.assertEqual([c.sucursal for c in reporte.context['reporte'].citas()], [self.norte])
        # No puede abrir el de una sucursal que no es suya: cae en la suya.
        ajeno = self.client.get(
            reverse('ver_reporte_diario', args=['privado', hoy.isoformat()]), {'sucursal': self.principal.id},
        )
        self.assertEqual(ajeno.context['reporte'].sucursal, self.norte)

    def test_los_avisos_van_solo_a_la_sucursal_de_la_cita(self):
        tec_norte = crear_usuario('tec_norte', rol=Usuario.ROL_TECNICO_IMAGENES)
        tec_norte.sucursales.set([self.norte])
        tec_central = crear_usuario('tec_central', rol=Usuario.ROL_TECNICO_IMAGENES)
        tec_central.sucursales.set([self.principal])
        cita = crear_cita(self.recep_norte, fecha=timezone.localdate(), sucursal=self.norte,
                          paciente=crear_paciente(dpi='7070707070707'))
        self.client.force_login(self.recep_norte)
        self.client.post(reverse('marcar_llegada_privado', args=[cita.id]))

        self.client.post(reverse('generar_orden_privado', args=[cita.id]), {'motivo': 'Dolor'})

        self.assertTrue(OrdenTrabajo.objects.filter(cita=cita).exists())
        self.assertTrue(Notificacion.objects.filter(destinatario=tec_norte).exists())
        self.assertFalse(Notificacion.objects.filter(destinatario=tec_central).exists())

    def test_el_admin_en_todas_debe_elegir_sucursal_para_agendar(self):
        from accounts.models import RolAdicional
        admin = crear_usuario('admin_suc_op', rol=Usuario.ROL_ADMINISTRADOR)
        RolAdicional.objects.create(usuario=admin, rol=Usuario.ROL_RECEPCIONISTA)
        self.client.force_login(admin)

        respuesta = self.client.get(reverse('calendario_privado'))

        self.assertRedirects(respuesta, reverse('dashboard'), fetch_redirect_response=False)
        self.client.post(reverse('cambiar_sucursal'), {'sucursal': self.norte.id})
        self.assertEqual(self.client.get(reverse('calendario_privado')).status_code, 200)

    def test_las_notificaciones_son_solo_de_la_sucursal_activa(self):
        recep = crear_usuario('recep_dos_suc', rol=Usuario.ROL_RECEPCIONISTA)
        recep.sucursales.set([self.principal, self.norte])
        cita_central = crear_cita(recep, sucursal=self.principal, paciente=crear_paciente(dpi='7070707070708'))
        cita_norte = crear_cita(recep, sucursal=self.norte, paciente=crear_paciente(dpi='7070707070709'))
        Notificacion.objects.create(destinatario=recep, tipo=Notificacion.TIPO_ESTUDIO_VALIDADO, mensaje='Central', cita=cita_central)
        Notificacion.objects.create(destinatario=recep, tipo=Notificacion.TIPO_ESTUDIO_VALIDADO, mensaje='Norte', cita=cita_norte)
        Notificacion.objects.create(destinatario=recep, tipo=Notificacion.TIPO_REPORTE_ENVIADO, mensaje='General')
        self.client.force_login(recep)

        def mensajes():
            datos = self.client.get(reverse('notificaciones_pendientes')).json()
            return sorted(n['mensaje'] for n in datos['notificaciones']), datos['no_leidas']

        self.client.post(reverse('cambiar_sucursal'), {'sucursal': self.principal.id})
        self.assertEqual(mensajes(), (['Central', 'General'], 2))
        self.client.post(reverse('cambiar_sucursal'), {'sucursal': self.norte.id})
        self.assertEqual(mensajes(), (['General', 'Norte'], 2))

        # "Marcar todas" solo marca las que está viendo: las de Central siguen pendientes.
        self.client.post(reverse('marcar_notificaciones_leidas'))
        self.client.post(reverse('cambiar_sucursal'), {'sucursal': self.principal.id})
        self.assertEqual(mensajes(), (['Central'], 1))


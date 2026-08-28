from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models


class Usuario(AbstractUser):
    ROL_ADMINISTRADOR = 'administrador'
    ROL_ADMINISTRADOR_FINANCIERO = 'administrador_financiero'
    ROL_RECEPCIONISTA = 'recepcionista'
    ROL_TECNICO_IMAGENES = 'tecnico_imagenes'
    ROL_MEDICO_RADIOLOGO = 'medico_radiologo'
    ROL_MEDICO_REMITENTE = 'medico_remitente'

    ROL_CHOICES = [
        (ROL_ADMINISTRADOR, 'Administrador'),
        (ROL_ADMINISTRADOR_FINANCIERO, 'Administrador financiero'),
        (ROL_RECEPCIONISTA, 'Recepcionista'),
        (ROL_TECNICO_IMAGENES, 'Técnico de imágenes'),
        (ROL_MEDICO_RADIOLOGO, 'Médico radiólogo'),
        (ROL_MEDICO_REMITENTE, 'Médico remitente'),
    ]

    rol = models.CharField(
        max_length=25,
        choices=ROL_CHOICES,
        default=ROL_ADMINISTRADOR,
        verbose_name='rol',
    )

    # Comisión aplicable a técnicos, radiólogos y médicos remitentes: % sobre
    # el precio del estudio, según el convenio de la cita en que participaron.
    porcentaje_coex = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, verbose_name='% comisión COEX',
    )
    porcentaje_privado = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, verbose_name='% comisión privado',
    )
    porcentaje_emergencia_igss = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, verbose_name='% comisión emergencia IGSS',
    )

    groups = models.ManyToManyField(
        Group,
        verbose_name='grupos',
        blank=True,
        related_name='usuario_set',
        related_query_name='usuario',
        db_table='usuarios_grupos',
    )
    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name='permisos',
        blank=True,
        related_name='usuario_set',
        related_query_name='usuario',
        db_table='usuarios_permisos',
    )

    class Meta:
        db_table = 'usuarios'
        verbose_name = 'usuario'
        verbose_name_plural = 'usuarios'


class Bitacora(models.Model):
    ACCION_LOGIN_EXITOSO = 'login_exitoso'
    ACCION_LOGIN_FALLIDO = 'login_fallido'
    ACCION_CREAR_USUARIO = 'crear_usuario'
    ACCION_EDITAR_USUARIO = 'editar_usuario'
    ACCION_CAMBIAR_ESTADO_USUARIO = 'cambiar_estado_usuario'
    ACCION_EDITAR_COMISION = 'editar_comision'
    ACCION_CREAR_ESTUDIO = 'crear_estudio'
    ACCION_EDITAR_ESTUDIO = 'editar_estudio'
    ACCION_SOLICITAR_CITA = 'solicitar_cita'
    ACCION_CONFIRMAR_CITA = 'confirmar_cita'
    ACCION_RECHAZAR_CITA = 'rechazar_cita'
    ACCION_REAGENDAR_CITA = 'reagendar_cita'
    ACCION_MARCAR_LLEGADA = 'marcar_llegada'
    ACCION_MARCAR_AUSENTE = 'marcar_ausente'
    ACCION_GENERAR_ORDEN = 'generar_orden'
    ACCION_ADJUNTAR_IMAGENES = 'adjuntar_imagenes'
    ACCION_SELECCIONAR_IMAGENES = 'seleccionar_imagenes'
    ACCION_ADJUNTAR_INFORME = 'adjuntar_informe'
    ACCION_ENVIAR_ESTUDIO = 'enviar_estudio'
    ACCION_REGISTRAR_TICKET = 'registrar_ticket'
    ACCION_PROCESAR_TICKET = 'procesar_ticket'
    ACCION_ENVIAR_REPORTE_DIARIO = 'enviar_reporte_diario'

    ACCION_CHOICES = [
        (ACCION_LOGIN_EXITOSO, 'Inicio de sesión'),
        (ACCION_LOGIN_FALLIDO, 'Intento de inicio de sesión fallido'),
        (ACCION_CREAR_USUARIO, 'Creación de usuario'),
        (ACCION_EDITAR_USUARIO, 'Edición de usuario'),
        (ACCION_CAMBIAR_ESTADO_USUARIO, 'Cambio de estado de usuario (suspensión/reactivación)'),
        (ACCION_EDITAR_COMISION, 'Cambio de comisión de un usuario'),
        (ACCION_CREAR_ESTUDIO, 'Creación de estudio'),
        (ACCION_EDITAR_ESTUDIO, 'Edición de estudio'),
        (ACCION_SOLICITAR_CITA, 'Solicitud de cita'),
        (ACCION_CONFIRMAR_CITA, 'Confirmación de cita'),
        (ACCION_RECHAZAR_CITA, 'Rechazo de solicitud de cita'),
        (ACCION_REAGENDAR_CITA, 'Reagenda de cita'),
        (ACCION_MARCAR_LLEGADA, 'Llegada de paciente'),
        (ACCION_MARCAR_AUSENTE, 'Ausencia de paciente'),
        (ACCION_GENERAR_ORDEN, 'Generación de orden de trabajo'),
        (ACCION_ADJUNTAR_IMAGENES, 'Carga de imágenes de estudio'),
        (ACCION_SELECCIONAR_IMAGENES, 'Selección de imágenes del estudio'),
        (ACCION_ADJUNTAR_INFORME, 'Carga de informe'),
        (ACCION_ENVIAR_ESTUDIO, 'Envío de estudio al paciente'),
        (ACCION_REGISTRAR_TICKET, 'Registro de ticket de emergencia'),
        (ACCION_PROCESAR_TICKET, 'Procesamiento de ticket (genera orden de trabajo)'),
        (ACCION_ENVIAR_REPORTE_DIARIO, 'Envío de reporte diario'),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='eventos_bitacora',
    )
    username_intento = models.CharField(max_length=150, blank=True)
    accion = models.CharField(max_length=30, choices=ACCION_CHOICES)
    descripcion = models.TextField(blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'bitacora'
        verbose_name = 'evento de bitácora'
        verbose_name_plural = 'bitácora'
        ordering = ['-creado_en']

    def __str__(self):
        quien = self.usuario or self.username_intento or 'anónimo'
        return f'{quien} - {self.get_accion_display()} - {self.creado_en:%Y-%m-%d %H:%M}'

    @classmethod
    def registrar(cls, *, accion, descripcion='', usuario=None, username_intento='', request=None):
        ip = request.META.get('REMOTE_ADDR') if request is not None else None
        cls.objects.create(
            usuario=usuario,
            username_intento=username_intento,
            accion=accion,
            descripcion=descripcion,
            ip=ip,
        )


class HistorialComision(models.Model):
    """Auditoría de los cambios de % de comisión de un usuario (técnico,
    radiólogo, médico remitente): guarda el valor anterior y el nuevo de
    cada campo modificado, con la fecha y el administrador que lo hizo."""

    CAMPOS_COMISION = ('porcentaje_coex', 'porcentaje_privado', 'porcentaje_emergencia_igss')

    ETIQUETAS_CAMPOS = {
        'porcentaje_coex': 'COEX',
        'porcentaje_privado': 'Privado',
        'porcentaje_emergencia_igss': 'Emergencia IGSS',
    }

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='historial_comisiones',
    )
    campo = models.CharField(max_length=30, choices=[(c, c) for c in CAMPOS_COMISION])
    valor_anterior = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    valor_nuevo = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    modificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='cambios_comision_realizados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'historial_comisiones'
        verbose_name = 'cambio de comisión'
        verbose_name_plural = 'historial de comisiones'
        ordering = ['-creado_en']

    def __str__(self):
        etiqueta = self.ETIQUETAS_CAMPOS.get(self.campo, self.campo)
        return (
            f'{self.usuario} · {etiqueta}: {self.valor_anterior}% -> '
            f'{self.valor_nuevo}% ({self.modificado_por})'
        )

    @property
    def campo_etiqueta(self):
        return self.ETIQUETAS_CAMPOS.get(self.campo, self.campo)

from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models


class Usuario(AbstractUser):
    # Compatibilidad con registros históricos; ya no se ofrece ni se crea este rol.
    ROL_ADMINISTRADOR_FINANCIERO = 'administrador_financiero'
    ROL_ADMINISTRADOR = 'administrador'
    ROL_RECEPCIONISTA = 'recepcionista'
    ROL_CAJA = 'caja'
    ROL_TECNICO_IMAGENES = 'tecnico_imagenes'
    ROL_MEDICO_RADIOLOGO = 'medico_radiologo'
    ROL_MEDICO_REMITENTE = 'medico_remitente'

    ROL_CHOICES = [
        (ROL_ADMINISTRADOR, 'Administrador'),
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
    puede_operar_caja = models.BooleanField(
        default=False,
        verbose_name='puede operar Caja',
        help_text='Permite consultar y registrar pagos de estudios.',
    )

    # Salario fijo mensual del empleado, antes de comisiones. Se usa en la
    # pantalla de Planilla (salario base + comisiones del período = total).
    salario_base = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name='salario base mensual',
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
    ACCION_ADELANTAR_TICKET = 'adelantar_ticket'
    ACCION_REORDENAR_TICKET = 'reordenar_ticket'
    ACCION_AVANZAR_TURNO = 'avanzar_turno'
    ACCION_ENVIAR_REPORTE_DIARIO = 'enviar_reporte_diario'
    ACCION_REGISTRAR_PAGO_PLANILLA = 'registrar_pago_planilla'
    ACCION_CREAR_COMBO = 'crear_combo'
    ACCION_EDITAR_COMBO = 'editar_combo'
    ACCION_MARCAR_COBRADO = 'marcar_cobrado'

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
        (ACCION_REGISTRAR_TICKET, 'Registro de ticket / turno'),
        (ACCION_PROCESAR_TICKET, 'Procesamiento de ticket (genera orden de trabajo)'),
        (ACCION_ADELANTAR_TICKET, 'Adelantó un turno en la fila de espera'),
        (ACCION_REORDENAR_TICKET, 'Reordenó un turno en la fila de espera'),
        (ACCION_AVANZAR_TURNO, 'Avanzó la pantalla de turnos (siguiente)'),
        (ACCION_ENVIAR_REPORTE_DIARIO, 'Envío de reporte diario'),
        (ACCION_REGISTRAR_PAGO_PLANILLA, 'Registro de pago de planilla'),
        (ACCION_CREAR_COMBO, 'Creación de combo de estudios'),
        (ACCION_EDITAR_COMBO, 'Edición de combo de estudios'),
        (ACCION_MARCAR_COBRADO, 'Marcar estudio como cobrado'),
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


MESES_ES = [
    '', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
    'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]


class PagoPlanilla(models.Model):
    """Pago de planilla a un empleado por un mes: el monto pagado (con la
    foto de la boleta / transferencia como comprobante) y quién lo registró.
    Un solo pago por (empleado, mes)."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pagos_planilla',
    )
    anio = models.PositiveIntegerField(verbose_name='año')
    mes = models.PositiveSmallIntegerField()
    salario_base = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    comisiones = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    comprobante = models.FileField(
        upload_to='comprobantes_planilla/%Y/%m/',
        verbose_name='comprobante (boleta o transferencia)',
    )
    numero_boleta = models.CharField(
        max_length=60, blank=True, verbose_name='número de boleta / referencia',
    )
    verificado = models.BooleanField(
        default=False,
        help_text='El OCR del comprobante confirmó el monto (y el número de boleta, si se indicó).',
    )
    verificacion_nota = models.CharField(max_length=255, blank=True)
    notas = models.CharField(max_length=255, blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='pagos_planilla_registrados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pagos_planilla'
        verbose_name = 'pago de planilla'
        verbose_name_plural = 'pagos de planilla'
        unique_together = ('usuario', 'anio', 'mes')
        ordering = ['-anio', '-mes']

    def __str__(self):
        return f'{self.usuario} · {self.periodo_etiqueta} · Q{self.total}'

    @property
    def periodo_etiqueta(self):
        mes = self.mes if 1 <= self.mes <= 12 else 0
        return f'{MESES_ES[mes]} {self.anio}'.strip()


class LineaComisionLiquidada(models.Model):
    """Puente que recuerda qué comisiones (persona + cita + rol) cubrió un
    PagoPlanilla.

    Las comisiones se calculan al vuelo a partir de las citas procesadas; sin
    esto, si una cita se reprocesa o un mes ya pagado vuelve a recalcularse,
    el empleado cobraría dos veces la misma comisión. Al registrar un pago se
    guarda una línea por cada comisión liquidada y, al recalcular la planilla,
    se descuenta todo lo ya liquidado (solo se muestra el delta no pagado).

    La unicidad (usuario, cita, rol) es global y a prueba de re-procesos: una
    misma comisión solo se puede pagar una vez en la vida del sistema.
    """

    rol_tecnico = 'tecnico'
    rol_radiologo = 'radiologo'

    ROL_EN_CITA_CHOICES = [
        (rol_tecnico, 'Técnico'),
        (rol_radiologo, 'Radiólogo'),
    ]

    pago = models.ForeignKey(
        PagoPlanilla, on_delete=models.CASCADE, related_name='lineas',
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='lineas_comision_liquidadas',
    )
    cita = models.ForeignKey(
        'pacientes.Cita', on_delete=models.PROTECT,
        related_name='lineas_comision_liquidadas',
    )
    rol_en_cita = models.CharField(max_length=20, choices=ROL_EN_CITA_CHOICES)
    comision = models.DecimalField(max_digits=10, decimal_places=2)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'lineas_comision_liquidadas'
        verbose_name = 'línea de comisión liquidada'
        verbose_name_plural = 'líneas de comisión liquidadas'
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'cita', 'rol_en_cita'],
                name='uniq_linea_comision_liquidada',
            ),
        ]

    def __str__(self):
        return f'{self.usuario} · cita {self.cita_id} · {self.get_rol_en_cita_display()}'

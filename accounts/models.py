import calendar
import datetime
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models
from django.utils import timezone


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

    # Permiso adicional, independiente del rol principal (típicamente se
    # marca en una recepcionista): habilita la pantalla de Caja (pagos de
    # estudios) sin tener que cambiarle el rol. Portado (2026-09-04) desde
    # la rama visual-andres de TechBlood.
    puede_operar_caja = models.BooleanField(
        default=False,
        verbose_name='puede operar Caja',
        help_text='Permite consultar y registrar pagos de estudios.',
    )

    # Sala / consultorio donde atiende un radiólogo. Sale en la pantalla
    # pública de sala de espera ("PASE A ...") cuando se llama a un turno
    # asignado a ese radiólogo.
    sala = models.CharField(
        max_length=40, blank=True, verbose_name='sala / consultorio',
        help_text='Solo para radiólogos: la sala donde atiende (ej. "Sala 1").',
    )

    # Sesión única por usuario: guarda la session_key de la sesión activa
    # más reciente. SesionUnicaMiddleware compara esto contra la sesión de
    # cada request y cierra cualquier sesión vieja en cuanto se detecta un
    # login más nuevo desde otro equipo.
    sesion_activa = models.CharField(max_length=40, blank=True, default='')

    # Confirmación del correo al crear la cuenta (ver
    # accounts.views.crear_usuario / confirmar_correo_usuario): el usuario
    # queda con is_active=False hasta que entra al link que se le manda a
    # su correo, para asegurarnos de que esa casilla es real y suya. Si el
    # correo nunca le llega, un administrador puede activarlo a mano desde
    # "Usuarios activos" (cambiar_estado_usuario) sin depender de esto.
    token_confirmacion_correo = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    token_confirmacion_generado_en = models.DateTimeField(null=True, blank=True, editable=False)

    VIGENCIA_TOKEN_CONFIRMACION = datetime.timedelta(days=2)

    def generar_token_confirmacion_correo(self):
        self.token_confirmacion_correo = uuid.uuid4()
        self.token_confirmacion_generado_en = timezone.now()
        self.save(update_fields=['token_confirmacion_correo', 'token_confirmacion_generado_en'])
        return self.token_confirmacion_correo

    def token_confirmacion_vencido(self):
        if not self.token_confirmacion_generado_en:
            return True
        return timezone.now() - self.token_confirmacion_generado_en > self.VIGENCIA_TOKEN_CONFIRMACION

    def confirmar_correo(self):
        """Activa la cuenta y consume el token (de un solo uso)."""
        self.is_active = True
        self.token_confirmacion_correo = None
        self.token_confirmacion_generado_en = None
        self.save(update_fields=['is_active', 'token_confirmacion_correo', 'token_confirmacion_generado_en'])

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


def _ip_real_del_visitante(request):
    """IP del visitante para la bitácora.

    Cuando el sitio se accede vía el Cloudflare Tunnel, la conexión le
    llega a Django desde 'cloudflared' en esta misma máquina, así que
    REMOTE_ADDR siempre da 127.0.0.1 — la bitácora no capturaba la IP
    real de nadie que entrara por la web pública.

    Cloudflare agrega el header CF-Connecting-IP con la IP real del
    cliente en cada request que pasa por su borde (no se puede
    falsificar: Cloudflare lo sobreescribe, ignora el que mande el
    visitante). Si no viene (acceso directo por LAN sin pasar por el
    túnel), se sigue usando REMOTE_ADDR como antes.
    """
    return request.META.get('HTTP_CF_CONNECTING_IP') or request.META.get('REMOTE_ADDR')


class Bitacora(models.Model):
    ACCION_LOGIN_EXITOSO = 'login_exitoso'
    ACCION_LOGIN_FALLIDO = 'login_fallido'
    ACCION_CREAR_USUARIO = 'crear_usuario'
    ACCION_CONFIRMAR_CORREO_USUARIO = 'confirmar_correo_usuario'
    ACCION_EDITAR_USUARIO = 'editar_usuario'
    ACCION_CAMBIAR_ESTADO_USUARIO = 'cambiar_estado_usuario'
    ACCION_EDITAR_COMISION = 'editar_comision'
    ACCION_CREAR_ESTUDIO = 'crear_estudio'
    ACCION_EDITAR_ESTUDIO = 'editar_estudio'
    ACCION_EDITAR_PRECIO_ESTUDIO = 'editar_precio_estudio'
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
    ACCION_AVANZAR_TURNO = 'avanzar_turno'
    ACCION_ENVIAR_REPORTE_DIARIO = 'enviar_reporte_diario'
    ACCION_REGISTRAR_PAGO_PLANILLA = 'registrar_pago_planilla'
    ACCION_CREAR_COMBO = 'crear_combo'
    ACCION_EDITAR_COMBO = 'editar_combo'
    ACCION_MARCAR_COBRADO = 'marcar_cobrado'
    ACCION_AGREGAR_ESTUDIO_EXTRA = 'agregar_estudio_extra'
    ACCION_VALIDAR_ESTUDIO = 'validar_estudio'
    ACCION_SOLICITAR_MODIFICACION = 'solicitar_modificacion'
    ACCION_CORREGIR_ESTUDIO = 'corregir_estudio'
    ACCION_ELIMINAR_CITA = 'eliminar_cita'
    ACCION_ELIMINAR_TURNO = 'eliminar_turno'
    ACCION_PROGRAMAR_CAMBIO_PRECIO = 'programar_cambio_precio'
    ACCION_CANCELAR_CAMBIO_PRECIO = 'cancelar_cambio_precio'

    ACCION_CHOICES = [
        (ACCION_LOGIN_EXITOSO, 'Inicio de sesión'),
        (ACCION_LOGIN_FALLIDO, 'Intento de inicio de sesión fallido'),
        (ACCION_CREAR_USUARIO, 'Creación de usuario'),
        (ACCION_CONFIRMAR_CORREO_USUARIO, 'Confirmación de correo de un usuario nuevo'),
        (ACCION_EDITAR_USUARIO, 'Edición de usuario'),
        (ACCION_CAMBIAR_ESTADO_USUARIO, 'Cambio de estado de usuario (suspensión/reactivación)'),
        (ACCION_EDITAR_COMISION, 'Cambio de comisión de un usuario'),
        (ACCION_CREAR_ESTUDIO, 'Creación de estudio'),
        (ACCION_EDITAR_ESTUDIO, 'Edición de estudio'),
        (ACCION_EDITAR_PRECIO_ESTUDIO, 'Cambio de precio de un estudio'),
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
        (ACCION_AVANZAR_TURNO, 'Avanzó la pantalla de turnos (siguiente)'),
        (ACCION_ENVIAR_REPORTE_DIARIO, 'Envío de reporte diario'),
        (ACCION_REGISTRAR_PAGO_PLANILLA, 'Registro de pago de planilla'),
        (ACCION_CREAR_COMBO, 'Creación de combo de estudios'),
        (ACCION_EDITAR_COMBO, 'Edición de combo de estudios'),
        (ACCION_MARCAR_COBRADO, 'Marcar estudio como cobrado'),
        (ACCION_AGREGAR_ESTUDIO_EXTRA, 'Agregó un estudio extra a una cita'),
        (ACCION_VALIDAR_ESTUDIO, 'El técnico confirmó que el estudio es correcto'),
        (ACCION_SOLICITAR_MODIFICACION, 'El técnico pidió modificar el estudio'),
        (ACCION_CORREGIR_ESTUDIO, 'Recepción modificó el estudio de una cita'),
        (ACCION_ELIMINAR_CITA, 'Eliminación de una cita del calendario'),
        (ACCION_ELIMINAR_TURNO, 'Eliminación de un turno de la fila de espera'),
        (ACCION_PROGRAMAR_CAMBIO_PRECIO, 'Programó un cambio de estudio (nombre, modalidad, duración o precio)'),
        (ACCION_CANCELAR_CAMBIO_PRECIO, 'Canceló un cambio de estudio programado'),
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
        ip = _ip_real_del_visitante(request) if request is not None else None
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


def etiqueta_mes(anio, mes):
    mes = mes if 1 <= (mes or 0) <= 12 else 0
    return f'{MESES_ES[mes]} {anio}'.strip()


class _PagoBase(models.Model):
    """Campos comunes de un pago de planilla (salario o comisiones): el monto,
    la foto de la boleta / transferencia como comprobante, la verificación por
    OCR y quién lo registró."""

    monto = models.DecimalField(max_digits=10, decimal_places=2, default=0)
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
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PagoSalario(_PagoBase):
    """Pago del salario base de un empleado por un mes (un solo depósito a fin
    de mes). Un pago por (empleado, mes)."""

    TIPO = 'salario'

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pagos_salario',
    )
    anio = models.PositiveIntegerField(verbose_name='año')
    mes = models.PositiveSmallIntegerField()

    class Meta:
        db_table = 'pagos_salario'
        verbose_name = 'pago de salario'
        verbose_name_plural = 'pagos de salario'
        unique_together = ('usuario', 'anio', 'mes')
        ordering = ['-anio', '-mes']

    def __str__(self):
        return f'Salario · {self.usuario} · {self.periodo_etiqueta} · Q{self.monto}'

    @property
    def periodo_etiqueta(self):
        return etiqueta_mes(self.anio, self.mes)

    @property
    def desde(self):
        return datetime.date(self.anio, self.mes, 1)

    @property
    def hasta(self):
        return datetime.date(self.anio, self.mes, calendar.monthrange(self.anio, self.mes)[1])


class PagoComision(_PagoBase):
    """Pago de las comisiones de un empleado por un período (rango de fechas
    libre: puede ser una semana, una quincena, un mes o cualquier rango).

    Qué comisiones cubre no se deduce del rango: se guardan una por una en
    `PagoComisionLinea`, así una comisión ganada un día que ya se pagó a
    medias (más estudios después del pago) queda pendiente para el próximo
    pago aunque el rango se cruce."""

    TIPO = 'comision'

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pagos_comision',
    )
    desde = models.DateField()
    hasta = models.DateField(help_text='Último día del período, incluido.')

    class Meta:
        db_table = 'pagos_comision'
        verbose_name = 'pago de comisiones'
        verbose_name_plural = 'pagos de comisiones'
        ordering = ['-hasta', '-desde']

    def __str__(self):
        return f'Comisiones · {self.usuario} · {self.periodo_etiqueta} · Q{self.monto}'

    @property
    def periodo_etiqueta(self):
        return f'{self.desde:%d/%m/%Y} – {self.hasta:%d/%m/%Y}'


class PagoComisionLinea(models.Model):
    """Una comisión concreta (una cita, un rol) cubierta por un PagoComision.
    El `unique_together (cita, rol_en_cita)` garantiza que cada comisión se
    pague una sola vez."""

    ROL_TECNICO = 'Técnico'
    ROL_RADIOLOGO = 'Radiólogo'

    pago = models.ForeignKey(PagoComision, on_delete=models.CASCADE, related_name='lineas')
    cita = models.ForeignKey('pacientes.Cita', on_delete=models.PROTECT, related_name='+')
    rol_en_cita = models.CharField(max_length=20)
    monto = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        db_table = 'pagos_comision_lineas'
        unique_together = ('cita', 'rol_en_cita')

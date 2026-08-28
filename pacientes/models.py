import datetime
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

MINUTOS_TOLERANCIA_LLEGADA = 15

# A partir de esta hora, las citas de convenio privado y de emergencia IGSS
# cobran tarifa "inhábil" (ver PrecioEstudio y Cita.horario_habil). COEX
# siempre se factura en tarifa hábil.
HORA_INICIO_TARIFA_INHABIL = datetime.time(18, 0)
CONVENIOS_CON_TARIFA_INHABIL = ('privado', 'emergencia_igss')

CONVENIO_COEX = 'coex'
CONVENIO_PRIVADO = 'privado'
CONVENIO_EMERGENCIA_IGSS = 'emergencia_igss'

CONVENIO_CHOICES = [
    (CONVENIO_COEX, 'COEX'),
    (CONVENIO_PRIVADO, 'Privado'),
    (CONVENIO_EMERGENCIA_IGSS, 'Emergencia IGSS'),
]


def es_horario_habil(convenio, hora):
    """¿La cita de este convenio a esta hora se factura en tarifa hábil?"""
    if convenio in CONVENIOS_CON_TARIFA_INHABIL and hora >= HORA_INICIO_TARIFA_INHABIL:
        return False
    return True


class Paciente(models.Model):
    SEXO_MASCULINO = 'M'
    SEXO_FEMENINO = 'F'

    SEXO_CHOICES = [
        (SEXO_MASCULINO, 'Masculino'),
        (SEXO_FEMENINO, 'Femenino'),
    ]

    dpi = models.CharField(max_length=20, unique=True, verbose_name='DPI')
    carnet_igss = models.CharField(
        max_length=20, unique=True, null=True, blank=True,
        verbose_name='carné de afiliación IGSS',
        help_text='Obligatorio para citas por COEX o Emergencia IGSS.',
    )
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    sexo = models.CharField(max_length=1, choices=SEXO_CHOICES, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    correo = models.EmailField(max_length=254, blank=True, null=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)

    # Campos que se pueden dejar sin llenar al registrar al paciente (ej. en
    # una emergencia) y que luego se le avisan pendientes a recepción. Ver
    # accounts.management.commands.notificar_pacientes_pendientes.
    CAMPOS_OPCIONALES = ('sexo', 'fecha_nacimiento', 'telefono')
    ETIQUETAS_CAMPOS_OPCIONALES = {
        'sexo': 'Sexo',
        'fecha_nacimiento': 'Fecha de nacimiento',
        'telefono': 'Teléfono',
    }

    class Meta:
        db_table = 'pacientes'
        verbose_name = 'paciente'
        verbose_name_plural = 'pacientes'

    def __str__(self):
        return f'{self.nombre} {self.apellido} ({self.dpi})'

    def campos_pendientes(self):
        """Nombres legibles de los campos opcionales que todavía no se
        llenaron para este paciente."""
        return [
            etiqueta for campo, etiqueta in self.ETIQUETAS_CAMPOS_OPCIONALES.items()
            if not getattr(self, campo)
        ]

    def edad_en(self, fecha):
        if not self.fecha_nacimiento:
            return None
        años = fecha.year - self.fecha_nacimiento.year
        if (fecha.month, fecha.day) < (self.fecha_nacimiento.month, self.fecha_nacimiento.day):
            años -= 1
        return años


class TipoEstudio(models.Model):
    MODALIDAD_RX = 'rx'
    MODALIDAD_RX_CONTRASTE = 'rx_contraste'
    MODALIDAD_TAC = 'tac'
    MODALIDAD_USG = 'usg'
    MODALIDAD_MAMO_DENSIT = 'mamo_densit'

    MODALIDAD_CHOICES = [
        (MODALIDAD_RX, 'Rayos X'),
        (MODALIDAD_RX_CONTRASTE, 'Rayos X con contraste / fluoroscopía'),
        (MODALIDAD_TAC, 'Tomografía (TAC)'),
        (MODALIDAD_USG, 'Ultrasonido / Doppler'),
        (MODALIDAD_MAMO_DENSIT, 'Mamografía / Densitometría'),
    ]

    nombre = models.CharField(max_length=120, unique=True)
    modalidad = models.CharField(
        max_length=20, choices=MODALIDAD_CHOICES, default=MODALIDAD_RX,
        help_text='Agrupa el estudio por equipo/sala y define qué técnico y radiólogo pueden atenderlo.',
    )
    duracion_minutos = models.PositiveIntegerField(
        default=30,
        verbose_name='duración (minutos)',
        help_text='Cuánto tiempo ocupa este estudio en el calendario de citas.',
    )
    activo = models.BooleanField(default=True)
    radiologos = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name='tipos_estudio_asignados',
        limit_choices_to={'rol': 'medico_radiologo'},
        verbose_name='radiólogos que realizan este estudio',
        help_text='Al agendar una cita de este estudio, solo se podrá asignar a estos radiólogos.',
    )

    class Meta:
        db_table = 'tipos_estudio'
        verbose_name = 'tipo de estudio'
        verbose_name_plural = 'tipos de estudio'

    def __str__(self):
        return self.nombre

    def precio_para(self, convenio, horario_habil=True):
        """Precio de este estudio para un convenio y tipo de horario.
        Si no hay tarifa inhábil cargada, cae a la hábil; si no hay ninguna,
        devuelve 0."""
        precios = {(p.convenio, p.horario_habil): p.precio for p in self.precios.all()}
        return (
            precios.get((convenio, horario_habil))
            or precios.get((convenio, True))
            or Decimal('0.00')
        )

    @property
    def precio_referencia(self):
        """Precio orientativo para listados: privado en horario hábil."""
        return self.precio_para('privado', True)


class PrecioEstudio(models.Model):
    """Una celda de la matriz de precios: cuánto cuesta un estudio para un
    convenio dado, en horario hábil o inhábil."""

    HORARIO_CHOICES = [
        (True, 'Hábil'),
        (False, 'Inhábil (después de las 18:00 en privado y emergencia)'),
    ]

    tipo_estudio = models.ForeignKey(
        TipoEstudio, on_delete=models.CASCADE, related_name='precios',
    )
    convenio = models.CharField(max_length=20, choices=CONVENIO_CHOICES)
    horario_habil = models.BooleanField(default=True, verbose_name='horario', choices=HORARIO_CHOICES)
    precio = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    class Meta:
        db_table = 'precios_estudio'
        verbose_name = 'precio de estudio'
        verbose_name_plural = 'precios de estudio'
        unique_together = ('tipo_estudio', 'convenio', 'horario_habil')
        ordering = ['tipo_estudio', 'convenio', '-horario_habil']

    def __str__(self):
        horario = 'hábil' if self.horario_habil else 'inhábil'
        return f'{self.tipo_estudio.nombre} · {self.get_convenio_display()} {horario}: Q{self.precio}'


class Cita(models.Model):
    # Los valores viven a nivel de módulo (los usa también PrecioEstudio, que
    # se define antes que Cita); acá se reexponen para no romper el código
    # que ya usa Cita.CONVENIO_*.
    CONVENIO_COEX = CONVENIO_COEX
    CONVENIO_PRIVADO = CONVENIO_PRIVADO
    CONVENIO_EMERGENCIA_IGSS = CONVENIO_EMERGENCIA_IGSS
    CONVENIO_CHOICES = CONVENIO_CHOICES

    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_AGENDADA = 'agendada'
    ESTADO_EN_ESPERA = 'en_espera'
    ESTADO_EN_PROCESO = 'en_proceso'
    ESTADO_PROCESADA = 'procesada'
    ESTADO_AUSENTE = 'ausente'
    ESTADO_RECHAZADA = 'rechazada'

    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, 'Pendiente de confirmación'),
        (ESTADO_AGENDADA, 'Agendada'),
        (ESTADO_EN_ESPERA, 'En espera'),
        (ESTADO_EN_PROCESO, 'En proceso'),
        (ESTADO_PROCESADA, 'Procesada'),
        (ESTADO_AUSENTE, 'Ausente'),
        (ESTADO_RECHAZADA, 'Rechazada'),
    ]

    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, related_name='citas')
    tipo_estudio = models.ForeignKey(TipoEstudio, on_delete=models.PROTECT, related_name='citas')
    radiologo = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='citas_asignadas',
    )
    convenio = models.CharField(max_length=20, choices=CONVENIO_CHOICES)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    fecha = models.DateField()
    hora = models.TimeField()
    medico_referente = models.CharField(
        max_length=150, blank=True,
        verbose_name='médico referente',
        help_text='Nombre del médico externo que refiere al paciente (para el reporte diario).',
    )
    fecha_sugerida = models.DateField(null=True, blank=True)
    hora_sugerida = models.TimeField(null=True, blank=True)
    hora_llegada = models.DateTimeField(null=True, blank=True)
    notas = models.TextField(blank=True)
    es_emergencia_forzada = models.BooleanField(
        default=False,
        verbose_name='agendada como emergencia',
        help_text=(
            'La recepcionista confirmó que agendó esta cita a propósito en un '
            'horario ya ocupado, por tratarse de una emergencia.'
        ),
    )
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='citas_creadas'
    )
    creada_en = models.DateTimeField(auto_now_add=True)
    revisada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='citas_revisadas',
    )
    revisada_en = models.DateTimeField(null=True, blank=True)
    motivo_rechazo = models.TextField(blank=True)

    class Meta:
        db_table = 'citas'
        verbose_name = 'cita'
        verbose_name_plural = 'citas'
        ordering = ['fecha', 'hora']

    def __str__(self):
        return f'{self.paciente} - {self.fecha} {self.hora}'

    @property
    def esta_tarde(self):
        if self.estado != self.ESTADO_AGENDADA or self.hora_llegada:
            return False
        hora_cita = timezone.make_aware(datetime.datetime.combine(self.fecha, self.hora))
        limite = hora_cita + datetime.timedelta(minutes=MINUTOS_TOLERANCIA_LLEGADA)
        return timezone.now() > limite

    @classmethod
    def marcar_ausentes_vencidas(cls):
        """Pasa a AUSENTE toda cita AGENDADA cuyo día ya pasó, o que es de hoy
        pero ya son las 18:00 y nadie la marcó ausente/llegada."""
        ahora = timezone.localtime()
        hoy = ahora.date()
        fecha_limite = hoy if ahora.time() >= datetime.time(18, 0) else hoy - datetime.timedelta(days=1)
        return cls.objects.filter(
            estado=cls.ESTADO_AGENDADA, fecha__lte=fecha_limite
        ).update(estado=cls.ESTADO_AUSENTE)

    @property
    def tecnico_asignado(self):
        """Técnico que subió las imágenes de este estudio, para el reporte
        diario. Vacío si el estudio todavía no se procesó."""
        orden = getattr(self, 'orden_trabajo', None)
        if not orden:
            return None
        imagen = orden.imagenes.first()
        return imagen.subida_por if imagen else None

    @property
    def cuenta_en_total_reporte(self):
        """Las citas marcadas como ausente no generaron ingreso: se listan en
        el reporte diario pero no suman al total del día."""
        return self.estado != self.ESTADO_AUSENTE

    @property
    def horario_habil(self):
        """True si esta cita se factura en tarifa hábil (ver es_horario_habil)."""
        return es_horario_habil(self.convenio, self.hora)

    @property
    def precio(self):
        """Precio de la cita según su estudio, convenio y horario."""
        return self.tipo_estudio.precio_para(self.convenio, self.horario_habil)


class ReporteDiario(models.Model):
    """Un reporte por convenio y fecha. Se crea automáticamente (en estado
    borrador) la primera vez que se confirma una cita de ese convenio para
    esa fecha (ver revisar_solicitud). Las citas que contiene no se guardan
    aquí: se calculan en el momento a partir de Cita(convenio, fecha), así
    nunca quedan desactualizadas si una cita se reagenda o se marca ausente."""

    ESTADO_BORRADOR = 'borrador'
    ESTADO_ENVIADO = 'enviado'

    ESTADO_CHOICES = [
        (ESTADO_BORRADOR, 'Borrador'),
        (ESTADO_ENVIADO, 'Enviado'),
    ]

    fecha = models.DateField()
    convenio = models.CharField(max_length=20, choices=Cita.CONVENIO_CHOICES)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=ESTADO_BORRADOR)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='reportes_diarios_enviados',
    )
    enviado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'reportes_diarios'
        verbose_name = 'reporte diario'
        verbose_name_plural = 'reportes diarios'
        unique_together = ('fecha', 'convenio')
        ordering = ['-fecha']

    def __str__(self):
        return f'Reporte {self.get_convenio_display()} - {self.fecha}'

    def citas(self):
        return (
            Cita.objects.filter(convenio=self.convenio, fecha=self.fecha)
            .exclude(estado__in=(Cita.ESTADO_PENDIENTE, Cita.ESTADO_RECHAZADA))
            .select_related('paciente', 'tipo_estudio', 'radiologo')
            .prefetch_related('tipo_estudio__precios')
            .order_by('hora')
        )

    def total(self):
        return sum(
            (cita.precio for cita in self.citas() if cita.cuenta_en_total_reporte),
            start=Decimal('0.00'),
        )


class OrdenTrabajo(models.Model):
    cita = models.OneToOneField(Cita, on_delete=models.PROTECT, related_name='orden_trabajo')
    motivo = models.TextField(verbose_name='motivo / indicación clínica')
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ordenes_trabajo_creadas'
    )
    creada_en = models.DateTimeField(auto_now_add=True)

    informe_texto = models.TextField(blank=True, verbose_name='informe (texto)')
    informe_archivo = models.FileField(
        upload_to='informes/%Y/%m/', blank=True, null=True, verbose_name='informe (archivo)'
    )
    informe_creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='informes_creados',
    )
    informe_creado_en = models.DateTimeField(null=True, blank=True)

    # El envío de resultados al paciente ya no ocurre automáticamente cuando
    # la radióloga adjunta el informe: ahora lo dispara la recepcionista
    # manualmente desde "Estudios realizados" (botón "Enviar estudio").
    # Este campo queda null hasta que efectivamente se envía.
    resultados_enviados_en = models.DateTimeField(null=True, blank=True)

    @property
    def tiene_informe(self):
        return bool(self.informe_texto or self.informe_archivo)

    @property
    def tiene_imagenes(self):
        return self.imagenes.exists()

    class Meta:
        db_table = 'ordenes_trabajo'
        verbose_name = 'orden de trabajo'
        verbose_name_plural = 'órdenes de trabajo'
        ordering = ['creada_en']

    def __str__(self):
        return f'Orden #{self.id} - {self.cita.paciente}'

    @property
    def edad_paciente(self):
        return self.cita.paciente.edad_en(self.cita.fecha)


class ImagenEstudio(models.Model):
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name='imagenes')
    archivo = models.FileField(upload_to='imagenes_estudio/%Y/%m/')
    # Cuando el técnico sube un DICOM, "archivo" queda con el JPG ya
    # convertido (para poder mostrarlo en el navegador) y acá se conserva el
    # .dcm original tal cual se subió, para que la radióloga pueda
    # descargarlo. Queda vacío si lo que se subió ya era JPG/PNG.
    archivo_original = models.FileField(
        upload_to='imagenes_estudio/dicom_original/%Y/%m/', null=True, blank=True,
    )
    subida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='imagenes_subidas'
    )
    subida_en = models.DateTimeField(auto_now_add=True)
    # La radióloga cura la galería (ver_imagenes_jpg): las que deja
    # marcadas son las que se siguen mostrando y las que se adjuntan en el
    # correo al paciente. Al descartar una, se le borra el JPG (queda
    # seleccionada=False y "archivo" vacío) pero "archivo_original" (el
    # DICOM) nunca se toca — se conserva completo pase lo que pase.
    seleccionada = models.BooleanField(default=True)

    class Meta:
        db_table = 'imagenes_estudio'
        verbose_name = 'imagen de estudio'
        verbose_name_plural = 'imágenes de estudio'
        ordering = ['subida_en']

    def __str__(self):
        return f'Imagen #{self.id} - Orden #{self.orden_id}'


class Ticket(models.Model):
    """Turno de la fila de recepción para pacientes que llegan sin cita
    agendada (walk-in). Por ahora solo se usa desde la pantalla de
    Emergencia IGSS, pero el campo `servicio` queda abierto para reusar
    este mismo sistema de turnos en COEX/Privado más adelante."""

    SERVICIO_COEX = 'coex'
    SERVICIO_PRIVADO = 'privado'
    SERVICIO_EMERGENCIA_IGSS = 'emergencia_igss'

    SERVICIO_CHOICES = [
        (SERVICIO_COEX, 'COEX'),
        (SERVICIO_PRIVADO, 'Privado'),
        (SERVICIO_EMERGENCIA_IGSS, 'Emergencia IGSS'),
    ]

    PREFIJO_TURNO = {
        SERVICIO_COEX: 'COEX',
        SERVICIO_PRIVADO: 'PRIV',
        SERVICIO_EMERGENCIA_IGSS: 'EMER',
    }

    PRIORIDAD_NORMAL = 1
    PRIORIDAD_URGENTE = 2
    PRIORIDAD_CRITICA = 3

    PRIORIDAD_CHOICES = [
        (PRIORIDAD_NORMAL, 'Normal'),
        (PRIORIDAD_URGENTE, 'Urgente'),
        (PRIORIDAD_CRITICA, 'Crítica'),
    ]

    ESTADO_EN_ESPERA = 'en_espera'
    ESTADO_EN_ATENCION = 'en_atencion'
    ESTADO_ATENDIDO = 'atendido'
    ESTADO_AUSENTE = 'ausente'

    ESTADO_CHOICES = [
        (ESTADO_EN_ESPERA, 'En espera'),
        (ESTADO_EN_ATENCION, 'En atención'),
        (ESTADO_ATENDIDO, 'Atendido'),
        (ESTADO_AUSENTE, 'Ausente'),
    ]

    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, related_name='tickets')
    cita = models.ForeignKey(
        'Cita', on_delete=models.SET_NULL, null=True, blank=True, related_name='ticket_origen',
        help_text='Cita/orden de trabajo generada al procesar este ticket (si ya se procesó).',
    )
    servicio = models.CharField(max_length=20, choices=SERVICIO_CHOICES)
    prioridad = models.PositiveSmallIntegerField(choices=PRIORIDAD_CHOICES, default=PRIORIDAD_NORMAL)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=ESTADO_EN_ESPERA)
    numero = models.PositiveIntegerField(editable=False, default=0)
    turno = models.CharField(max_length=20, editable=False, blank=True)
    motivo = models.CharField(max_length=255, blank=True, verbose_name='motivo de la visita')
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='tickets_registrados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    atendido_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'tickets'
        verbose_name = 'ticket'
        verbose_name_plural = 'tickets'
        ordering = ['-prioridad', 'creado_en']

    def __str__(self):
        return f'{self.turno} - {self.paciente}'

    def save(self, *args, **kwargs):
        if self.turno:
            super().save(*args, **kwargs)
            return

        fecha = timezone.localdate()
        with transaction.atomic():
            # DailySequence garantiza un solo contador por (servicio, fecha),
            # incluso si dos recepcionistas registran un ticket al mismo tiempo.
            secuencia, _ = DailySequence.objects.select_for_update().get_or_create(
                servicio=self.servicio, fecha=fecha,
            )
            secuencia.ultimo += 1
            secuencia.save(update_fields=['ultimo'])
            self.numero = secuencia.ultimo
            self.turno = f'{self.PREFIJO_TURNO.get(self.servicio, self.servicio.upper())}-{self.numero:03d}'
            super().save(*args, **kwargs)


class Notificacion(models.Model):
    """Aviso interno para un usuario (con sonido en el navegador) cuando el
    flujo de trabajo le asigna algo nuevo: una cita, una orden, un estudio
    listo para informar, o un informe ya terminado."""

    TIPO_CITA_ASIGNADA = 'cita_asignada'
    TIPO_CITA_CONFIRMADA = 'cita_confirmada'
    TIPO_CITA_RECHAZADA = 'cita_rechazada'
    TIPO_ORDEN_PENDIENTE = 'orden_pendiente'
    TIPO_ESTUDIO_LISTO_INFORMAR = 'estudio_listo_informar'
    TIPO_ESTUDIO_COMPLETADO = 'estudio_completado'
    TIPO_DATOS_PACIENTE_PENDIENTES = 'datos_paciente_pendientes'
    TIPO_REPORTE_ENVIADO = 'reporte_enviado'

    TIPO_CHOICES = [
        (TIPO_CITA_ASIGNADA, 'Nueva cita asignada'),
        (TIPO_CITA_CONFIRMADA, 'Cita confirmada'),
        (TIPO_CITA_RECHAZADA, 'Cita rechazada'),
        (TIPO_ORDEN_PENDIENTE, 'Nueva orden de trabajo pendiente'),
        (TIPO_ESTUDIO_LISTO_INFORMAR, 'Estudio listo para informar'),
        (TIPO_ESTUDIO_COMPLETADO, 'Estudio completado'),
        (TIPO_DATOS_PACIENTE_PENDIENTES, 'Datos de paciente pendientes de llenar'),
        (TIPO_REPORTE_ENVIADO, 'Reporte diario enviado'),
    ]

    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notificaciones',
    )
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    mensaje = models.CharField(max_length=255)
    cita = models.ForeignKey(
        Cita, on_delete=models.CASCADE, null=True, blank=True, related_name='notificaciones',
    )
    url = models.CharField(max_length=255, blank=True, verbose_name='enlace')
    leida = models.BooleanField(default=False)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notificaciones'
        verbose_name = 'notificación'
        verbose_name_plural = 'notificaciones'
        ordering = ['-creada_en']

    def __str__(self):
        return f'{self.destinatario} - {self.mensaje}'

    @classmethod
    def notificar(cls, *, destinatario, tipo, mensaje, cita=None, url=''):
        return cls.objects.create(
            destinatario=destinatario, tipo=tipo, mensaje=mensaje, cita=cita, url=url,
        )

    @classmethod
    def notificar_a_varios(cls, *, usuarios, tipo, mensaje, cita=None, url=''):
        usuarios = list(usuarios)
        if not usuarios:
            return []
        return cls.objects.bulk_create([
            cls(destinatario=usuario, tipo=tipo, mensaje=mensaje, cita=cita, url=url)
            for usuario in usuarios
        ])


class DailySequence(models.Model):
    """Contador diario por servicio para generar el número de turno de los
    tickets (ver Ticket.save). Una fila por (servicio, fecha)."""

    servicio = models.CharField(max_length=20)
    fecha = models.DateField()
    ultimo = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'secuencias_diarias_tickets'
        verbose_name = 'secuencia diaria de tickets'
        verbose_name_plural = 'secuencias diarias de tickets'
        unique_together = ('servicio', 'fecha')

    def __str__(self):
        return f'{self.servicio} {self.fecha} -> {self.ultimo}'

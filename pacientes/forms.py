import re

from django import forms
from django.utils import timezone

from accounts.models import Usuario
from clinica.validators import validar_dominio_correo

from .models import Cita, Combo, Paciente, TipoEstudio
from .models import Cobro

CONVENIOS_QUE_REQUIEREN_CARNET_IGSS = (Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS)

NOMBRE_REGEX = re.compile(r'^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+$')


class TipoEstudioSelect(forms.Select):
    """Select de tipo de estudio que agrega precio (hábil e inhábil) y
    duración como atributos data-* de cada <option>, para que el formulario
    los muestre en pantalla sin pedirlos de nuevo al servidor. Las opciones
    se agrupan en <optgroup> por modalidad (categoría) para facilitar la
    búsqueda."""

    detalles = {}
    # estudio_id (str) -> nombre de la modalidad/categoría a la que pertenece
    grupo_de = {}

    def optgroups(self, name, value, attrs=None):
        """Agrupa las opciones planas por modalidad usando <optgroup>."""
        if not isinstance(value, (list, tuple)):
            value = [value]
        groups = []
        has_selected = False

        flat = list(self.choices)
        agrupadas = {}
        orden = []
        for option_value, option_label in flat:
            if option_value is None:
                option_value = ""
            grupo = self.grupo_de.get(str(option_value)) if option_value else None
            if grupo is not None and grupo not in agrupadas:
                orden.append(grupo)
            agrupadas.setdefault(grupo, []).append((option_value, option_label))

        index = 0
        for grupo in [None] + [g for g in orden if g is not None]:
            subindex = None
            subgroup = []
            for option_value, option_label in agrupadas[grupo]:
                selected = (
                    not has_selected or self.allow_multiple_selected
                ) and str(option_value) in value
                has_selected |= selected
                subgroup.append(
                    self.create_option(
                        name, option_value, option_label, selected, index,
                        subindex=subindex, attrs=attrs,
                    )
                )
                index += 1
                if subindex is not None:
                    subindex += 1
            groups.append((grupo, subgroup, len(groups)))
        return groups

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        detalle = self.detalles.get(str(value)) if value else None
        if detalle:
            option['attrs']['data-precio-habil'] = str(detalle[0])
            option['attrs']['data-precio-inhabil'] = str(detalle[1])
            option['attrs']['data-duracion'] = str(detalle[2])
            # Ids de los radiólogos que realizan este estudio: el JS de
            # agendar_cita.html los usa para filtrar los estudios al elegir
            # radiólogo (y viceversa) sin volver a consultar al servidor.
            radiologos = detalle[3] if len(detalle) > 3 else ()
            if radiologos:
                option['attrs']['data-radiologos'] = ','.join(str(r) for r in radiologos)
        return option


def ids_radiologos_activos(te):
    """Ids de los radiólogos ACTIVOS que realizan un tipo de estudio.
    Usa la caché del prefetch_related('radiologos') para no disparar
    consultas extra, y coincide con lo que el campo 'radiologo' y el
    endpoint radiologos_por_estudio realmente dejan elegir (un radiólogo
    inactivo no puede quedar seleccionable en el lado del cliente)."""
    return [
        u.id for u in te.radiologos.all()
        if u.is_active and u.rol == Usuario.ROL_MEDICO_RADIOLOGO
    ]


def validar_fecha_nacimiento_no_futura(fecha):
    if fecha and fecha > timezone.localdate():
        raise forms.ValidationError('La fecha de nacimiento no puede ser una fecha futura.')


def limpiar_carnet_igss(carnet, *, dpi, requerido):
    """Valida el carné de afiliación IGSS: obligatorio según el convenio, y
    único entre pacientes (el mismo paciente, identificado por su DPI,
    puede conservar el suyo)."""
    carnet = (carnet or '').strip()
    if not carnet:
        if requerido:
            raise forms.ValidationError(
                'El carné de afiliación IGSS es obligatorio para COEX y Emergencia IGSS.'
            )
        return None
    duplicado = Paciente.objects.filter(carnet_igss=carnet).exclude(dpi=dpi).exists()
    if duplicado:
        raise forms.ValidationError('Ese carné de afiliación IGSS ya está registrado con otro paciente.')
    return carnet


class AgendarCitaForm(forms.Form):
    dpi = forms.CharField(
        label='DPI',
        max_length=13,
        min_length=13,
        widget=forms.TextInput(attrs={
            'maxlength': 13,
            'inputmode': 'numeric',
            'pattern': r'\d{13}',
            'title': 'El DPI debe tener exactamente 13 dígitos.',
        }),
    )
    nombre = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'pattern': r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+',
            'title': 'Solo letras y espacios.',
        }),
    )
    apellido = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'pattern': r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+',
            'title': 'Solo letras y espacios.',
        }),
    )
    sexo = forms.ChoiceField(
        choices=[('', '---------')] + list(Paciente.SEXO_CHOICES), required=False,
    )
    telefono = forms.CharField(max_length=20, required=False)
    correo = forms.EmailField(
        label='Correo electrónico',
        max_length=254,
        widget=forms.EmailInput(attrs={
            'placeholder': 'paciente@correo.com',
            'autocomplete': 'email',
        }),
    )
    fecha_nacimiento = forms.DateField(
        required=False, widget=forms.DateInput(attrs={'type': 'date'}),
    )
    carnet_igss = forms.CharField(
        label='Carné de afiliación IGSS',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'inputmode': 'numeric'}),
    )

    tipo_estudio = forms.ModelChoiceField(
        queryset=TipoEstudio.objects.filter(activo=True).order_by('nombre'),
        widget=TipoEstudioSelect(),
    )
    radiologo = forms.ModelChoiceField(
        label='Radiólogo asignado',
        queryset=Usuario.objects.filter(
            rol=Usuario.ROL_MEDICO_RADIOLOGO, is_active=True
        ).order_by('username'),
    )
    medico_referente = forms.CharField(
        label='Médico referente',
        max_length=150,
        required=False,
        help_text='Médico externo que refiere al paciente (aparece en el reporte diario).',
    )
    fecha = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    hora = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}))
    notas = forms.CharField(widget=forms.Textarea, required=False)
    es_emergencia = forms.BooleanField(
        label='Confirmo que es una cita de emergencia: debe agendarse en este horario aunque ya esté ocupado.',
        required=False,
    )

    def __init__(self, *args, convenio=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fecha_nacimiento'].widget.attrs['max'] = timezone.localdate().isoformat()
        self.fields['tipo_estudio'].queryset = (
            self.fields['tipo_estudio'].queryset.prefetch_related('precios', 'radiologos')
        )
        self.fields['tipo_estudio'].widget.detalles = {
            str(te.pk): (
                te.precio_para(convenio, True),
                te.precio_para(convenio, False),
                te.duracion_minutos,
                ids_radiologos_activos(te),
            )
            for te in self.fields['tipo_estudio'].queryset
        }
        self.fields['tipo_estudio'].widget.grupo_de = {
            str(te.pk): te.get_modalidad_display()
            for te in self.fields['tipo_estudio'].queryset
        }
        self.convenio = convenio
        if convenio in CONVENIOS_QUE_REQUIEREN_CARNET_IGSS:
            self.fields['carnet_igss'].widget.attrs['required'] = True

    def clean_dpi(self):
        dpi = self.cleaned_data['dpi'].strip()
        if not dpi.isdigit():
            raise forms.ValidationError('El DPI debe contener solo números.')
        if len(dpi) != 13:
            raise forms.ValidationError('El DPI debe tener exactamente 13 dígitos.')
        return dpi

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        if not NOMBRE_REGEX.match(nombre):
            raise forms.ValidationError('El nombre solo puede contener letras y espacios.')
        return nombre

    def clean_apellido(self):
        apellido = self.cleaned_data['apellido'].strip()
        if not NOMBRE_REGEX.match(apellido):
            raise forms.ValidationError('El apellido solo puede contener letras y espacios.')
        return apellido

    def clean_correo(self):
        correo = self.cleaned_data['correo'].strip().lower()
        validar_dominio_correo(correo)
        return correo

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data['fecha_nacimiento']
        validar_fecha_nacimiento_no_futura(fecha)
        return fecha

    def clean_carnet_igss(self):
        return limpiar_carnet_igss(
            self.cleaned_data.get('carnet_igss'),
            dpi=self.cleaned_data.get('dpi'),
            requerido=self.convenio in CONVENIOS_QUE_REQUIEREN_CARNET_IGSS,
        )

    def clean(self):
        cleaned = super().clean()
        tipo_estudio = cleaned.get('tipo_estudio')
        radiologo = cleaned.get('radiologo')
        if tipo_estudio and radiologo and not tipo_estudio.radiologos.filter(id=radiologo.id).exists():
            self.add_error(
                'radiologo',
                f'{radiologo.get_full_name() or radiologo.username} no realiza estudios de "{tipo_estudio}".',
            )
        return cleaned


class AgendarCitaPrivadoForm(forms.Form):
    """Agendamiento del módulo Privado. Más simple que AgendarCitaForm: sin
    carné IGSS, sin radiólogo (se asigna al confirmar la solicitud) y sin
    casilla de emergencia. La cita queda PENDIENTE para revisión del
    radiólogo."""

    dpi = forms.CharField(
        label='DPI',
        max_length=13,
        min_length=13,
        widget=forms.TextInput(attrs={
            'maxlength': 13,
            'inputmode': 'numeric',
            'pattern': r'\d{13}',
            'title': 'El DPI debe tener exactamente 13 dígitos.',
        }),
    )
    nombre = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'pattern': r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+',
            'title': 'Solo letras y espacios.',
        }),
    )
    apellido = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'pattern': r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+',
            'title': 'Solo letras y espacios.',
        }),
    )
    sexo = forms.ChoiceField(
        choices=[('', '---------')] + list(Paciente.SEXO_CHOICES), required=False,
    )
    telefono = forms.CharField(max_length=20, required=False)
    correo = forms.EmailField(
        label='Correo electrónico (opcional)',
        max_length=254,
        required=False,
        widget=forms.EmailInput(attrs={
            'placeholder': 'paciente@correo.com',
            'autocomplete': 'email',
        }),
    )
    fecha_nacimiento = forms.DateField(
        required=False, widget=forms.DateInput(attrs={'type': 'date'}),
    )
    tipo_estudio = forms.ModelChoiceField(
        queryset=TipoEstudio.objects.filter(activo=True).order_by('nombre'),
        widget=TipoEstudioSelect(),
    )
    fecha = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    hora = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}))
    motivo = forms.CharField(
        label='Motivo de la consulta',
        max_length=255,
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fecha_nacimiento'].widget.attrs['max'] = timezone.localdate().isoformat()
        queryset = self.fields['tipo_estudio'].queryset.prefetch_related('precios', 'radiologos')
        self.fields['tipo_estudio'].queryset = queryset
        self.fields['tipo_estudio'].widget.detalles = {
            str(te.pk): (
                te.precio_para(Cita.CONVENIO_PRIVADO, True),
                te.precio_para(Cita.CONVENIO_PRIVADO, False),
                te.duracion_minutos,
                ids_radiologos_activos(te),
            )
            for te in queryset
        }
        self.fields['tipo_estudio'].widget.grupo_de = {
            str(te.pk): te.get_modalidad_display() for te in queryset
        }

    def clean_dpi(self):
        dpi = self.cleaned_data['dpi'].strip()
        if not dpi.isdigit():
            raise forms.ValidationError('El DPI debe contener solo números.')
        if len(dpi) != 13:
            raise forms.ValidationError('El DPI debe tener exactamente 13 dígitos.')
        return dpi

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        if not NOMBRE_REGEX.match(nombre):
            raise forms.ValidationError('El nombre solo puede contener letras y espacios.')
        return nombre

    def clean_apellido(self):
        apellido = self.cleaned_data['apellido'].strip()
        if not NOMBRE_REGEX.match(apellido):
            raise forms.ValidationError('El apellido solo puede contener letras y espacios.')
        return apellido

    def clean_correo(self):
        correo = (self.cleaned_data['correo'] or '').strip().lower()
        validar_dominio_correo(correo)
        return correo

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data['fecha_nacimiento']
        validar_fecha_nacimiento_no_futura(fecha)
        return fecha


class RegistrarTicketForm(forms.Form):
    """Check-in de un paciente que llega sin cita (HU: Registrar Ticket,
    pantalla de Emergencia IGSS). Si el DPI ya existe se reutiliza ese
    paciente; si no, se registra con los datos capturados aquí."""

    dpi = forms.CharField(
        label='DPI',
        max_length=13,
        min_length=13,
        widget=forms.TextInput(attrs={
            'maxlength': 13,
            'inputmode': 'numeric',
            'pattern': r'\d{13}',
            'title': 'El DPI debe tener exactamente 13 dígitos.',
        }),
    )
    nombre = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'pattern': r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+',
            'title': 'Solo letras y espacios.',
        }),
    )
    apellido = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'pattern': r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+',
            'title': 'Solo letras y espacios.',
        }),
    )
    sexo = forms.ChoiceField(
        choices=[('', '---------')] + list(Paciente.SEXO_CHOICES), required=False,
    )
    telefono = forms.CharField(max_length=20, required=False)
    correo = forms.EmailField(
        label='Correo electrónico',
        max_length=254,
        widget=forms.EmailInput(attrs={
            'placeholder': 'paciente@correo.com',
            'autocomplete': 'email',
        }),
    )
    fecha_nacimiento = forms.DateField(
        required=False, widget=forms.DateInput(attrs={'type': 'date'}),
    )
    carnet_igss = forms.CharField(
        label='Carné de afiliación IGSS',
        max_length=20,
        widget=forms.TextInput(attrs={'inputmode': 'numeric', 'required': True}),
    )
    motivo = forms.CharField(
        label='Motivo de la visita',
        max_length=255,
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fecha_nacimiento'].widget.attrs['max'] = timezone.localdate().isoformat()

    def clean_dpi(self):
        dpi = self.cleaned_data['dpi'].strip()
        if not dpi.isdigit():
            raise forms.ValidationError('El DPI debe contener solo números.')
        if len(dpi) != 13:
            raise forms.ValidationError('El DPI debe tener exactamente 13 dígitos.')
        return dpi

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        if not NOMBRE_REGEX.match(nombre):
            raise forms.ValidationError('El nombre solo puede contener letras y espacios.')
        return nombre

    def clean_apellido(self):
        apellido = self.cleaned_data['apellido'].strip()
        if not NOMBRE_REGEX.match(apellido):
            raise forms.ValidationError('El apellido solo puede contener letras y espacios.')
        return apellido

    def clean_correo(self):
        correo = self.cleaned_data['correo'].strip().lower()
        validar_dominio_correo(correo)
        return correo

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data['fecha_nacimiento']
        validar_fecha_nacimiento_no_futura(fecha)
        return fecha

    def clean_carnet_igss(self):
        return limpiar_carnet_igss(
            self.cleaned_data.get('carnet_igss'),
            dpi=self.cleaned_data.get('dpi'),
            requerido=True,
        )


class CompletarDatosPacienteForm(forms.Form):
    """Usado desde la notificación de datos pendientes: solo pide los
    campos opcionales que se pueden completar después (sexo, teléfono y
    fecha de nacimiento)."""

    sexo = forms.ChoiceField(
        choices=[('', '---------')] + list(Paciente.SEXO_CHOICES), required=False,
    )
    telefono = forms.CharField(max_length=20, required=False)
    fecha_nacimiento = forms.DateField(
        required=False, widget=forms.DateInput(attrs={'type': 'date'}),
    )

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data.get('fecha_nacimiento')
        validar_fecha_nacimiento_no_futura(fecha)
        return fecha


class IngresarCorreoEnvioForm(forms.Form):
    """Usado cuando la recepcionista quiere enviar un estudio pero el
    paciente todavía no tiene correo registrado: pide el correo y, al
    guardarlo, la vista manda el estudio de una vez."""

    correo = forms.EmailField(
        label='Correo electrónico',
        max_length=254,
        widget=forms.EmailInput(attrs={
            'placeholder': 'paciente@correo.com',
            'autocomplete': 'email',
        }),
    )

    def clean_correo(self):
        correo = self.cleaned_data['correo'].strip().lower()
        validar_dominio_correo(correo)
        return correo


class ProcesarTicketForm(forms.Form):
    """Convierte un ticket en espera directamente en una orden de trabajo
    para el técnico (se salta la revisión del radiólogo: el paciente ya
    está físicamente en la clínica por emergencia)."""

    tipo_estudio = forms.ModelChoiceField(
        queryset=TipoEstudio.objects.filter(activo=True).order_by('nombre'),
        label='Tipo de estudio',
    )
    motivo = forms.CharField(
        label='Motivo / indicación clínica',
        widget=forms.Textarea(attrs={'rows': 4}),
        help_text='Ej: Paciente presenta dolor torácico agudo.',
    )


# Cada estudio tiene un precio por convenio y por tipo de horario. COEX solo
# tiene tarifa hábil; Privado y Emergencia IGSS tienen hábil e inhábil (a
# partir de las 18:00). El formulario expone esas 5 celdas.
PRECIOS_ESTUDIO = [
    ('precio_coex_habil', Cita.CONVENIO_COEX, True, 'COEX'),
    ('precio_privado_habil', Cita.CONVENIO_PRIVADO, True, 'Privado · hábil'),
    ('precio_privado_inhabil', Cita.CONVENIO_PRIVADO, False, 'Privado · inhábil'),
    ('precio_emergencia_igss_habil', Cita.CONVENIO_EMERGENCIA_IGSS, True, 'Emergencia IGSS · hábil'),
    ('precio_emergencia_igss_inhabil', Cita.CONVENIO_EMERGENCIA_IGSS, False, 'Emergencia IGSS · inhábil'),
]


class CrearTipoEstudioForm(forms.ModelForm):
    class Meta:
        model = TipoEstudio
        fields = ('nombre', 'modalidad', 'duracion_minutos')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        actuales = {}
        if self.instance and self.instance.pk:
            actuales = {
                (p.convenio, p.horario_habil): p.precio
                for p in self.instance.precios.all()
            }
        for campo, convenio, habil, etiqueta in PRECIOS_ESTUDIO:
            self.fields[campo] = forms.DecimalField(
                label=f'Precio {etiqueta}', max_digits=8, decimal_places=2, min_value=0,
                initial=actuales.get((convenio, habil), 0),
            )

    def clean_duracion_minutos(self):
        duracion = self.cleaned_data['duracion_minutos']
        if duracion <= 0:
            raise forms.ValidationError('La duración debe ser mayor a 0 minutos.')
        return duracion

    def save(self, commit=True):
        tipo_estudio = super().save(commit=commit)

        def guardar_precios():
            from .models import PrecioEstudio
            for campo, convenio, habil, _ in PRECIOS_ESTUDIO:
                PrecioEstudio.objects.update_or_create(
                    tipo_estudio=tipo_estudio, convenio=convenio, horario_habil=habil,
                    defaults={'precio': self.cleaned_data[campo]},
                )

        if commit:
            guardar_precios()
        else:
            self._guardar_precios = guardar_precios
        return tipo_estudio


class ComboForm(forms.ModelForm):
    class Meta:
        model = Combo
        fields = ('nombre', 'estudios', 'activo', 'aplica_descuento', 'porcentaje_descuento')
        widgets = {'estudios': forms.CheckboxSelectMultiple}

    def clean_porcentaje_descuento(self):
        pct = self.cleaned_data['porcentaje_descuento']
        if not self.cleaned_data.get('aplica_descuento'):
            return pct
        if pct is None or pct <= 0 or pct > 100:
            raise forms.ValidationError('El porcentaje de descuento debe estar entre 0 y 100.')
        return pct


class GenerarOrdenForm(forms.Form):
    motivo = forms.CharField(
        label='Motivo / indicación clínica',
        widget=forms.Textarea(attrs={'rows': 4}),
        help_text='Ej: Paciente presenta lesiones graves en el brazo izquierdo.',
    )


EXTENSIONES_IMAGEN_DIRECTA = ('.jpg', '.jpeg', '.png')

# Archivos que suelen venir "de regalo" al subir una carpeta completa del
# escáner (miniaturas/metadatos del sistema operativo, no son parte del
# estudio) y que se descartan en silencio en vez de rechazar todo el envío.
NOMBRES_IGNORADOS_EN_CARPETA = ('.ds_store', 'thumbs.db', 'desktop.ini')


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(d, initial) for d in data]
        return [single_file_clean(data, initial)] if data else []


class AdjuntarImagenesForm(forms.Form):
    """Acepta tanto imágenes sueltas (JPG/PNG) como la carpeta completa que
    exporta el equipo de rayos X/tomógrafo: series DICOM con archivos
    `.dcm` o sin extensión (ej. `I0`, `I1`, ...). Los `.dcm`/sin extensión
    se convierten a JPG al guardarlos (ver dicom_utils.dicom_a_jpg_memoria),
    portado de la rama Andres de TechBlood/ProyectoSeminarioClinica."""

    imagenes = MultipleFileField(
        label='Imágenes del estudio',
        help_text=(
            'Selecciona la carpeta completa del estudio DICOM, o imágenes JPG/PNG '
            'sueltas. Los archivos DICOM se convierten a JPG automáticamente.'
        ),
        widget=MultipleFileInput(attrs={'webkitdirectory': True, 'directory': True}),
    )

    def clean_imagenes(self):
        archivos = self.cleaned_data['imagenes']
        archivos_utiles = [
            archivo for archivo in archivos
            if not archivo.name.lower().endswith(NOMBRES_IGNORADOS_EN_CARPETA)
            and not archivo.name.startswith('.')
        ]
        if not archivos_utiles:
            raise forms.ValidationError('No se seleccionó ningún archivo válido.')
        return archivos_utiles


class AdjuntarInformeForm(forms.Form):
    informe_texto = forms.CharField(
        label='Informe (texto)',
        widget=forms.Textarea(attrs={'rows': 8}),
        required=False,
    )
    informe_archivo = forms.FileField(
        label='Informe (PDF)',
        required=False,
    )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('informe_texto') and not cleaned.get('informe_archivo'):
            raise forms.ValidationError(
                'Escribe el informe, adjunta un archivo, o ambos.'
            )
        archivo = cleaned.get('informe_archivo')
        if archivo and not archivo.name.lower().endswith('.pdf'):
            raise forms.ValidationError('El archivo adjunto debe ser un PDF.')
        return cleaned


class RegistrarPagoEstudioForm(forms.Form):
    forma_pago = forms.ChoiceField(
        label='Forma de pago', choices=Cobro.FORMA_PAGO_CHOICES,
    )
    numero_boleta = forms.CharField(
        label='Número de boleta / referencia', max_length=60, required=False,
    )
    notas = forms.CharField(
        label='Notas', max_length=255, required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
    )

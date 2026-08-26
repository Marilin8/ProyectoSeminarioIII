import re

from django import forms
from django.utils import timezone

from accounts.models import Usuario

from .models import Cita, Paciente, Ticket, TipoEstudio

CONVENIOS_QUE_REQUIEREN_CARNET_IGSS = (Cita.CONVENIO_COEX, Cita.CONVENIO_EMERGENCIA_IGSS)

NOMBRE_REGEX = re.compile(r'^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+$')


class TipoEstudioSelect(forms.Select):
    """Select de tipo de estudio que agrega precio y duración como atributos
    data-* de cada <option>, para que el formulario los muestre en pantalla
    sin pedirlos de nuevo al servidor."""

    detalles = {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        detalle = self.detalles.get(str(value)) if value else None
        if detalle:
            option['attrs']['data-precio'] = str(detalle[0])
            option['attrs']['data-duracion'] = str(detalle[1])
        return option


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
        self.fields['tipo_estudio'].widget.detalles = {
            str(te.pk): (te.precio, te.duracion_minutos)
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
        return self.cleaned_data['correo'].strip().lower()

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
    prioridad = forms.ChoiceField(
        choices=Ticket.PRIORIDAD_CHOICES,
        initial=Ticket.PRIORIDAD_NORMAL,
        label='Prioridad',
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
        return self.cleaned_data['correo'].strip().lower()

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


class CrearTipoEstudioForm(forms.ModelForm):
    class Meta:
        model = TipoEstudio
        fields = ('nombre', 'precio', 'duracion_minutos')

    def clean_precio(self):
        precio = self.cleaned_data['precio']
        if precio <= 0:
            raise forms.ValidationError('El precio debe ser mayor a 0.')
        return precio

    def clean_duracion_minutos(self):
        duracion = self.cleaned_data['duracion_minutos']
        if duracion <= 0:
            raise forms.ValidationError('La duración debe ser mayor a 0 minutos.')
        return duracion


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

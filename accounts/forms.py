from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm

from clinica.validators import validar_dominio_correo
from pacientes.models import TipoEstudio

from .models import Usuario


class LoginForm(AuthenticationForm):
    """Login con un mensaje claro cuando el usuario existe pero está inactivo
    (Django, para un usuario inactivo, muestra el error genérico de
    credenciales porque el backend devuelve None antes de llegar a
    confirm_login_allowed)."""

    error_messages = {
        **AuthenticationForm.error_messages,
        'inactive': 'Tu usuario está inactivo. Pedile al administrador que lo reactive.',
    }

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        if username and password:
            Modelo = get_user_model()
            try:
                usuario = Modelo._default_manager.get_by_natural_key(username)
            except Modelo.DoesNotExist:
                usuario = None
            if usuario is not None and not usuario.is_active:
                raise forms.ValidationError(self.error_messages['inactive'], code='inactive')
        return super().clean()


# Longitud mínima de contraseña en el cambio de contraseña del propio perfil.
PASSWORD_MIN_LEN = 10

ROLES_CON_COMISION = (
    Usuario.ROL_TECNICO_IMAGENES,
    Usuario.ROL_MEDICO_RADIOLOGO,
    Usuario.ROL_MEDICO_REMITENTE,
)

CAMPOS_PORCENTAJE = ('porcentaje_coex', 'porcentaje_privado', 'porcentaje_emergencia_igss')


def _campo_email():
    """Correo obligatorio, con formato válido y dominio real (no temporal)."""
    return forms.EmailField(
        label='Correo',
        required=True,
        validators=[validar_dominio_correo],
        error_messages={
            'required': 'El correo es obligatorio.',
            'invalid': 'Ingresá un correo electrónico válido (ejemplo: nombre@dominio.com).',
        },
    )


def _validar_porcentajes(form, cleaned):
    """Reglas de comisión compartidas por crear y editar usuario:
    - cada porcentaje entre 0 y 100
    - si el rol no cobra comisión, se fuerzan a 0"""
    rol = cleaned.get('rol')
    for campo in CAMPOS_PORCENTAJE:
        valor = cleaned.get(campo)
        if valor is not None and not (0 <= valor <= 100):
            form.add_error(campo, 'El porcentaje debe estar entre 0 y 100.')
    if rol not in ROLES_CON_COMISION:
        for campo in CAMPOS_PORCENTAJE:
            cleaned[campo] = 0

    salario = cleaned.get('salario_base')
    if salario is not None and salario < 0:
        form.add_error('salario_base', 'El salario base no puede ser negativo.')
    return cleaned


class CrearUsuarioForm(UserCreationForm):
    email = _campo_email()

    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = (
            'username', 'first_name', 'last_name', 'email', 'rol', 'salario_base',
            'porcentaje_coex', 'porcentaje_privado', 'porcentaje_emergencia_igss',
        )

    def clean(self):
        cleaned = super().clean()
        return _validar_porcentajes(self, cleaned)


class CambiarContrasenaForm(PasswordChangeForm):
    """Cambio de contraseña del propio perfil con reglas propias (no las de
    AUTH_PASSWORD_VALIDATORS): al menos 10 caracteres, una mayúscula, mezcla
    de letras y números, distinta del nombre/usuario y de la anterior."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.help_text = ''

    def clean_new_password1(self):
        pw = self.cleaned_data.get('new_password1') or ''
        errores = []
        if len(pw) < PASSWORD_MIN_LEN:
            errores.append(f'Debe tener al menos {PASSWORD_MIN_LEN} caracteres.')
        if not any(c.isupper() for c in pw):
            errores.append('Debe incluir al menos una letra mayúscula.')
        if not (any(c.isalpha() for c in pw) and any(c.isdigit() for c in pw)):
            errores.append('Debe combinar letras y números.')
        datos_personales = [
            self.user.username, self.user.first_name, self.user.last_name,
        ]
        if any(dato and pw.lower() == dato.lower() for dato in datos_personales):
            errores.append('No puede ser igual a tu nombre ni a tu usuario.')
        if pw and self.user.check_password(pw):
            errores.append('No puede ser igual a tu contraseña anterior.')
        if errores:
            raise forms.ValidationError(errores)
        return pw

    def _post_clean(self):
        # Salta la validación de AUTH_PASSWORD_VALIDATORS que hace
        # SetPasswordForm._post_clean; ya validamos en clean_new_password1.
        forms.Form._post_clean(self)


class PerfilForm(forms.ModelForm):
    """Datos que cada usuario puede editar de su propio perfil. No incluye
    rol, comisiones, estado ni username."""

    email = _campo_email()

    class Meta:
        model = Usuario
        fields = ('first_name', 'last_name', 'email')
        labels = {'first_name': 'Nombres', 'last_name': 'Apellidos'}

    def clean_first_name(self):
        valor = (self.cleaned_data.get('first_name') or '').strip()
        if not valor:
            raise forms.ValidationError('El nombre es obligatorio.')
        return valor

    def clean_last_name(self):
        valor = (self.cleaned_data.get('last_name') or '').strip()
        if not valor:
            raise forms.ValidationError('El apellido es obligatorio.')
        return valor


class EditarUsuarioForm(forms.ModelForm):
    """Edición completa de un usuario existente desde la pantalla de
    administración: datos personales, rol, comisiones, estado y — solo para
    radiólogos — los tipos de estudio que puede realizar."""

    email = _campo_email()

    tipos_estudio = forms.ModelMultipleChoiceField(
        queryset=TipoEstudio.objects.order_by('nombre'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label='Estudios que este radiólogo puede realizar',
        help_text='Al agendar una cita, solo se podrá asignar el estudio a los radiólogos marcados aquí.',
    )

    class Meta:
        model = Usuario
        fields = (
            'first_name', 'last_name', 'email', 'rol', 'salario_base',
            'porcentaje_coex', 'porcentaje_privado', 'porcentaje_emergencia_igss',
            'is_active',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['tipos_estudio'].initial = self.instance.tipos_estudio_asignados.all()

    def clean(self):
        cleaned = super().clean()
        return _validar_porcentajes(self, cleaned)

    def save(self, commit=True):
        usuario = super().save(commit=commit)

        def guardar_estudios():
            if usuario.rol == Usuario.ROL_MEDICO_RADIOLOGO:
                usuario.tipos_estudio_asignados.set(self.cleaned_data['tipos_estudio'])
            else:
                usuario.tipos_estudio_asignados.clear()

        if commit:
            guardar_estudios()
        else:
            self._guardar_estudios = guardar_estudios
        return usuario


class RegistrarPagoPlanillaForm(forms.Form):
    """Comprobante de pago de planilla: foto de la boleta o de la
    transferencia (JPG/PNG/WEBP) o un PDF, el número de boleta y una nota.

    Al validar, corre el OCR del comprobante (``accounts.verificacion_boleta``)
    y compara el monto (y el número de boleta, si se indicó) con lo que se
    está pagando. Si no coinciden, no deja registrar el pago salvo que se
    marque ``confirmar_pese_a_diferencia``.
    """

    EXTENSIONES_VALIDAS = ('.jpg', '.jpeg', '.png', '.webp', '.pdf')
    TAMANO_MAXIMO = 10 * 1024 * 1024  # 10 MB

    comprobante = forms.FileField(label='Comprobante (boleta o transferencia)')
    numero_boleta = forms.CharField(
        label='Número de boleta / referencia', max_length=60, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'El que aparece en la boleta'}),
    )
    notas = forms.CharField(
        label='Notas (opcional)', max_length=255, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Ej.: transferencia Banco Industrial'}),
    )
    confirmar_pese_a_diferencia = forms.BooleanField(
        label='Registrar el pago aunque los datos del comprobante no coincidan',
        required=False,
    )

    def __init__(self, *args, monto_esperado=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.monto_esperado = monto_esperado
        self.verificacion = None

    def clean_comprobante(self):
        archivo = self.cleaned_data['comprobante']
        if not archivo.name.lower().endswith(self.EXTENSIONES_VALIDAS):
            raise forms.ValidationError('Subí una foto (JPG, PNG o WEBP) o un PDF.')
        if archivo.size > self.TAMANO_MAXIMO:
            raise forms.ValidationError('El archivo no debe pesar más de 10 MB.')
        return archivo

    def clean(self):
        from .verificacion_boleta import ESTADO_NO_COINCIDE, verificar

        cleaned = super().clean()
        archivo = cleaned.get('comprobante')
        if archivo is None or self.monto_esperado is None:
            return cleaned

        contenido = archivo.read()
        archivo.seek(0)  # el archivo se sigue usando para guardarlo
        self.verificacion = verificar(
            contenido, self.monto_esperado, cleaned.get('numero_boleta', ''),
            nombre_archivo=archivo.name,
        )

        if self.verificacion.estado == ESTADO_NO_COINCIDE and not cleaned.get('confirmar_pese_a_diferencia'):
            raise forms.ValidationError(
                'Los datos del comprobante no coinciden con el pago: '
                f'{self.verificacion.mensaje}. Revisá la boleta; si aun así querés '
                'registrar el pago, marcá la casilla de confirmación.'
            )
        return cleaned

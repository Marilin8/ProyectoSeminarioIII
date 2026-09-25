import datetime

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.utils import timezone

from clinica.validators import validar_correo_existente, validar_dominio_correo
from pacientes.models import TipoEstudio

from .models import RolAdicional, Usuario


def _campo_fecha_ingreso(inicial=None):
    """Desde cuándo trabaja el empleado en la clínica: se usa para saber a
    partir de qué mes se le debe salario/comisiones (ver accounts.planilla
    y la pestaña "Pendiente de pago"), en vez de asumir que empezó el día
    que se le creó la cuenta en el sistema."""
    return forms.DateField(
        label='Fecha de ingreso a la clínica',
        required=True,
        initial=inicial,
        widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        input_formats=['%Y-%m-%d'],
        help_text='Desde esta fecha se le empieza a contar salario y comisiones pendientes.',
    )


def _validar_fecha_ingreso_no_futura(fecha):
    if fecha and fecha > timezone.localdate():
        raise forms.ValidationError('La fecha de ingreso no puede ser futura.')
    return fecha


def _campo_fecha_ingreso(inicial=None):
    """Desde cuándo trabaja el empleado en la clínica: se usa para saber a
    partir de qué mes se le debe salario/comisiones (ver accounts.planilla
    y la pestaña "Pendiente de pago"), en vez de asumir que empezó el día
    que se le creó la cuenta en el sistema."""
    return forms.DateField(
        label='Fecha de ingreso a la clínica',
        required=True,
        initial=inicial,
        widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        input_formats=['%Y-%m-%d'],
        help_text='Desde esta fecha se le empieza a contar salario y comisiones pendientes.',
    )


def _validar_fecha_ingreso_no_futura(fecha):
    if fecha and fecha > timezone.localdate():
        raise forms.ValidationError('La fecha de ingreso no puede ser futura.')
    return fecha


class LoginForm(AuthenticationForm):
    """Login con un mensaje claro cuando el usuario existe pero está inactivo
    (Django, para un usuario inactivo, muestra el error genérico de
    credenciales porque el backend devuelve None antes de llegar a
    confirm_login_allowed)."""

    error_messages = {
        **AuthenticationForm.error_messages,
        'inactive': 'Tu usuario está inactivo. Pedile al administrador que lo reactive.',
        'correo_sin_confirmar': (
            'Todavía no confirmaste tu correo. Revisá tu bandeja de entrada (y spam) '
            'y entrá al link que te mandamos para poder ingresar.'
        ),
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
                # Cuenta recién creada esperando que confirme su correo (ver
                # accounts.views.crear_usuario) vs. suspendida a mano por un
                # administrador (cambiar_estado_usuario): son dos motivos
                # distintos de estar inactivo, con mensajes distintos.
                if usuario.token_confirmacion_correo:
                    raise forms.ValidationError(
                        self.error_messages['correo_sin_confirmar'], code='correo_sin_confirmar',
                    )
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
        validators=[validar_dominio_correo, validar_correo_existente],
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


ROLES_NO_ASIGNABLES_COMO_ADICIONALES = (
    Usuario.ROL_ADMINISTRADOR,
    Usuario.ROL_ADMINISTRADOR_FINANCIERO,
    Usuario.ROL_MEDICO_RADIOLOGO,
    Usuario.ROL_MEDICO_REMITENTE,
)


def _campo_roles_adicionales():
    """Además de su rol principal (que define comportamiento por defecto,
    ej. en qué lista aparece primero), un usuario puede tener roles
    adicionales -- ej. un técnico al que también se le habilita el rol de
    recepcionista. Administrador, administrador financiero, médico
    radiólogo y médico remitente no se ofrecen como roles adicionales, solo
    como rol principal. Ver Usuario.tiene_rol / accounts.models.RolAdicional."""
    choices = [
        choice for choice in Usuario.ROL_CHOICES
        if choice[0] not in ROLES_NO_ASIGNABLES_COMO_ADICIONALES
    ]
    return forms.MultipleChoiceField(
        choices=choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Roles adicionales',
        help_text=(
            'Además de su rol principal, este usuario también ve las pantallas y '
            'tiene los permisos de los roles que marques acá.'
        ),
    )


def _guardar_roles_adicionales(usuario, roles_seleccionados):
    """Sincroniza RolAdicional con lo que se marcó en el form -- solo
    agrega/quita lo que cambió, sin borrar y recrear todo."""
    seleccionados = set(roles_seleccionados or ()) - {usuario.rol}
    actuales = set(usuario.roles_adicionales.values_list('rol', flat=True))
    a_quitar = actuales - seleccionados
    a_agregar = seleccionados - actuales
    if a_quitar:
        RolAdicional.objects.filter(usuario=usuario, rol__in=a_quitar).delete()
    if a_agregar:
        RolAdicional.objects.bulk_create([
            RolAdicional(usuario=usuario, rol=rol) for rol in a_agregar
        ])


class CrearUsuarioForm(UserCreationForm):
    email = _campo_email()
    puede_operar_caja = forms.BooleanField(
        label='Puede operar Caja', required=False,
        help_text='Permite gestionar pagos de estudios sin cambiar el rol principal.',
    )
    roles_adicionales = _campo_roles_adicionales()
    fecha_ingreso = _campo_fecha_ingreso(inicial=timezone.localdate)

    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = (
            'username', 'first_name', 'last_name', 'email', 'rol', 'salario_base',
            'puede_operar_caja', 'sala',
            'porcentaje_coex', 'porcentaje_privado', 'porcentaje_emergencia_igss',
        )

    def clean(self):
        cleaned = super().clean()
        return _validar_porcentajes(self, cleaned)

    def clean_fecha_ingreso(self):
        return _validar_fecha_ingreso_no_futura(self.cleaned_data.get('fecha_ingreso'))

    def save(self, commit=True):
        usuario = super().save(commit=False)
        fecha = self.cleaned_data.get('fecha_ingreso')
        if fecha:
            usuario.date_joined = timezone.make_aware(
                datetime.datetime.combine(fecha, datetime.time.min)
            )

        def guardar_roles_adicionales():
            _guardar_roles_adicionales(usuario, self.cleaned_data.get('roles_adicionales'))

        if commit:
            usuario.save()
            guardar_roles_adicionales()
        else:
            self._guardar_roles_adicionales = guardar_roles_adicionales
        return usuario


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
        fields = ('first_name', 'last_name', 'email', 'foto_perfil')
        labels = {'first_name': 'Nombres', 'last_name': 'Apellidos', 'foto_perfil': 'Foto de perfil'}

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
    puede_operar_caja = forms.BooleanField(
        label='Puede operar Caja', required=False,
        help_text='Permite gestionar pagos de estudios sin cambiar el rol principal.',
    )

    tipos_estudio = forms.ModelMultipleChoiceField(
        queryset=TipoEstudio.objects.order_by('nombre'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label='Estudios que este radiólogo puede realizar',
        help_text='Al agendar una cita, solo se podrá asignar el estudio a los radiólogos marcados aquí.',
    )
    roles_adicionales = _campo_roles_adicionales()
    fecha_ingreso = _campo_fecha_ingreso()

    class Meta:
        model = Usuario
        fields = (
            'first_name', 'last_name', 'email', 'rol', 'salario_base',
            'puede_operar_caja', 'sala',
            'porcentaje_coex', 'porcentaje_privado', 'porcentaje_emergencia_igss',
            'is_active',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['tipos_estudio'].initial = self.instance.tipos_estudio_asignados.all()
            self.fields['fecha_ingreso'].initial = self.instance.date_joined.date()
            self.fields['roles_adicionales'].initial = list(
                self.instance.roles_adicionales.values_list('rol', flat=True)
            )

    def clean(self):
        cleaned = super().clean()
        return _validar_porcentajes(self, cleaned)

    def clean_fecha_ingreso(self):
        return _validar_fecha_ingreso_no_futura(self.cleaned_data.get('fecha_ingreso'))

    def save(self, commit=True):
        usuario = super().save(commit=False)
        fecha = self.cleaned_data.get('fecha_ingreso')
        if fecha:
            usuario.date_joined = timezone.make_aware(
                datetime.datetime.combine(fecha, datetime.time.min)
            )

        def guardar_estudios():
            if usuario.rol == Usuario.ROL_MEDICO_RADIOLOGO:
                usuario.tipos_estudio_asignados.set(self.cleaned_data['tipos_estudio'])
            else:
                usuario.tipos_estudio_asignados.clear()

        if commit:
            usuario.save()
            guardar_estudios()
            _guardar_roles_adicionales(usuario, self.cleaned_data.get('roles_adicionales'))
        else:
            self._guardar_estudios = guardar_estudios
        return usuario


class RegistrarPagoForm(forms.Form):
    """Comprobante de un pago de planilla (salario o comisiones): foto de la
    boleta o de la transferencia (JPG/PNG/WEBP) o un PDF, el número de boleta
    y una nota.

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

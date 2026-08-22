from django.contrib.auth.forms import UserCreationForm

from .models import Usuario

ROLES_CON_COMISION = (
    Usuario.ROL_TECNICO_IMAGENES,
    Usuario.ROL_MEDICO_RADIOLOGO,
    Usuario.ROL_MEDICO_REMITENTE,
)


class CrearUsuarioForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = (
            'username', 'first_name', 'last_name', 'email', 'rol',
            'porcentaje_coex', 'porcentaje_privado', 'porcentaje_emergencia_igss',
        )

    def clean(self):
        cleaned = super().clean()
        rol = cleaned.get('rol')
        campos_porcentaje = ('porcentaje_coex', 'porcentaje_privado', 'porcentaje_emergencia_igss')

        for campo in campos_porcentaje:
            valor = cleaned.get(campo)
            if valor is not None and not (0 <= valor <= 100):
                self.add_error(campo, 'El porcentaje debe estar entre 0 y 100.')

        if rol not in ROLES_CON_COMISION:
            for campo in campos_porcentaje:
                cleaned[campo] = 0

        return cleaned

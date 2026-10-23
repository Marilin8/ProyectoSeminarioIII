from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AgenteEquipo, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ('username', 'first_name', 'last_name', 'rol', 'is_staff', 'is_active')
    list_filter = ('rol', 'is_staff', 'is_superuser', 'is_active')
    fieldsets = UserAdmin.fieldsets + (
        ('Rol y permisos operativos', {'fields': ('rol', 'puede_operar_caja')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Rol y permisos operativos', {'fields': ('rol', 'puede_operar_caja')}),
    )


@admin.register(AgenteEquipo)
class AgenteEquipoAdmin(admin.ModelAdmin):
    """Solo para ver y revocar: el token se crea con ``manage.py token_agente``."""
    list_display = ('nombre', 'activo', 'ultimo_uso', 'ultima_ip', 'creado_en')
    readonly_fields = ('ultimo_uso', 'ultima_ip', 'creado_en')
    fields = ('nombre', 'activo', 'ultimo_uso', 'ultima_ip', 'creado_en')

    def has_add_permission(self, request):
        return False

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


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

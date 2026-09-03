from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import PagoPlanilla, Usuario


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


@admin.register(PagoPlanilla)
class PagoPlanillaAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'anio', 'mes', 'total', 'numero_boleta', 'verificado')
    list_filter = ('anio', 'mes', 'verificado')
    search_fields = ('usuario__username', 'usuario__first_name', 'usuario__last_name', 'numero_boleta')

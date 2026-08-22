from django.contrib import admin

from .models import Notificacion, TipoEstudio


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ('destinatario', 'tipo', 'mensaje', 'leida', 'creada_en')
    list_filter = ('tipo', 'leida')
    search_fields = ('mensaje', 'destinatario__username')
    autocomplete_fields = ('destinatario',)


@admin.register(TipoEstudio)
class TipoEstudioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'precio', 'duracion_minutos', 'activo')
    list_filter = ('activo',)
    search_fields = ('nombre',)
    filter_horizontal = ('radiologos',)

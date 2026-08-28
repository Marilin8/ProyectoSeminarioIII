from django.contrib import admin

<<<<<<< HEAD
from .models import Notificacion, PrecioEstudio, TipoEstudio
=======
from .models import Notificacion, TipoEstudio
>>>>>>> 6c6a7f92a98d42c5c4312897e77c9a819885bb58


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ('destinatario', 'tipo', 'mensaje', 'leida', 'creada_en')
    list_filter = ('tipo', 'leida')
    search_fields = ('mensaje', 'destinatario__username')
    autocomplete_fields = ('destinatario',)


<<<<<<< HEAD
class PrecioEstudioInline(admin.TabularInline):
    model = PrecioEstudio
    extra = 0


@admin.register(TipoEstudio)
class TipoEstudioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'modalidad', 'duracion_minutos', 'precio_referencia', 'activo')
    list_filter = ('modalidad', 'activo')
    search_fields = ('nombre',)
    filter_horizontal = ('radiologos',)
    inlines = (PrecioEstudioInline,)


@admin.register(PrecioEstudio)
class PrecioEstudioAdmin(admin.ModelAdmin):
    list_display = ('tipo_estudio', 'convenio', 'horario_habil', 'precio')
    list_filter = ('convenio', 'horario_habil', 'tipo_estudio__modalidad')
    search_fields = ('tipo_estudio__nombre',)
=======
@admin.register(TipoEstudio)
class TipoEstudioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'precio', 'duracion_minutos', 'activo')
    list_filter = ('activo',)
    search_fields = ('nombre',)
    filter_horizontal = ('radiologos',)
>>>>>>> 6c6a7f92a98d42c5c4312897e77c9a819885bb58

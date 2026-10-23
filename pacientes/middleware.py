"""Middlewares de mantenimiento que corren en cada request: marcan ausentes
las citas vencidas y aplican los cambios de estudio programados. Así no
hace falta un cron aparte para esas dos tareas.
"""
from .models import CambioEstudioProgramado, Cita


class AutoMarcarAusenteMiddleware:
    """Antes de cada request, pasa a AUSENTE las citas AGENDADAS cuyo día ya
    venció (ver Cita.marcar_ausentes_vencidas)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        Cita.marcar_ausentes_vencidas()
        return self.get_response(request)


class AplicarCambiosEstudioProgramadosMiddleware:
    """Antes de cada request, aplica los cambios de estudio (nombre,
    modalidad, duración y/o precios) que un administrador programó y cuya
    fecha de vigencia ya llegó (ver CambioEstudioProgramado.aplicar_vencidos)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        CambioEstudioProgramado.aplicar_vencidos()
        return self.get_response(request)

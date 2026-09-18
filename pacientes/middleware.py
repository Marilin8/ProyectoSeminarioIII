from .models import Cita


class AutoMarcarAusenteMiddleware:
    """Antes de cada request, pasa a AUSENTE las citas AGENDADAS cuyo día ya
    venció (ver Cita.marcar_ausentes_vencidas)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        Cita.marcar_ausentes_vencidas()
        return self.get_response(request)

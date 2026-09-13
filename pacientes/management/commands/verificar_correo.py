from django.core.management.base import BaseCommand, CommandError

from clinica.didit import DiditError, verificar_correo


class Command(BaseCommand):
    help = (
        'Consulta la Email Risk API de Didit para un correo puntual y muestra el '
        'resultado completo -- para confirmar que la API key funciona y entender qué '
        'está viendo el sistema (validar_correo_existente en clinica/validators.py '
        'solo mira el campo "is_undeliverable"). No manda ningún código al correo. '
        'Uso: manage.py verificar_correo correo@ejemplo.com'
    )

    def add_arguments(self, parser):
        parser.add_argument('correo', help='Correo a consultar, ej. paciente@gmail.com')

    def handle(self, *args, **options):
        correo = options['correo']
        try:
            info = verificar_correo(correo)
        except DiditError as exc:
            raise CommandError(f'No se pudo consultar Didit: {exc}')

        bloqueado = bool(info.get('is_undeliverable'))
        intel = info.get('email_intelligence') or {}

        self.stdout.write(f'Correo consultado:     {correo}')
        self.stdout.write(f'Estado de la sesión:   {info.get("status")}')
        self.stdout.write(f'No se puede entregar:  {info.get("is_undeliverable")}')
        self.stdout.write(f'Es desechable:         {info.get("is_disposable")}')
        self.stdout.write(f'Aparece en filtración:  {info.get("is_breached")}')
        if info.get('breaches'):
            self.stdout.write(f'  Filtraciones:        {info["breaches"]}')
        if intel:
            self.stdout.write(f'Puntaje de riesgo:     {intel.get("score")} (0-100, mayor = más riesgo)')
            self.stdout.write(f'Entregabilidad:        {intel.get("deliverable")}')
            self.stdout.write(f'Dominio gratuito:      {intel.get("is_free_domain")}')
        self.stdout.write('')

        if bloqueado:
            self.stdout.write(self.style.ERROR(
                'El sistema RECHAZARÍA este correo (validar_correo_existente lanza '
                'ValidationError cuando is_undeliverable=True).'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                'El sistema DEJARÍA PASAR este correo (is_undeliverable=False o sin dato).'
            ))

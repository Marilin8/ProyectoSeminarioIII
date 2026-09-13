from django.core.management.base import BaseCommand, CommandError

from clinica.abstractapi import AbstractApiError, RESULTADO_NO_EXISTE, verificar_correo


class Command(BaseCommand):
    help = (
        'Consulta la Email Verification API de AbstractAPI para un correo puntual y '
        'muestra el resultado completo -- para confirmar que la API key funciona y '
        'entender qué está viendo el sistema (validar_correo_existente en '
        'clinica/validators.py solo mira el campo "deliverability"). '
        'Uso: manage.py verificar_correo correo@ejemplo.com'
    )

    def add_arguments(self, parser):
        parser.add_argument('correo', help='Correo a consultar, ej. paciente@gmail.com')

    def handle(self, *args, **options):
        correo = options['correo']
        try:
            datos = verificar_correo(correo)
        except AbstractApiError as exc:
            raise CommandError(f'No se pudo consultar AbstractAPI: {exc}')

        deliverability = datos.get('deliverability')
        bloqueado = deliverability == RESULTADO_NO_EXISTE

        self.stdout.write(f'Correo consultado:     {correo}')
        self.stdout.write(f'Formato válido:        {datos.get("is_valid_format", {}).get("value")}')
        self.stdout.write(f'Dominio tiene MX:      {datos.get("is_mx_found", {}).get("value")}')
        self.stdout.write(f'SMTP responde:         {datos.get("is_smtp_valid", {}).get("value")}')
        self.stdout.write(f'Correo gratuito:       {datos.get("is_free_email", {}).get("value")}')
        self.stdout.write(f'Casilla desechable:    {datos.get("is_disposable_email", {}).get("value")}')
        self.stdout.write(f'Casilla de rol:        {datos.get("is_role_email", {}).get("value")}')
        self.stdout.write(f'Dominio acepta todo:   {datos.get("is_catchall_email", {}).get("value")}')
        self.stdout.write(f'Puntaje de calidad:    {datos.get("quality_score")}')
        self.stdout.write('')
        self.stdout.write(f'Deliverability:        {deliverability}')

        if bloqueado:
            self.stdout.write(self.style.ERROR(
                'El sistema RECHAZARÍA este correo (validar_correo_existente lanza '
                'ValidationError solo cuando deliverability="UNDELIVERABLE").'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                'El sistema DEJARÍA PASAR este correo '
                f'(deliverability="{deliverability}", solo se rechaza "UNDELIVERABLE").'
            ))

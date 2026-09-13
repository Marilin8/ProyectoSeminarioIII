import dns.exception
from django.core.management.base import BaseCommand

from clinica.validators import dominio_puede_recibir_correo


class Command(BaseCommand):
    help = (
        'Consulta por DNS si el dominio de un correo puntual tiene MX (o, a falta de '
        'eso, A/AAAA) y muestra el resultado -- para entender qué está viendo el '
        'sistema (validar_correo_existente en clinica/validators.py). No confirma que '
        'el buzón puntual exista, solo que el dominio puede recibir correo. '
        'Uso: manage.py verificar_correo correo@ejemplo.com'
    )

    def add_arguments(self, parser):
        parser.add_argument('correo', help='Correo a consultar, ej. paciente@gmail.com')

    def handle(self, *args, **options):
        correo = options['correo']
        dominio = correo.rsplit('@', 1)[-1].strip().lower()
        self.stdout.write(f'Correo consultado: {correo}')
        self.stdout.write(f'Dominio a revisar: {dominio}')
        self.stdout.write('')

        try:
            puede_recibir = dominio_puede_recibir_correo(dominio)
        except dns.exception.DNSException as exc:
            self.stdout.write(self.style.WARNING(
                f'No se pudo consultar el DNS ({exc}). El sistema DEJARÍA PASAR este '
                'correo en ese caso (no bloquea por una falla de red).'
            ))
            return

        if puede_recibir:
            self.stdout.write(self.style.SUCCESS(
                'El dominio tiene MX (o A/AAAA). El sistema DEJARÍA PASAR este correo.'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                'El dominio no existe o no tiene ningún registro que le permita '
                'recibir correo. El sistema RECHAZARÍA este correo.'
            ))

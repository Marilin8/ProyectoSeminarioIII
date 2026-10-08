from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts import cifrado


class Command(BaseCommand):
    help = (
        'Descifra un respaldo .zip.cif usando la RESPALDOS_CLAVE del archivo .env. '
        'Sirve para recuperar un respaldo bajado de Google Drive aunque la web no funcione.'
    )

    def add_arguments(self, parser):
        parser.add_argument('archivo', help='Ruta del respaldo cifrado (.zip.cif)')
        parser.add_argument(
            'salida', nargs='?',
            help='Ruta del .zip de salida (por defecto, sin la extensión .cif)',
        )

    def handle(self, *args, **opciones):
        clave = (settings.RESPALDOS_CLAVE or '').strip()
        if not clave:
            raise CommandError('No hay RESPALDOS_CLAVE en el archivo .env.')
        origen = Path(opciones['archivo'])
        if not origen.is_file():
            raise CommandError(f'No existe el archivo {origen}.')
        salida = Path(opciones['salida']) if opciones['salida'] else origen.with_suffix('')
        if salida.exists():
            raise CommandError(f'{salida} ya existe; indique otra ruta de salida.')
        try:
            cifrado.descifrar_archivo(origen, salida, clave.encode('utf-8'))
        except cifrado.ErrorCifrado as error:
            salida.unlink(missing_ok=True)
            raise CommandError(str(error))
        self.stdout.write(self.style.SUCCESS(f'Respaldo descifrado en {salida}'))

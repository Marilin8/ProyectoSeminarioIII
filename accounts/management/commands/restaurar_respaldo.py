from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts import respaldos


class Command(BaseCommand):
    help = (
        'Restaura TODA la información del sistema desde un respaldo (.zip o .zip.cif). '
        'Antes guarda un respaldo de seguridad del estado actual. Sirve para respaldos '
        'demasiado grandes para subirlos por la página web.'
    )

    def add_arguments(self, parser):
        parser.add_argument('archivo', help='Ruta del respaldo (.zip o .zip.cif)')
        parser.add_argument(
            '--sin-archivos', action='store_true',
            help='No restaurar las imágenes e informes (solo la base de datos)',
        )
        parser.add_argument(
            '--si', action='store_true', help='No pedir la confirmación escrita (para uso en scripts)',
        )

    def handle(self, *args, **opciones):
        origen = Path(opciones['archivo'])
        if not origen.is_file():
            raise CommandError(f'No existe el archivo {origen}.')
        if not opciones['si']:
            self.stdout.write(self.style.WARNING(
                'Esto reemplaza TODA la información actual por la del respaldo '
                '(se guarda antes un respaldo de seguridad).'
            ))
            if input('Escriba RESTAURAR para continuar: ').strip().upper() != 'RESTAURAR':
                raise CommandError('Cancelado: no se restauró nada.')

        def mostrar(porcentaje, etapa):
            self.stdout.write(f'[{int(porcentaje):3d}%] {etapa}')

        try:
            seguridad, archivos = respaldos.restaurar(
                origen, restaurar_archivos=not opciones['sin_archivos'], progreso=mostrar,
            )
        except respaldos.ErrorRespaldo as error:
            raise CommandError(str(error))
        self.stdout.write(self.style.SUCCESS(
            f'Restauración completa. El estado anterior quedó en el respaldo {seguridad}.'
            + (f' Archivos restaurados: {archivos}.' if archivos else '')
        ))

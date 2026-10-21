from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts import respaldos


class Command(BaseCommand):
    help = (
        'Restaura las imágenes e informes (media/) aplicando, del más antiguo al más nuevo, '
        'todos los paquetes incrementales imagenes_*.zip(.cif) de una carpeta (por defecto, la '
        'carpeta de respaldos). Para recuperar el sistema completo: primero restaurar_respaldo '
        'con la última copia de la base de datos (auto_...) y después este comando. '
        'No toca la base de datos.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'carpeta', nargs='?',
            help='Carpeta con los paquetes imagenes_* (por defecto, la carpeta de respaldos)',
        )

    def handle(self, *args, **opciones):
        carpeta = Path(opciones['carpeta']) if opciones['carpeta'] else respaldos.carpeta_respaldos()
        if not carpeta.is_dir():
            raise CommandError(f'No existe la carpeta {carpeta}.')
        paquetes = sorted(
            (p for p in carpeta.iterdir()
             if p.is_file() and p.name.startswith(respaldos.PREFIJO_IMAGENES)
             and respaldos.NOMBRE_VALIDO.match(p.name)),
            key=lambda p: p.name,  # imagenes_AAAAMMDD_HHMMSS: el nombre ordena por fecha
        )
        if not paquetes:
            raise CommandError(f'No hay paquetes imagenes_* en {carpeta}.')

        def mostrar(porcentaje, etapa):
            self.stdout.write(f'[{int(porcentaje):3d}%] {etapa}')

        try:
            total = respaldos.restaurar_paquetes_de_imagenes(paquetes, progreso=mostrar)
        except respaldos.ErrorRespaldo as error:
            raise CommandError(str(error))
        self.stdout.write(self.style.SUCCESS(
            f'Se aplicaron {len(paquetes)} paquetes: {total} archivos restaurados en media/.'
        ))

from django.core.management.base import BaseCommand, CommandError

from accounts import respaldo_automatico, respaldos


class Command(BaseCommand):
    help = (
        'Crea ahora una copia de seguridad automática (prefijo auto_), la sube a Google Drive '
        'y borra las más antiguas pasando el límite. Es lo mismo que hace el sistema cada día '
        'a las 00:00; sirve para probarlo o para hacerla a mano.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--sin-archivos', action='store_true',
            help='Solo la base de datos (sin las imágenes e informes)',
        )

    def handle(self, *args, **opciones):
        def mostrar(porcentaje, etapa):
            self.stdout.write(f'[{int(porcentaje):3d}%] {etapa}')

        try:
            resumen = respaldo_automatico.ejecutar(
                mostrar, incluir_archivos=False if opciones['sin_archivos'] else None,
            )
        except respaldos.ErrorRespaldo as error:
            raise CommandError(str(error))
        self.stdout.write(self.style.SUCCESS(resumen['texto']))

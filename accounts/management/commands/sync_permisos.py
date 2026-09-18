from django.apps import apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Crea los tipos de contenido y permisos faltantes en las tablas '
        '"tipos_contenido" y "permisos". Se necesita porque la creación '
        'automática de Django (al final de cada migrate) quedó desactivada '
        '(ver accounts/apps.py) al renombrar esas tablas a español. Correr '
        'este comando cada vez que se agreguen modelos nuevos.'
    )

    def handle(self, *args, **options):
        for app_config in apps.get_app_configs():
            create_contenttypes(app_config, verbosity=1)
            create_permissions(app_config, verbosity=1)
        self.stdout.write(self.style.SUCCESS('Tipos de contenido y permisos sincronizados.'))

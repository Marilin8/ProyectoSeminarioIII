from django.core.management.base import BaseCommand

from pacientes.models import Combo


class Command(BaseCommand):
    help = (
        'Crea/actualiza el TipoEstudio espejo (modalidad "Combo") de cada combo del '
        'catálogo, para que se puedan agendar como un estudio más (ver '
        'Combo.sincronizar_tipo_estudio). Uso: manage.py sincronizar_combos'
    )

    def handle(self, *args, **options):
        combos = Combo.objects.all().prefetch_related('estudios')
        if not combos:
            self.stdout.write('No hay combos en el catálogo.')
            return
        for combo in combos:
            tipo_estudio = combo.sincronizar_tipo_estudio()
            self.stdout.write(self.style.SUCCESS(
                f'{combo.nombre} -> TipoEstudio #{tipo_estudio.id} ({tipo_estudio.nombre})'
            ))
        self.stdout.write(self.style.SUCCESS(f'{combos.count()} combo(s) sincronizado(s).'))

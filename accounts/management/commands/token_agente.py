"""Administra los tokens de las PCs que corren el agente de borrado.

    python manage.py token_agente crear "Rayos X sala 1"     (muestra el token UNA vez)
    python manage.py token_agente renovar "Rayos X sala 1"   (token nuevo, el viejo deja de servir)
    python manage.py token_agente revocar "Rayos X sala 1"
    python manage.py token_agente listar
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import AgenteEquipo


class Command(BaseCommand):
    help = 'Crea, renueva, revoca o lista los tokens del agente de borrado de las PCs.'

    def add_arguments(self, parser):
        parser.add_argument('accion', choices=['crear', 'renovar', 'revocar', 'listar'])
        parser.add_argument('nombre', nargs='?', help='Nombre de la PC')

    def handle(self, *args, accion, nombre=None, **options):
        if accion == 'listar':
            for a in AgenteEquipo.objects.all():
                uso = timezone.localtime(a.ultimo_uso).strftime('%d/%m/%Y %H:%M') if a.ultimo_uso else 'nunca'
                estado = 'activo' if a.activo else 'REVOCADO'
                self.stdout.write(f'{a.nombre:30} {estado:9} último uso: {uso} ({a.ultima_ip or "-"})')
            return
        if not nombre:
            raise CommandError('Falta el nombre de la PC.')

        if accion == 'crear':
            if AgenteEquipo.objects.filter(nombre=nombre).exists():
                raise CommandError(f'Ya existe "{nombre}". Use "renovar" para darle un token nuevo.')
            agente = AgenteEquipo(nombre=nombre)
            token = agente.generar_token()
            agente.save()
        else:
            agente = AgenteEquipo.objects.filter(nombre=nombre).first()
            if agente is None:
                raise CommandError(f'No existe "{nombre}".')
            if accion == 'revocar':
                agente.activo = False
                agente.save(update_fields=['activo'])
                self.stdout.write(self.style.SUCCESS(f'"{nombre}" revocado: su agente ya no puede consultar.'))
                return
            token = agente.generar_token()
            agente.activo = True
            agente.save(update_fields=['token_hash', 'activo'])

        self.stdout.write(self.style.SUCCESS(f'Token de "{nombre}" (cópielo ahora, no se vuelve a mostrar):'))
        self.stdout.write(token)

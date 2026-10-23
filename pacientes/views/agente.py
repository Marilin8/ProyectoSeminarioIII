"""API del agente de borrado que corre en las PCs que suben estudios.

El agente (agente_borrado/agente_borrado.ps1) calcula el SHA-256 de los
archivos de la carpeta de RadiAnt y pregunta aquí cuáles ya están guardados en
el sistema; solo esos los borra (o manda a la papelera) del disco local. La
respuesta devuelve únicamente huellas, nunca datos de pacientes.
"""
import json
import re

from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import AgenteEquipo, _ip_real_del_visitante

from ..models import ImagenEstudio

MAXIMO_HUELLAS_POR_CONSULTA = 1000
HUELLA_VALIDA = re.compile(r'^[0-9a-f]{64}$')


@csrf_exempt  # lo llama un programa con token, no un navegador con sesión
@require_POST
def confirmar_huellas(request):
    """Recibe ``{"huellas": [sha256, ...]}`` con el header
    ``Authorization: Bearer <token>`` y responde ``{"confirmadas": [...]}``:
    las huellas de imágenes que el sistema tiene guardadas.

    Solo se confirma si el archivo sigue en el servidor: el DICOM original o,
    si se subió un JPG, el JPG (que la radióloga puede haber descartado). Así
    el agente nunca borra la única copia que queda."""
    cabecera = request.headers.get('Authorization', '')
    token = cabecera[len('Bearer '):].strip() if cabecera.startswith('Bearer ') else ''
    agente = AgenteEquipo.autenticar(token)
    if agente is None:
        return JsonResponse({'error': 'token inválido o desactivado'}, status=401)

    try:
        huellas = json.loads(request.body or b'{}').get('huellas', [])
    except (ValueError, AttributeError):
        return JsonResponse({'error': 'JSON inválido'}, status=400)
    if not isinstance(huellas, list) or len(huellas) > MAXIMO_HUELLAS_POR_CONSULTA:
        return JsonResponse(
            {'error': f'"huellas" debe ser una lista de hasta {MAXIMO_HUELLAS_POR_CONSULTA}'}, status=400,
        )
    pedidas = {h.lower() for h in huellas if isinstance(h, str) and HUELLA_VALIDA.match(h.lower())}

    con_archivo = (Q(archivo_original__isnull=False) & ~Q(archivo_original='')) | ~Q(archivo='')
    confirmadas = set(
        ImagenEstudio.objects.filter(con_archivo, huella_sha256__in=pedidas)
        .values_list('huella_sha256', flat=True)
    ) if pedidas else set()

    AgenteEquipo.objects.filter(pk=agente.pk).update(
        ultimo_uso=timezone.now(), ultima_ip=_ip_real_del_visitante(request),
    )
    return JsonResponse({'confirmadas': sorted(confirmadas)})

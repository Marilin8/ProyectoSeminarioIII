import datetime
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.db import connection

from . import cifrado

NOMBRE_VALIDO = re.compile(r'^respaldo_\d{8}_\d{6}(_con_archivos)?\.zip(\.cif)?$')
LARGO_MINIMO_CLAVE = 16
TIMEOUT_DUMP_SEGUNDOS = 600


class ErrorRespaldo(Exception):
    pass


def clave_de_cifrado():
    """Clave configurada en el .env como bytes, o None si el cifrado está desactivado."""
    clave = (getattr(settings, 'RESPALDOS_CLAVE', '') or '').strip()
    if not clave:
        return None
    if len(clave) < LARGO_MINIMO_CLAVE:
        raise ErrorRespaldo(
            'La RESPALDOS_CLAVE del archivo .env es demasiado corta '
            f'(mínimo {LARGO_MINIMO_CLAVE} caracteres).'
        )
    return clave.encode('utf-8')


def carpeta_respaldos():
    carpeta = Path(getattr(settings, 'BACKUP_DIR', settings.BASE_DIR / 'respaldos'))
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def _ruta_mysqldump():
    configurada = getattr(settings, 'MYSQLDUMP_PATH', '')
    if configurada and Path(configurada).exists():
        return str(configurada)
    encontrada = shutil.which('mysqldump')
    if encontrada:
        return encontrada
    for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        if not base:
            continue
        for candidato in sorted(Path(base, 'MySQL').glob('*/bin/mysqldump.exe'), reverse=True):
            return str(candidato)
    raise ErrorRespaldo(
        'No se encontró mysqldump en el servidor. Instale MySQL Server/Client o '
        'defina MYSQLDUMP_PATH en el archivo .env.'
    )


def _volcar_base_de_datos(destino):
    db = connection.settings_dict
    comando = [
        _ruta_mysqldump(),
        f'--host={db["HOST"] or "127.0.0.1"}',
        f'--port={db["PORT"] or "3306"}',
        f'--user={db["USER"]}',
        '--single-transaction',
        '--routines',
        '--triggers',
        '--default-character-set=utf8mb4',
        f'--result-file={destino}',
        db['NAME'],
    ]
    # La contraseña va por variable de entorno y no como argumento para que
    # no quede visible en la lista de procesos del servidor.
    entorno = {**os.environ, 'MYSQL_PWD': str(db['PASSWORD'] or '')}
    try:
        resultado = subprocess.run(
            comando, env=entorno, capture_output=True, text=True,
            timeout=TIMEOUT_DUMP_SEGUNDOS,
        )
    except subprocess.TimeoutExpired:
        raise ErrorRespaldo('mysqldump tardó demasiado y se canceló.')
    if resultado.returncode != 0:
        detalle = (resultado.stderr or '').strip().splitlines()
        raise ErrorRespaldo(f'mysqldump falló: {detalle[-1] if detalle else "error desconocido"}')


def crear_respaldo(incluir_archivos=False):
    """Genera un respaldo en la carpeta de respaldos: un .zip con el volcado SQL
    de la base de datos y, si se pide, la carpeta media/ (imágenes e informes).
    Si hay RESPALDOS_CLAVE en el .env, el .zip se guarda cifrado (.zip.cif) y
    nunca queda una copia sin cifrar en la carpeta de respaldos.
    Devuelve el nombre del archivo creado."""
    clave = clave_de_cifrado()
    ahora = datetime.datetime.now()
    base = f'respaldo_{ahora:%Y%m%d_%H%M%S}{"_con_archivos" if incluir_archivos else ""}.zip'
    nombre = base + ('.cif' if clave else '')
    carpeta = carpeta_respaldos()
    final = carpeta / nombre
    parcial = carpeta / (nombre + '.parcial')

    try:
        with tempfile.TemporaryDirectory() as tmp:
            sql = Path(tmp) / 'base_de_datos.sql'
            _volcar_base_de_datos(sql)
            zip_plano = Path(tmp) / base
            with zipfile.ZipFile(zip_plano, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(sql, 'base_de_datos.sql')
                if incluir_archivos:
                    media = Path(settings.MEDIA_ROOT)
                    if media.exists():
                        for archivo in media.rglob('*'):
                            if archivo.is_file():
                                zf.write(archivo, Path('media') / archivo.relative_to(media))
            if clave:
                cifrado.cifrar_archivo(zip_plano, parcial, clave)
            else:
                shutil.copyfile(zip_plano, parcial)
        parcial.replace(final)
    except Exception:
        parcial.unlink(missing_ok=True)
        raise
    return nombre


def descifrar_a_archivo(nombre, destino):
    """Descifra un respaldo .cif en `destino` (ruta o archivo abierto)."""
    ruta = ruta_respaldo(nombre)
    if ruta is None or not nombre.endswith('.cif'):
        raise ErrorRespaldo('Ese respaldo no está cifrado o no existe.')
    clave = clave_de_cifrado()
    if clave is None:
        raise ErrorRespaldo('No hay RESPALDOS_CLAVE en el archivo .env: no se puede descifrar.')
    try:
        cifrado.descifrar_archivo(ruta, destino, clave)
    except cifrado.ErrorCifrado as error:
        raise ErrorRespaldo(str(error))


def listar_respaldos():
    carpeta = carpeta_respaldos()
    from .models import RespaldoEnNube
    en_nube = set(RespaldoEnNube.objects.values_list('nombre', flat=True))
    respaldos = []
    for ruta in carpeta.iterdir():
        if ruta.is_file() and NOMBRE_VALIDO.match(ruta.name):
            info = ruta.stat()
            respaldos.append({
                'nombre': ruta.name,
                'tamano': info.st_size,
                'fecha': datetime.datetime.fromtimestamp(info.st_mtime),
                'con_archivos': '_con_archivos' in ruta.name,
                'cifrado': ruta.name.endswith('.cif'),
                'en_nube': ruta.name in en_nube,
            })
    return sorted(respaldos, key=lambda r: r['fecha'], reverse=True)


def ruta_respaldo(nombre):
    """Ruta de un respaldo existente, o None. El nombre se valida contra un
    patrón estricto para que nunca pueda salirse de la carpeta de respaldos."""
    if not NOMBRE_VALIDO.match(nombre or ''):
        return None
    ruta = carpeta_respaldos() / nombre
    return ruta if ruta.is_file() else None

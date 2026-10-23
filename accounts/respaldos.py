"""Respaldos de la base de datos y de los archivos subidos (media).

``crear_respaldo`` vuelca MySQL con ``mysqldump`` a un ZIP (opcionalmente con
la carpeta media) y, si hay ``RESPALDOS_CLAVE`` en el .env, lo cifra
(``.zip.cif``, ver ``cifrado.py``). También lista, valida y restaura
respaldos (``restaurar``), y arma paquetes incrementales de imágenes.
Las pantallas que lo usan están en ``accounts.views`` (Respaldos) y el
trabajo corre en segundo plano vía ``tareas_respaldo``/``trabajos``.
"""
import datetime
import json
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

PREFIJO_AUTOMATICO = 'auto_'
# Paquetes incrementales de imágenes: solo los archivos de media/ nuevos o
# cambiados desde el paquete anterior. No entran en la rotación (borrar uno
# perdería esas imágenes): juntos, en orden, forman la copia de media/.
PREFIJO_IMAGENES = 'imagenes_'
NOMBRE_VALIDO = re.compile(r'^(respaldo|auto|imagenes)_\d{8}_\d{6}(_con_archivos)?\.zip(\.cif)?$')
# Qué archivos de media/ ya están en algún paquete: {ruta relativa: [tamaño, mtime_ns]}.
NOMBRE_INVENTARIO = 'inventario_imagenes.json'
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


def _ruta_mysql():
    """Cliente `mysql`, que vive junto a mysqldump."""
    dump = Path(_ruta_mysqldump())
    cliente = dump.with_name('mysql' + dump.suffix)
    if cliente.exists():
        return str(cliente)
    encontrada = shutil.which('mysql')
    if encontrada:
        return encontrada
    raise ErrorRespaldo('No se encontró el programa mysql en el servidor (viene con MySQL Server/Client).')


def _entorno_mysql():
    db = connection.settings_dict
    # La contraseña va por variable de entorno y no como argumento para que
    # no quede visible en la lista de procesos del servidor.
    return {**os.environ, 'MYSQL_PWD': str(db['PASSWORD'] or '')}


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


def crear_respaldo(incluir_archivos=False, progreso=None, prefijo='respaldo_'):
    """Genera un respaldo en la carpeta de respaldos: un .zip con el volcado SQL
    de la base de datos y, si se pide, la carpeta media/ (imágenes e informes).
    Si hay RESPALDOS_CLAVE en el .env, el .zip se guarda cifrado (.zip.cif) y
    nunca queda una copia sin cifrar en la carpeta de respaldos.
    `progreso(porcentaje, etapa)` es opcional. Devuelve el nombre del archivo."""
    def avisar(porcentaje, etapa):
        if progreso:
            progreso(porcentaje, etapa)

    clave = clave_de_cifrado()
    ahora = datetime.datetime.now()
    base = f'{prefijo}{ahora:%Y%m%d_%H%M%S}{"_con_archivos" if incluir_archivos else ""}.zip'
    nombre = base + ('.cif' if clave else '')
    carpeta = carpeta_respaldos()
    final = carpeta / nombre
    parcial = carpeta / (nombre + '.parcial')

    try:
        with tempfile.TemporaryDirectory() as tmp:
            avisar(5, 'Copiando la base de datos…')
            sql = Path(tmp) / 'base_de_datos.sql'
            _volcar_base_de_datos(sql)
            avisar(30, 'Comprimiendo…')
            zip_plano = Path(tmp) / base
            with zipfile.ZipFile(zip_plano, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(sql, 'base_de_datos.sql')
                if incluir_archivos:
                    media = Path(settings.MEDIA_ROOT)
                    archivos = [a for a in media.rglob('*') if a.is_file()] if media.exists() else []
                    for numero, archivo in enumerate(archivos, 1):
                        zf.write(archivo, Path('media') / archivo.relative_to(media))
                        avisar(30 + 45 * numero / len(archivos), 'Comprimiendo imágenes e informes…')
            if clave:
                avisar(75, 'Cifrando…')
                cifrado.cifrar_archivo(
                    zip_plano, parcial, clave,
                    progreso=lambda fraccion: avisar(75 + 20 * fraccion, 'Cifrando…'),
                )
            else:
                shutil.copyfile(zip_plano, parcial)
        avisar(96, 'Guardando el respaldo…')
        parcial.replace(final)
    except Exception:
        parcial.unlink(missing_ok=True)
        raise
    return nombre


def _leer_inventario():
    ruta = carpeta_respaldos() / NOMBRE_INVENTARIO
    try:
        return json.loads(ruta.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        # Sin inventario (primera vez, o se borró): el próximo paquete lleva
        # todas las imágenes. Es más grande, pero nunca deja nada afuera.
        return {}


def _guardar_inventario(inventario):
    ruta = carpeta_respaldos() / NOMBRE_INVENTARIO
    temporal = ruta.with_name(ruta.name + '.parcial')
    temporal.write_text(json.dumps(inventario), encoding='utf-8')
    temporal.replace(ruta)


def _archivos_de_media():
    """{ruta relativa con '/': [tamaño, mtime_ns]} de todo media/."""
    media = Path(settings.MEDIA_ROOT)
    if not media.exists():
        return {}
    archivos = {}
    for archivo in media.rglob('*'):
        if archivo.is_file():
            info = archivo.stat()
            archivos[archivo.relative_to(media).as_posix()] = [info.st_size, info.st_mtime_ns]
    return archivos


def crear_paquete_imagenes(progreso=None):
    """Copia incremental de media/ (imágenes, informes, comprobantes): un
    .zip(.cif) con solo los archivos nuevos o modificados desde el paquete
    anterior. La primera vez (sin inventario) lleva todo. Devuelve el nombre
    del paquete, o None si no había nada nuevo."""
    def avisar(porcentaje, etapa):
        if progreso:
            progreso(porcentaje, etapa)

    actuales = _archivos_de_media()
    anteriores = _leer_inventario()
    nuevos = sorted(ruta for ruta, firma in actuales.items() if anteriores.get(ruta) != firma)
    if not nuevos:
        return None

    clave = clave_de_cifrado()
    base = f'{PREFIJO_IMAGENES}{datetime.datetime.now():%Y%m%d_%H%M%S}.zip'
    nombre = base + ('.cif' if clave else '')
    carpeta = carpeta_respaldos()
    final = carpeta / nombre
    parcial = carpeta / (nombre + '.parcial')
    media = Path(settings.MEDIA_ROOT)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            zip_plano = Path(tmp) / base
            with zipfile.ZipFile(zip_plano, 'w', zipfile.ZIP_DEFLATED) as zf:
                for numero, relativa in enumerate(nuevos, 1):
                    try:
                        zf.write(media / relativa, f'media/{relativa}')
                    except FileNotFoundError:
                        actuales.pop(relativa, None)  # se borró mientras se armaba el paquete
                    avisar(70 * numero / len(nuevos), f'Comprimiendo imágenes nuevas ({numero} de {len(nuevos)})…')
            if clave:
                cifrado.cifrar_archivo(
                    zip_plano, parcial, clave,
                    progreso=lambda fraccion: avisar(70 + 28 * fraccion, 'Cifrando imágenes nuevas…'),
                )
            else:
                shutil.copyfile(zip_plano, parcial)
        parcial.replace(final)
    except Exception:
        parcial.unlink(missing_ok=True)
        raise
    # Recién con el paquete guardado se marcan como respaldadas.
    _guardar_inventario(actuales)
    avisar(100, 'Listo')
    return nombre


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
                'automatico': ruta.name.startswith(PREFIJO_AUTOMATICO),
                'imagenes': ruta.name.startswith(PREFIJO_IMAGENES),
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


# ---------------------------------------------------------------------------
# Restauración
# ---------------------------------------------------------------------------

def _abrir_zip_del_respaldo(ruta, tmp):
    """Devuelve la ruta de un .zip en claro: descifra si es un .zip.cif."""
    ruta = Path(ruta)
    if cifrado.es_sobre(ruta):
        clave = clave_de_cifrado()
        if clave is None:
            raise ErrorRespaldo('El archivo está cifrado y no hay RESPALDOS_CLAVE en el archivo .env.')
        plano = Path(tmp) / 'respaldo_descifrado.zip'
        try:
            cifrado.descifrar_archivo(ruta, plano, clave)
        except cifrado.ErrorCifrado as error:
            raise ErrorRespaldo(str(error))
        ruta = plano
    if not zipfile.is_zipfile(ruta):
        raise ErrorRespaldo('El archivo no es un respaldo válido (debe ser .zip o .zip.cif).')
    return ruta


def _extraer_y_validar(zip_path, tmp):
    """Comprueba que sea un respaldo de este sistema y deja el volcado SQL en
    disco. Devuelve (ruta del .sql, si trae archivos de media/)."""
    with zipfile.ZipFile(zip_path) as zf:
        nombres = zf.namelist()
        if 'base_de_datos.sql' not in nombres:
            raise ErrorRespaldo('El archivo no contiene la base de datos (base_de_datos.sql).')
        for nombre in nombres:
            partes = Path(nombre).parts
            if nombre.startswith(('/', '\\')) or '..' in partes or ':' in nombre:
                raise ErrorRespaldo('El respaldo contiene rutas no permitidas.')
            if nombre != 'base_de_datos.sql' and partes[0] != 'media':
                raise ErrorRespaldo('El respaldo contiene archivos que no corresponden a este sistema.')
        sql = Path(tmp) / 'restaurar.sql'
        with zf.open('base_de_datos.sql') as origen, open(sql, 'wb') as destino:
            shutil.copyfileobj(origen, destino, 1024 * 1024)
        hay_media = any(n.startswith('media/') and not n.endswith('/') for n in nombres)

    with open(sql, 'rb') as archivo:
        archivo.seek(max(sql.stat().st_size - 4096, 0))
        cola = archivo.read()
    if b'-- Dump completed' not in cola:
        raise ErrorRespaldo('El volcado de la base de datos está incompleto o dañado.')
    with open(sql, 'rb') as archivo:
        if b'CREATE TABLE' not in archivo.read(8 * 1024 * 1024):
            raise ErrorRespaldo('El archivo no parece un respaldo de la base de datos de este sistema.')
    return sql, hay_media


def _es_paquete_de_imagenes(zip_path):
    """¿Es un paquete incremental (solo media/, sin base de datos)? Valida las rutas."""
    with zipfile.ZipFile(zip_path) as zf:
        nombres = zf.namelist()
    if not nombres or 'base_de_datos.sql' in nombres:
        return False
    for nombre in nombres:
        partes = Path(nombre).parts
        if nombre.startswith(('/', '\\')) or '..' in partes or ':' in nombre or partes[0] != 'media':
            raise ErrorRespaldo('El archivo no es un respaldo válido de este sistema.')
    return True


def restaurar_paquetes_de_imagenes(rutas, progreso=None):
    """Aplica, en orden, paquetes incrementales de imágenes (del más antiguo al más
    nuevo): así cada archivo queda en su última versión. Devuelve cuántos archivos
    se escribieron."""
    total = 0
    rutas = list(rutas)
    for numero, ruta in enumerate(rutas, 1):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = _abrir_zip_del_respaldo(ruta, tmp)
            if not _es_paquete_de_imagenes(zip_path):
                raise ErrorRespaldo(f'{Path(ruta).name} no es un paquete de imágenes.')
            total += _restaurar_archivos_media(zip_path)
        if progreso:
            progreso(100 * numero / len(rutas), f'Paquete {numero} de {len(rutas)}: {Path(ruta).name}')
    return total


def _vaciar_base_de_datos():
    """Borra todas las tablas actuales para cargar el respaldo en limpio (así
    no quedan tablas ni datos de una versión más nueva mezclados con la vieja)."""
    with connection.cursor() as cursor:
        cursor.execute('SET FOREIGN_KEY_CHECKS=0')
        try:
            for tabla in connection.introspection.table_names(cursor):
                cursor.execute('DROP TABLE IF EXISTS `%s`' % tabla.replace('`', '``'))
        finally:
            cursor.execute('SET FOREIGN_KEY_CHECKS=1')


def _cargar_sql(sql, progreso=None):
    db = connection.settings_dict
    comando = [
        _ruta_mysql(),
        f'--host={db["HOST"] or "127.0.0.1"}',
        f'--port={db["PORT"] or "3306"}',
        f'--user={db["USER"]}',
        '--default-character-set=utf8mb4',
        db['NAME'],
    ]
    total = max(Path(sql).stat().st_size, 1)
    enviados = 0
    proceso = subprocess.Popen(
        comando, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=_entorno_mysql(),
    )
    try:
        with open(sql, 'rb') as archivo:
            for bloque in iter(lambda: archivo.read(1024 * 1024), b''):
                proceso.stdin.write(bloque)
                enviados += len(bloque)
                if progreso:
                    progreso(enviados / total)
        proceso.stdin.close()
    except (BrokenPipeError, OSError):
        pass  # mysql abortó por un error: el detalle sale en stderr
    try:
        _, error = proceso.communicate(timeout=TIMEOUT_DUMP_SEGUNDOS)
    except subprocess.TimeoutExpired:
        proceso.kill()
        raise ErrorRespaldo('La carga de la base de datos tardó demasiado y se canceló.')
    if proceso.returncode != 0:
        detalle = error.decode('utf-8', errors='replace').strip().splitlines()
        raise ErrorRespaldo(f'mysql falló: {detalle[-1] if detalle else "error desconocido"}')


def _restaurar_archivos_media(zip_path, progreso=None):
    media = Path(settings.MEDIA_ROOT).resolve()
    with zipfile.ZipFile(zip_path) as zf:
        miembros = [n for n in zf.namelist() if n.startswith('media/') and not n.endswith('/')]
        for numero, miembro in enumerate(miembros, 1):
            destino = (media / Path(miembro).relative_to('media')).resolve()
            if media != destino and media not in destino.parents:
                raise ErrorRespaldo('El respaldo contiene rutas no permitidas.')
            destino.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(miembro) as origen, open(destino, 'wb') as salida:
                shutil.copyfileobj(origen, salida, 1024 * 1024)
            if progreso:
                progreso(numero / len(miembros))
    return len(miembros)


def restaurar(ruta_subida, *, restaurar_archivos=True, progreso=None):
    """Reemplaza TODA la información actual por la de un respaldo (.zip o
    .zip.cif) subido por el administrador. Antes de tocar nada verifica el
    archivo y guarda un respaldo de seguridad del estado actual; si algo
    falla a mitad, devuelve la base de datos a como estaba.
    Devuelve (nombre del respaldo de seguridad, cantidad de archivos restaurados)."""
    from django.core.management import call_command

    def avisar(porcentaje, etapa):
        if progreso:
            progreso(porcentaje, etapa)

    with tempfile.TemporaryDirectory() as tmp:
        avisar(3, 'Verificando el archivo…')
        zip_path = _abrir_zip_del_respaldo(ruta_subida, tmp)
        if _es_paquete_de_imagenes(zip_path):
            # Paquete incremental: solo agrega/reemplaza archivos de media/; la base
            # de datos no se toca, así que no hace falta respaldo de seguridad.
            archivos = _restaurar_archivos_media(
                zip_path, lambda f: avisar(5 + 90 * f, 'Restaurando imágenes e informes…'),
            )
            return None, archivos
        sql, hay_media = _extraer_y_validar(zip_path, tmp)

        avisar(10, 'Guardando un respaldo de seguridad del estado actual…')
        seguridad = crear_respaldo(
            incluir_archivos=False,
            progreso=lambda p, e: avisar(10 + p * 0.2, f'Respaldo de seguridad: {e}'),
        )

        avisar(32, 'Borrando los datos actuales…')
        archivos = 0
        try:
            _vaciar_base_de_datos()
            _cargar_sql(sql, lambda f: avisar(35 + 45 * f, 'Cargando la base de datos…'))
            if restaurar_archivos and hay_media:
                archivos = _restaurar_archivos_media(
                    zip_path, lambda f: avisar(80 + 8 * f, 'Restaurando imágenes e informes…'),
                )
            avisar(90, 'Actualizando la estructura de la base de datos…')
            call_command('migrate', interactive=False, verbosity=0)
        except Exception as error:
            avisar(92, 'Falló la restauración: devolviendo los datos a como estaban…')
            try:
                sql_anterior, _ = _extraer_y_validar(
                    _abrir_zip_del_respaldo(ruta_respaldo(seguridad), tmp), tmp,
                )
                _vaciar_base_de_datos()
                _cargar_sql(sql_anterior)
            except Exception as error_deshacer:
                raise ErrorRespaldo(
                    f'La restauración falló ({error}) y tampoco se pudo devolver el estado anterior '
                    f'({error_deshacer}). Sus datos están a salvo en el respaldo {seguridad}: '
                    'restáurelo desde la carpeta de respaldos del servidor.'
                )
            raise ErrorRespaldo(
                f'La restauración falló ({error}). Se devolvió la información a como estaba antes; '
                'no se perdió nada.'
            )
    return seguridad, archivos

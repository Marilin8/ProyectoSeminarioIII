"""Cifrado de respaldos: AES-256-GCM con la clave del archivo .env.

Formato del archivo cifrado ("sobre"):
    MAGIA | versión (1 byte) | sal (16) | nonce (12) | datos cifrados | etiqueta GCM (16)
La cabecera queda autenticada: si alguien altera el archivo, o la clave no es
la correcta, el descifrado falla en vez de entregar basura. Se procesa por
bloques de 1 MB para no cargar respaldos grandes en memoria.
"""
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIA = b'CIME-RESPALDO\x00'
VERSION_SOBRE = 1
LARGO_SAL, LARGO_NONCE, LARGO_ETIQUETA = 16, 12, 16
LARGO_CABECERA = len(MAGIA) + 1 + LARGO_SAL + LARGO_NONCE
ITERACIONES_CLAVE = 200_000
BLOQUE = 1024 * 1024


class ErrorCifrado(Exception):
    pass


def _derivar_clave(clave, sal):
    return hashlib.pbkdf2_hmac('sha256', clave, sal, ITERACIONES_CLAVE, dklen=32)


def es_sobre(ruta):
    with open(ruta, 'rb') as archivo:
        return archivo.read(len(MAGIA)) == MAGIA


def cifrar_archivo(ruta_entrada, ruta_salida, clave, progreso=None):
    sal, nonce = os.urandom(LARGO_SAL), os.urandom(LARGO_NONCE)
    cabecera = MAGIA + bytes([VERSION_SOBRE]) + sal + nonce
    cifrador = Cipher(algorithms.AES(_derivar_clave(clave, sal)), modes.GCM(nonce)).encryptor()
    cifrador.authenticate_additional_data(cabecera)
    total = max(os.path.getsize(ruta_entrada), 1)
    leido = 0
    with open(ruta_entrada, 'rb') as origen, open(ruta_salida, 'wb') as destino:
        destino.write(cabecera)
        for bloque in iter(lambda: origen.read(BLOQUE), b''):
            destino.write(cifrador.update(bloque))
            leido += len(bloque)
            if progreso:
                progreso(min(leido / total, 1.0))
        destino.write(cifrador.finalize())
        destino.write(cifrador.tag)


def descifrar_archivo(ruta, ruta_salida, clave):
    """Descifra `ruta` en `ruta_salida` (ruta o archivo binario abierto).
    Falla si la clave no corresponde o si el archivo fue modificado."""
    total = os.path.getsize(ruta)
    if total < LARGO_CABECERA + LARGO_ETIQUETA:
        raise ErrorCifrado('El archivo de respaldo está incompleto o dañado.')
    with open(ruta, 'rb') as origen:
        cabecera = origen.read(LARGO_CABECERA)
        if cabecera[:len(MAGIA)] != MAGIA:
            raise ErrorCifrado('El archivo no es un respaldo cifrado.')
        if cabecera[len(MAGIA)] != VERSION_SOBRE:
            raise ErrorCifrado('Formato de respaldo no reconocido.')
        sal = cabecera[len(MAGIA) + 1:len(MAGIA) + 1 + LARGO_SAL]
        nonce = cabecera[-LARGO_NONCE:]
        origen.seek(total - LARGO_ETIQUETA)
        etiqueta = origen.read(LARGO_ETIQUETA)
        origen.seek(LARGO_CABECERA)
        descifrador = Cipher(
            algorithms.AES(_derivar_clave(clave, sal)), modes.GCM(nonce, etiqueta),
        ).decryptor()
        descifrador.authenticate_additional_data(cabecera)

        abierto_aqui = isinstance(ruta_salida, (str, os.PathLike))
        destino = open(ruta_salida, 'wb') if abierto_aqui else ruta_salida
        try:
            pendiente = total - LARGO_CABECERA - LARGO_ETIQUETA
            while pendiente:
                bloque = origen.read(min(BLOQUE, pendiente))
                if not bloque:
                    raise ErrorCifrado('El archivo de respaldo está incompleto o dañado.')
                destino.write(descifrador.update(bloque))
                pendiente -= len(bloque)
            destino.write(descifrador.finalize())
        except InvalidTag:
            raise ErrorCifrado(
                'La clave no corresponde a este respaldo, o el archivo fue modificado o está dañado.'
            ) from None
        except ErrorCifrado:
            raise
        finally:
            if abierto_aqui:
                destino.close()

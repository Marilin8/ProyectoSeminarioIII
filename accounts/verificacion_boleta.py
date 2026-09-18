"""Verificación del comprobante de pago de planilla.

Lee por OCR el comprobante subido (foto de la boleta de depósito o
captura de la transferencia) e intenta sacar el **número de boleta /
referencia** y el **monto depositado**, para compararlos con lo que se
está pagando en la planilla. Sirve para evitar que se registre un pago
por una cantidad distinta a la que realmente se depositó.

Uso como programa suelto:

    python -m accounts.verificacion_boleta boleta.jpg --monto 3134.00 --numero 123456

El OCR usa Tesseract a través de `pytesseract`. Si Tesseract no está
instalado, la verificación devuelve estado ``no_verificable`` (no
rompe: el pago se puede registrar igual, pero queda marcado como no
verificado). En Windows se instala desde:
https://github.com/UB-Mannheim/tesseract/wiki  (idioma español incluido).
Si el .exe no queda en el PATH, apuntá a él con la variable de entorno
``TESSERACT_CMD``.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

TOLERANCIA = Decimal('0.01')

ESTADO_COINCIDE = 'coincide'
ESTADO_NO_COINCIDE = 'no_coincide'
ESTADO_NO_VERIFICABLE = 'no_verificable'

# Palabras que suelen preceder al número de boleta / referencia en una
# boleta de depósito o en el comprobante de una transferencia.
_ETIQUETAS_NUMERO = (
    r'boleta', r'no\.?', r'nro\.?', r'n[uú]m(?:ero)?\.?', r'referencia', r'ref\.?',
    r'documento', r'doc\.?', r'autorizaci[oó]n', r'auth', r'transacci[oó]n', r'operaci[oó]n',
    r'comprobante',
)
_RE_NUMERO = re.compile(
    r'(?:' + r'|'.join(_ETIQUETAS_NUMERO) + r')\s*[:#\-]?\s*([0-9][0-9\-]{3,})',
    re.IGNORECASE,
)
# Montos tipo 1,234.56 / 1.234,56 / 1234.56 / Q 1,234.56
_RE_MONTO = re.compile(
    r'(?<![\d.,])(?:Q|GTQ|\$)?\s*'
    r'(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})|\d+[.,]\d{2})'
    r'(?![\d])',
)


@dataclass
class ResultadoVerificacion:
    estado: str
    monto_esperado: Decimal
    numero_esperado: str = ''
    monto_detectado: Decimal | None = None
    numero_detectado: str | None = None
    montos_detectados: list = field(default_factory=list)
    numeros_detectados: list = field(default_factory=list)
    monto_coincide: bool | None = None
    numero_coincide: bool | None = None
    mensaje: str = ''
    texto_ocr: str = ''

    @property
    def ok(self) -> bool:
        return self.estado == ESTADO_COINCIDE

    def resumen(self) -> str:
        if self.estado == ESTADO_NO_VERIFICABLE:
            return self.mensaje or 'No se pudo leer el comprobante automáticamente.'
        partes = []
        if self.monto_coincide is True:
            partes.append(f'monto Q{self.monto_esperado} confirmado')
        elif self.monto_coincide is False:
            detectado = f'Q{self.monto_detectado}' if self.monto_detectado is not None else 'no encontrado'
            partes.append(f'monto NO coincide (esperado Q{self.monto_esperado}, en la boleta: {detectado})')
        if self.numero_esperado:
            if self.numero_coincide is True:
                partes.append(f'número de boleta {self.numero_esperado} confirmado')
            elif self.numero_coincide is False:
                partes.append(f'número de boleta NO coincide (esperado {self.numero_esperado})')
        return '; '.join(partes) if partes else 'Sin datos para comparar.'


# --------------------------------------------------------------------------
# OCR
# --------------------------------------------------------------------------
def _leer_texto(contenido: bytes, nombre: str = '') -> str | None:
    """Devuelve el texto del comprobante, o None si no se pudo hacer OCR
    (Tesseract no instalado, PDF sin soporte, imagen ilegible)."""
    if nombre.lower().endswith('.pdf'):
        # Los PDF requieren pdf2image/poppler; no es una dependencia del
        # proyecto, así que se deja para revisión manual.
        return None
    try:
        import pytesseract
        from PIL import Image, ImageOps
    except ImportError:
        return None

    cmd = os.environ.get('TESSERACT_CMD')
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    try:
        imagen = Image.open(io.BytesIO(contenido))
        imagen = ImageOps.exif_transpose(imagen).convert('L')
        # Un poco de contraste ayuda con fotos de boletas.
        imagen = ImageOps.autocontrast(imagen)
        try:
            texto = pytesseract.image_to_string(imagen, lang='spa')
        except pytesseract.pytesseract.TesseractError:
            texto = pytesseract.image_to_string(imagen)
        return texto
    except (OSError, ValueError):
        return None
    except Exception:  # pytesseract.TesseractNotFoundError y afines
        return None


# --------------------------------------------------------------------------
# Parseo
# --------------------------------------------------------------------------
def _a_decimal(texto_monto: str) -> Decimal | None:
    limpio = texto_monto.strip()
    if ',' in limpio and '.' in limpio:
        # El último separador es el decimal.
        if limpio.rfind(',') > limpio.rfind('.'):
            limpio = limpio.replace('.', '').replace(',', '.')
        else:
            limpio = limpio.replace(',', '')
    elif ',' in limpio:
        entero, _, resto = limpio.rpartition(',')
        limpio = f'{entero.replace(",", "")}.{resto}' if len(resto) == 2 else limpio.replace(',', '')
    try:
        return Decimal(limpio).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


def extraer_montos(texto: str) -> list[Decimal]:
    montos = []
    for bruto in _RE_MONTO.findall(texto or ''):
        valor = _a_decimal(bruto)
        if valor is not None and valor > 0 and valor not in montos:
            montos.append(valor)
    return montos


def extraer_numeros(texto: str) -> list[str]:
    numeros = []
    for bruto in _RE_NUMERO.findall(texto or ''):
        limpio = bruto.replace('-', '')
        if limpio and limpio not in numeros:
            numeros.append(limpio)
    return numeros


def _numeros_iguales(esperado: str, detectado: str) -> bool:
    a = re.sub(r'\D', '', esperado or '')
    b = re.sub(r'\D', '', detectado or '')
    if not a or not b:
        return False
    return a == b or a.endswith(b) or b.endswith(a)


# --------------------------------------------------------------------------
# API principal
# --------------------------------------------------------------------------
def verificar(contenido: bytes, monto_esperado, numero_esperado: str = '',
              nombre_archivo: str = '') -> ResultadoVerificacion:
    """Compara el comprobante (`contenido` = bytes de la imagen) contra el
    `monto_esperado` (y opcionalmente el `numero_esperado` de boleta)."""
    monto_esperado = Decimal(str(monto_esperado)).quantize(Decimal('0.01'))
    numero_esperado = (numero_esperado or '').strip()

    texto = _leer_texto(contenido, nombre_archivo)
    if texto is None:
        return ResultadoVerificacion(
            estado=ESTADO_NO_VERIFICABLE,
            monto_esperado=monto_esperado,
            numero_esperado=numero_esperado,
            mensaje=(
                'No se pudo leer el comprobante automáticamente '
                '(Tesseract no está instalado o el archivo es un PDF/imagen ilegible). '
                'Verificá los datos a mano.'
            ),
        )

    montos = extraer_montos(texto)
    numeros = extraer_numeros(texto)

    monto_coincide = any(abs(m - monto_esperado) <= TOLERANCIA for m in montos)
    monto_detectado = next(
        (m for m in montos if abs(m - monto_esperado) <= TOLERANCIA),
        max(montos) if montos else None,
    )

    numero_coincide = None
    numero_detectado = None
    if numero_esperado:
        for n in numeros:
            if _numeros_iguales(numero_esperado, n):
                numero_coincide, numero_detectado = True, n
                break
        else:
            # Búsqueda laxa en todo el texto, por si la etiqueta no matcheó.
            solo_digitos = re.sub(r'\D', '', numero_esperado)
            numero_coincide = bool(solo_digitos) and solo_digitos in re.sub(r'[^\d]', '', texto)

    problema = (monto_coincide is False) or (numero_coincide is False)
    resultado = ResultadoVerificacion(
        estado=ESTADO_NO_COINCIDE if problema else ESTADO_COINCIDE,
        monto_esperado=monto_esperado,
        numero_esperado=numero_esperado,
        monto_detectado=monto_detectado,
        numero_detectado=numero_detectado,
        montos_detectados=montos,
        numeros_detectados=numeros,
        monto_coincide=monto_coincide,
        numero_coincide=numero_coincide,
        texto_ocr=texto,
    )
    resultado.mensaje = resultado.resumen()
    return resultado


def verificar_archivo(ruta: str, monto_esperado, numero_esperado: str = '') -> ResultadoVerificacion:
    with open(ruta, 'rb') as fh:
        return verificar(fh.read(), monto_esperado, numero_esperado, nombre_archivo=ruta)


def _main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description='Verifica el número de boleta y el monto de un comprobante de pago.',
    )
    parser.add_argument('imagen', help='Ruta de la foto de la boleta / transferencia (JPG o PNG).')
    parser.add_argument('--monto', required=True, help='Monto que se debería haber depositado, ej. 3134.00')
    parser.add_argument('--numero', default='', help='Número de boleta / referencia esperado (opcional).')
    parser.add_argument('--texto', action='store_true', help='Muestra también el texto que leyó el OCR.')
    args = parser.parse_args(argv)

    resultado = verificar_archivo(args.imagen, args.monto, args.numero)

    print(f'Estado:            {resultado.estado}')
    print(f'Monto esperado:    Q{resultado.monto_esperado}')
    print(f'Montos detectados: {", ".join(f"Q{m}" for m in resultado.montos_detectados) or "(ninguno)"}')
    if args.numero:
        print(f'Número esperado:   {resultado.numero_esperado}')
        print(f'Números detectados:{", ".join(resultado.numeros_detectados) or " (ninguno)"}')
    print(f'Resultado:         {resultado.mensaje}')
    if args.texto:
        print('\n--- texto OCR ---')
        print(resultado.texto_ocr)

    return 0 if resultado.estado != ESTADO_NO_COINCIDE else 1


if __name__ == '__main__':
    import sys

    sys.exit(_main())

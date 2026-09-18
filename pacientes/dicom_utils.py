import io

import numpy as np
import pydicom
from django.core.files.base import ContentFile
from PIL import Image


def dicom_a_jpg_memoria(archivo_subido):
    """Recibe un objeto UploadedFile de Django, procesa la imagen DICOM
    aplicando Unidades Hounsfield y Ventaneo Médico, y retorna un
    ContentFile en JPG.

    Portado de la rama Andres de TechBlood/ProyectoSeminarioClinica
    (pacientes/dicom_utils.py)."""
    try:
        # force=True: muchos equipos (sobre todo los que exportan archivos
        # sin extensión, tipo I0, I102...) generan DICOM sin el preámbulo
        # de 128 bytes ni el prefijo "DICM" — pydicom los rechaza por
        # defecto aunque el contenido sea válido. Con force=True igual los
        # lee, asumiendo Implicit VR Little Endian si no trae file_meta.
        ds = pydicom.dcmread(archivo_subido, force=True)
        matriz = ds.pixel_array.astype(float)

        # 1. Convertir a Unidades Hounsfield (HU) reales
        slope = getattr(ds, 'RescaleSlope', 1)
        intercept = getattr(ds, 'RescaleIntercept', 0)
        matriz = matriz * slope + intercept

        # 2. Obtener valores de ventana (Window Center / Width)
        window_center = getattr(ds, 'WindowCenter', None)
        window_width = getattr(ds, 'WindowWidth', None)

        if isinstance(window_center, pydicom.multival.MultiValue):
            window_center = window_center[0]
        if isinstance(window_width, pydicom.multival.MultiValue):
            window_width = window_width[0]

        # 3. Aplicar contraste médico (Ventaneo)
        if window_center is not None and window_width is not None:
            img_min = float(window_center) - (float(window_width) / 2)
            img_max = float(window_center) + (float(window_width) / 2)
            matriz = np.clip(matriz, img_min, img_max)
        else:
            # Respaldo automático: ajusta al percentil 1% y 99%
            p_low, p_high = np.percentile(matriz, (1, 99))
            matriz = np.clip(matriz, p_low, p_high)

        # 4. Normalizar a escala de grises 8-bits (0 - 255)
        rango = matriz.max() - matriz.min()
        if rango == 0:
            rango = 1
        matriz_normalizada = (matriz - matriz.min()) / rango * 255.0
        matriz_8bits = matriz_normalizada.astype(np.uint8)

        # 5. Invertir colores si la interpretación fotométrica es MONOCHROME1
        if getattr(ds, 'PhotometricInterpretation', '') == 'MONOCHROME1':
            matriz_8bits = 255 - matriz_8bits

        # 6. Convertir a objeto PIL y exportar a buffer en memoria
        imagen = Image.fromarray(matriz_8bits)
        if imagen.mode != 'RGB':
            imagen = imagen.convert('RGB')

        buffer = io.BytesIO()
        imagen.save(buffer, format='JPEG', quality=92)

        # Extraer nombre limpio (compatible con archivos tipo 'I0' o '.dcm')
        nombre_raw = archivo_subido.name.split('/')[-1].split('\\')[-1]
        nombre_base = nombre_raw.rsplit('.', 1)[0] if '.' in nombre_raw else nombre_raw
        nombre_jpg = f"{nombre_base}.jpg"

        return ContentFile(buffer.getvalue(), name=nombre_jpg)

    except Exception:
        # Retorna None si el archivo procesado no es un contenedor DICOM válido
        return None

"""Genera docs/Documentacion_Sistema_Clinica.pdf.

La parte narrativa (arquitectura, flujos, despliegue) está escrita aquí; las
tablas de módulos, modelos, URLs y funciones se sacan del código en el momento
(docstrings), así el PDF se puede regenerar cuando el código cambie:

    venv\\Scripts\\python docs\\generar_pdf.py

Usa ``clinica.settings_test`` solo para cargar Django (no toca la base de datos).
"""
import ast
import datetime
import inspect
import os
import pathlib
import re
import sys
from xml.sax.saxutils import escape

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'clinica.settings_test')

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.urls import URLPattern, URLResolver, get_resolver  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents  # noqa: E402

SALIDA = RAIZ / 'docs' / 'Documentacion_Sistema_Clinica.pdf'

# ---------------------------------------------------------------- estilos

FUENTES = pathlib.Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
try:
    pdfmetrics.registerFont(TTFont('Texto', str(FUENTES / 'segoeui.ttf')))
    pdfmetrics.registerFont(TTFont('Texto-Negrita', str(FUENTES / 'segoeuib.ttf')))
    pdfmetrics.registerFont(TTFont('Texto-Cursiva', str(FUENTES / 'segoeuii.ttf')))
    pdfmetrics.registerFont(TTFont('Texto-NegritaCursiva', str(FUENTES / 'segoeuiz.ttf')))
    pdfmetrics.registerFont(TTFont('Codigo', str(FUENTES / 'consola.ttf')))
    pdfmetrics.registerFontFamily(
        'Texto', normal='Texto', bold='Texto-Negrita', italic='Texto-Cursiva', boldItalic='Texto-NegritaCursiva',
    )
    BASE, NEGRITA, CODIGO = 'Texto', 'Texto-Negrita', 'Codigo'
except Exception:  # sin las fuentes de Windows: las estándar de PDF
    BASE, NEGRITA, CODIGO = 'Helvetica', 'Helvetica-Bold', 'Courier'

MORADO = colors.HexColor('#5B21B6')
MORADO_CLARO = colors.HexColor('#EDE9FE')
GRIS = colors.HexColor('#F3F4F6')

_e = getSampleStyleSheet()
E = {
    'titulo': ParagraphStyle('titulo', parent=_e['Title'], fontName=NEGRITA, fontSize=26, leading=32,
                             textColor=MORADO, spaceAfter=18),
    'subtitulo': ParagraphStyle('subtitulo', parent=_e['Normal'], fontName=BASE, fontSize=13, leading=18,
                                alignment=TA_CENTER, textColor=colors.HexColor('#374151')),
    'h1': ParagraphStyle('h1', parent=_e['Heading1'], fontName=NEGRITA, fontSize=18, leading=22,
                         textColor=MORADO, spaceBefore=6, spaceAfter=10),
    'h2': ParagraphStyle('h2', parent=_e['Heading2'], fontName=NEGRITA, fontSize=13.5, leading=17,
                         textColor=colors.HexColor('#4C1D95'), spaceBefore=10, spaceAfter=6),
    'h3': ParagraphStyle('h3', parent=_e['Heading3'], fontName=NEGRITA, fontSize=11, leading=14,
                         spaceBefore=8, spaceAfter=4),
    'p': ParagraphStyle('p', parent=_e['BodyText'], fontName=BASE, fontSize=9.6, leading=13.4, spaceAfter=5),
    'vi': ParagraphStyle('vi', parent=_e['BodyText'], fontName=BASE, fontSize=9.6, leading=13.4,
                         leftIndent=12, bulletIndent=2, spaceAfter=2),
    'celda': ParagraphStyle('celda', parent=_e['BodyText'], fontName=BASE, fontSize=7.8, leading=9.8),
    'celda_cod': ParagraphStyle('celda_cod', parent=_e['BodyText'], fontName=CODIGO, fontSize=7.2, leading=9.2),
    'cab': ParagraphStyle('cab', parent=_e['BodyText'], fontName=NEGRITA, fontSize=8, leading=10,
                          textColor=colors.white),
    'codigo': ParagraphStyle('codigo', parent=_e['Code'], fontName=CODIGO, fontSize=8, leading=10.5,
                             backColor=GRIS, borderPadding=5, leftIndent=6, rightIndent=6, spaceAfter=8),
    'toc1': ParagraphStyle('toc1', fontName=NEGRITA, fontSize=10.5, leading=15, leftIndent=10),
    'toc2': ParagraphStyle('toc2', fontName=BASE, fontSize=9.3, leading=12.5, leftIndent=26),
}


def P(texto, estilo='p'):
    return Paragraph(texto, E[estilo])


def vinetas(items):
    return [Paragraph(t, E['vi'], bulletText='•') for t in items]


def cod(texto):
    return Preformatted(texto.strip('\n'), E['codigo'])


def doc_html(texto):
    """Texto de un docstring a marcado de ReportLab: escapa y muestra ``así`` en fuente de código."""
    return re.sub(r'``(.+?)``', lambda m: f'<font face="{CODIGO}">{m.group(1)}</font>', escape(str(texto)))


def c(texto, estilo='celda'):
    return Paragraph(doc_html(texto).replace('\n', '<br/>'), E[estilo])


def tabla(cabeceras, filas, anchos, estilos_col=None):
    estilos_col = estilos_col or ['celda'] * len(cabeceras)
    datos = [[Paragraph(h, E['cab']) for h in cabeceras]]
    for f in filas:
        datos.append([v if hasattr(v, 'wrap') else c(v, estilos_col[i]) for i, v in enumerate(f)])
    t = Table(datos, colWidths=anchos, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), MORADO),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, GRIS]),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#D1D5DB')),
        ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
    ]))
    return t


def primer_parrafo(doc):
    return (doc or '').strip().split('\n\n')[0].replace('\n', ' ')


# ------------------------------------------------------- datos del código

def recorrer_urls(resolver=None, prefijo=''):
    resolver = resolver or get_resolver()
    for p in resolver.url_patterns:
        if isinstance(p, URLResolver):
            if 'admin' in str(p.pattern):
                continue
            yield from recorrer_urls(p, prefijo + str(p.pattern))
        elif isinstance(p, URLPattern):
            real = p.callback
            while hasattr(real, '__wrapped__'):
                real = real.__wrapped__
            yield {
                'ruta': '/' + prefijo + str(p.pattern), 'nombre': p.name or '',
                'modulo': real.__module__, 'vista': real.__name__, 'doc': inspect.getdoc(real) or '',
            }


def modulos_de(base):
    res = []
    for p in sorted(pathlib.Path(base).rglob('*.py')):
        partes = p.parts
        if 'migrations' in partes or p.name.startswith('test') or p.name == 'tests.py':
            continue
        if p.name == '__init__.py' and p.parent.name != 'views':
            continue
        src = p.read_text(encoding='utf-8')
        arbol = ast.parse(src)
        funciones = [
            (n.name, 'clase' if isinstance(n, ast.ClassDef) else 'función', ast.get_docstring(n) or '')
            for n in arbol.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
        ]
        res.append({'ruta': str(p).replace('\\', '/'), 'lineas': src.count('\n'),
                    'doc': ast.get_docstring(arbol) or '', 'funciones': funciones})
    return res


# ------------------------------------------------------------- documento

class Documento(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name in ('h1', 'h2'):
            nivel = 0 if flowable.style.name == 'h1' else 1
            texto = flowable.getPlainText()
            clave = f'h{id(flowable)}'
            self.canv.bookmarkPage(clave)
            self.canv.addOutlineEntry(texto, clave, level=nivel, closed=nivel > 0)
            self.notify('TOCEntry', (nivel, texto, self.page, clave))


def pie(canvas, doc):
    canvas.saveState()
    canvas.setFont(BASE, 7.5)
    canvas.setFillColor(colors.HexColor('#6B7280'))
    canvas.drawString(2 * cm, 1.2 * cm, 'Sistema Clínica de Imágenes — Documentación técnica')
    canvas.drawRightString(letter[0] - 2 * cm, 1.2 * cm, f'Página {doc.page}')
    canvas.restoreState()


def construir():
    hoy = datetime.date.today()
    urls = list(recorrer_urls())
    h = []

    # Portada
    h += [Spacer(1, 5 * cm), P('Sistema de Gestión<br/>Clínica de Imágenes Médicas', 'titulo'),
          P('Documentación técnica del proyecto Django', 'subtitulo'), Spacer(1, 0.6 * cm),
          P(f'Carpeta en producción: <b>seminario subida</b> (rama <b>Elmer</b>)<br/>'
            f'Sitio: clinica.cimeimagenes.com · Waitress :8005 + Cloudflare Tunnel<br/>'
            f'Generado el {hoy.strftime("%d/%m/%Y")}', 'subtitulo'),
          PageBreak()]

    toc = TableOfContents()
    toc.levelStyles = [E['toc1'], E['toc2']]
    h += [Paragraph('Contenido', ParagraphStyle('contenido', parent=E['h1'])), toc, PageBreak()]

    # 1. Visión general
    h += [P('1. Visión general', 'h1'),
          P('El sistema administra el trabajo diario de una clínica de radiología e imágenes: agenda de '
            'citas por convenio (COEX, Privado y Emergencia IGSS), fila de turnos, órdenes de trabajo, '
            'carga de imágenes (JPG y DICOM), informes del radiólogo, envío de resultados al paciente y al '
            'médico tratante con un visor web, cobros y órdenes de pago agrupadas, reportes diarios, '
            'comisiones, planilla, estadísticas, bitácora de auditoría y respaldos.'),
          P('Tecnologías', 'h2'),
          tabla(['Pieza', 'Uso'], [
              ('Django 5.2 (Python 3.11)', 'Aplicación web (vistas basadas en funciones, plantillas Django).'),
              ('MySQL 8 (mysqlclient)', 'Base de datos local en 127.0.0.1:3306. Sin tablas de zona horaria: '
                                         'no usar lookups __date; filtrar con __range.'),
              ('Waitress', 'Servidor WSGI de producción en Windows (run_waitress.py, puerto 8005).'),
              ('Cloudflare Tunnel', 'Publica el puerto 8005 como https://clinica.cimeimagenes.com.'),
              ('WhiteNoise', 'Sirve los estáticos con manifiesto (requiere collectstatic).'),
              ('django-otp (TOTP)', 'Verificación en dos pasos para usuarios y para el admin de Django.'),
              ('ReportLab / openpyxl', 'PDF (boletas, constancias, reportes) y Excel (reportes diarios).'),
              ('pydicom + numpy + Pillow', 'Conversión DICOM → JPG con ventana Hounsfield.'),
              ('qrcode', 'QR del enlace al visor en los correos de resultados.'),
              ('dnspython', 'Verificación gratuita de que el dominio de un correo puede recibir correo.'),
              ('cryptography', 'Cifrado AES-256-GCM de los respaldos.'),
              ('pytesseract', 'OCR de comprobantes de pago de planilla (verificación de boleta).'),
          ], [4.5 * cm, 12.5 * cm]),
          P('Apps del proyecto', 'h2'),
          *vinetas([
              '<b>clinica</b>: configuración (settings, settings_test, urls, wsgi), validadores de correo y el '
              'admin de Django protegido con MFA.',
              '<b>accounts</b>: usuarios, roles, sucursales, inicio de sesión con MFA, panel principal, '
              'estadísticas y finanzas, planilla y comisiones de empleados, bitácora y respaldos.',
              '<b>pacientes</b>: pacientes, catálogo de estudios y precios, agenda, turnos, órdenes de trabajo, '
              'imágenes, informes, caja, reportes diarios, médicos tratantes, notificaciones y visor web.',
          ]),
          P('Middlewares (en orden)', 'h2'),
          tabla(['Middleware', 'Qué hace'], [
              ('accounts.ModoRestauracionMiddleware', 'Durante una restauración responde 503 con una página de '
                                                       'progreso sin tocar la base de datos.'),
              ('Security / WhiteNoise / Sessions / Common / CSRF / Auth', 'Middlewares estándar de Django.'),
              ('django_otp.OTPMiddleware', 'Marca si la sesión ya pasó el segundo factor.'),
              ('Messages / XFrameOptions', 'Mensajes flash y protección clickjacking.'),
              ('accounts.SesionUnicaMiddleware', 'Un usuario solo puede tener una sesión activa: si entra desde '
                                                  'otro equipo, la sesión vieja se cierra.'),
              ('accounts.SinCacheConSesionMiddleware', 'Páginas con sesión sin caché del navegador (botón Atrás '
                                                        'tras cerrar sesión).'),
              ('pacientes.AutoMarcarAusenteMiddleware', 'En cada request marca AUSENTE las citas agendadas '
                                                         'vencidas.'),
              ('pacientes.AplicarCambiosEstudioProgramadosMiddleware', 'En cada request aplica los cambios de '
                                                                        'estudio/precio programados que ya '
                                                                        'vencieron.'),
          ], [6.5 * cm, 10.5 * cm], ['celda_cod', 'celda']),
          PageBreak()]

    # 2. Estructura
    h += [P('2. Estructura del proyecto', 'h1'),
          cod('''
seminario subida/
├── manage.py
├── run_waitress.py            arranque de producción (Waitress, puerto 8005)
├── requirements.txt / requirements-dev.txt
├── pytest.ini / setup.cfg     pytest (settings_test) y flake8
├── .env / .env.example        configuración por entorno (no se versiona .env)
├── docs/                      esta documentación y su generador
├── templates/base.html        layout general (barra lateral, campanita)
├── static/                    CSS/JS propios (se copian a staticfiles/ con collectstatic)
├── clinica/                   settings, urls, wsgi, validators, admin con MFA
├── accounts/
│   ├── models.py              Sucursal, Usuario, RolAdicional, Bitacora, pagos, Drive...
│   ├── views.py               login/MFA, usuarios, sucursales, planilla, bitácora, respaldos
│   ├── forms.py
│   ├── pantallas.py           botones del panel por rol;  menu_lateral.py  barra lateral
│   ├── sucursales.py          sucursal activa y filtros por sucursal
│   ├── estadisticas.py / finanzas.py / planilla.py / periodos.py
│   ├── respaldos.py / respaldo_automatico.py / programador.py / trabajos.py / nube.py / cifrado.py
│   ├── limitador.py           límite de intentos fallidos de login/MFA
│   ├── middleware.py / correos.py / verificacion_boleta.py
│   └── management/commands/   respaldos, restaurar, sync_permisos...
└── pacientes/
    ├── models.py              Paciente, TipoEstudio, PrecioEstudio, Cita, Cobro, OrdenTrabajo...
    ├── views/                 vistas separadas por responsabilidad (ver sección 5)
    ├── forms.py / horarios.py / correos.py / dicom_utils.py
    ├── comisiones_medico_tratante.py / estado_clinica.py / middleware.py
    ├── templates/pacientes/ y templates/includes/
    └── management/commands/   datos demo, notificar pendientes, verificar correo...
'''),
          P('Reorganización de octubre 2026: el antiguo <font face="%s">pacientes/views.py</font> (más de 6000 '
            'líneas, con cuatro vistas duplicadas) se dividió en el paquete <font face="%s">pacientes/views/</font>. '
            '<font face="%s">urls.py</font> no cambió porque <font face="%s">views/__init__.py</font> reexporta '
            'todas las vistas con URL.' % ((CODIGO,) * 4)),
          PageBreak()]

    # 3. Roles
    from accounts.pantallas import PANTALLAS_POR_ROL
    from accounts.models import Usuario
    nombres_rol = dict(Usuario.ROL_CHOICES)
    h += [P('3. Roles y pantallas', 'h1'),
          P('Cada usuario tiene un rol principal (<font face="%s">Usuario.rol</font>) y puede tener roles '
            'adicionales (<font face="%s">RolAdicional</font>). <font face="%s">Usuario.tiene_rol()</font> considera '
            'ambos, y las funciones de <font face="%s">pacientes/views/permisos.py</font> y '
            '<font face="%s">accounts.views.es_administrador</font> se usan con '
            '<font face="%s">@user_passes_test</font>. Caja se habilita con el permiso '
            '<font face="%s">puede_operar_caja</font>, independiente del rol.' % ((CODIGO,) * 7)),
          tabla(['Rol', 'Pantallas del panel principal'], [
              (nombres_rol.get(rol, rol), ', '.join(p['nombre'] for p in ps) or '—')
              for rol, ps in PANTALLAS_POR_ROL.items()
          ], [4.5 * cm, 12.5 * cm]),
          P('El usuario trabaja en una o varias <b>sucursales</b>; la activa se guarda en la sesión '
            '(<font face="%s">accounts/sucursales.py</font>). Los listados se filtran con '
            '<font face="%s">sucursales.filtrar()</font> y los registros por id se abren con '
            '<font face="%s">sucursales.permitidas()</font>. El administrador puede ver "Todas las sucursales".'
            % ((CODIGO,) * 3)),
          PageBreak()]

    # 4. Modelos
    h += [P('4. Modelos (base de datos)', 'h1'),
          P('Resumen generado desde el código: tabla MySQL, descripción (docstring) y campos de cada modelo. '
            'Los campos ForeignKey/OneToOne muestran el modelo destino.')]
    for app in ('accounts', 'pacientes'):
        h.append(P(f'App {app}', 'h2'))
        for m in apps.get_app_config(app).get_models():
            doc = inspect.getdoc(m) or ''
            if doc.startswith(m.__name__ + '('):
                doc = ''
            campos = []
            for f in m._meta.get_fields():
                if f.auto_created and not f.concrete:
                    continue
                destino = f' → {f.related_model.__name__}' if getattr(f, 'related_model', None) else ''
                campos.append(f'{f.name} ({type(f).__name__}{destino})')
            bloque = [P(f'{m.__name__} <font size="8" color="#6B7280">· tabla {m._meta.db_table}</font>', 'h3')]
            if doc:
                bloque.append(P(doc_html(doc).replace('\n\n', '<br/><br/>').replace('\n', ' ')))
            bloque.append(P('<font size="8"><b>Campos:</b> ' + escape(', '.join(campos)) + '</font>'))
            h.append(KeepTogether(bloque[:2]))
            h += bloque[2:]
    h.append(PageBreak())

    # 5. Vistas y URLs
    h += [P('5. Vistas y URLs', 'h1'),
          P('Todas las rutas de la aplicación (sin el admin de Django), agrupadas por módulo. La descripción '
            'es el primer párrafo del docstring de la vista.')]
    por_modulo = {}
    for u in urls:
        por_modulo.setdefault(u['modulo'], []).append(u)
    descripciones = {m['ruta'].replace('/', '.').removesuffix('.py'): m['doc']
                     for m in modulos_de('pacientes') + modulos_de('accounts')}
    for modulo in sorted(por_modulo):
        h.append(P(modulo, 'h2'))
        doc_mod = descripciones.get(modulo) or descripciones.get(modulo + '.__init__')
        if doc_mod:
            h.append(P(doc_html(primer_parrafo(doc_mod))))
        h.append(tabla(['URL', 'Nombre', 'Vista', 'Qué hace'], [
            (u['ruta'], u['nombre'], u['vista'], primer_parrafo(u['doc']) or '—') for u in por_modulo[modulo]
        ], [4.6 * cm, 3.6 * cm, 3.4 * cm, 5.4 * cm], ['celda_cod', 'celda_cod', 'celda_cod', 'celda']))
    h.append(PageBreak())

    # 6. Flujos
    h += [P('6. Flujos principales', 'h1')]
    h += [P('6.1 Agendar una cita y atenderla', 'h2'),
          *vinetas([
              '<b>COEX y Emergencia IGSS</b>: recepción elige el hueco en el calendario semanal '
              '(<font face="%s">citas.seleccionar_horario</font>, reglas en <font face="%s">horarios.py</font>: '
              'lunes a sábado, 7:00–17:00, bloques de 15 min, hasta 21 días adelante) y llena '
              '<font face="%s">agendar_cita</font>. El paciente se reutiliza por DPI '
              '(<font face="%s">obtener_o_actualizar_paciente</font>). La cita queda <b>PENDIENTE</b> y le llega '
              'una notificación al radiólogo asignado, que la confirma o rechaza en "Solicitudes de citas" '
              '(<font face="%s">revisar_solicitud</font>). Se permiten hasta 5 emergencias por día encima de '
              'otra cita.' % ((CODIGO,) * 5),
              '<b>Privado</b>: <font face="%s">agendar_cita_privado</font> agenda directo (AGENDADA), asigna el '
              'primer radiólogo habilitado de la sucursal y solo avisa si el turno ya está ocupado.' % CODIGO,
              '<b>Llegada</b>: en "Procesar citas" recepción marca la llegada (<font face="%s">marcar_llegada</font>); '
              'en COEX/Privado eso crea el turno de la Pantalla de turnos. Emergencia IGSS sin cita entra por '
              '"Registrar Ticket" (prioridad urgente).' % CODIGO,
              '<b>Orden de trabajo</b>: <font face="%s">generar_orden</font> (o "Procesar" desde el turno) crea la '
              'OrdenTrabajo con la indicación clínica, el Cobro pendiente, pasa la cita a EN_PROCESO y avisa a '
              'los técnicos.' % CODIGO,
              '<b>Técnico</b>: en "Órdenes pendientes" verifica el estudio (<font face="%s">validar_estudio</font>: '
              'correcto, o pide a recepción una corrección que se resuelve en "Estudios por corregir") y sube '
              'las imágenes por tandas. Los DICOM se convierten a JPG y se guarda el original.' % CODIGO,
              '<b>Radiólogo</b>: en "Citas procesadas" elige qué imágenes ve el paciente, redacta o sube el '
              'informe de cada estudio (un combo tiene varios) y puede agregar un estudio extra. Con todos los '
              'informes la cita queda <b>PROCESADA</b>.',
              '<b>Resultados</b>: se envían por correo con enlace y QR al visor '
              '(<font face="%s">envio_resultados</font>). En Privado el envío espera a que el cobro esté pagado; '
              'COEX y Emergencia IGSS se envían sin esperar el pago. El médico tratante recibe su propio enlace '
              'si su tipo es privado/ambos.' % CODIGO,
              '<b>Visor web</b> (<font face="%s">views/visor.py</font>): el paciente entra con el enlace firmado '
              '(token UUID) y su DPI (máx. 5 intentos); el médico tratante con un código OTP por correo '
              '(vence a los 10 min, reenvío cada 60 s).' % CODIGO,
          ])]
    h += [P('6.2 Precios: convenio × horario', 'h2'),
          *vinetas([
              'Cada TipoEstudio tiene una matriz <font face="%s">PrecioEstudio</font> por <b>convenio</b> (COEX, '
              'Privado, Emergencia IGSS) y <b>horario hábil/inhábil</b>, general o propia de una sucursal.' % CODIGO,
              'Regla de horario (<font face="%s">es_horario_habil</font>): desde las 18:00 Privado y Emergencia '
              'IGSS cobran tarifa inhábil; <b>COEX no tiene tarifa inhábil</b>. Si una celda inhábil no existe se '
              'usa la hábil.' % CODIGO,
              '<font face="%s">TipoEstudio.precio_para(convenio, habil, fecha, sucursal)</font>: primero el precio '
              'propio de la sucursal, si no el general. Con fecha busca en '
              '<font face="%s">HistorialPrecioEstudio</font> el precio vigente ese día, así reportes y boletas '
              'viejas no cambian cuando se actualiza la tarifa.' % ((CODIGO,) * 2),
              '<font face="%s">Cita.precio</font> = precio del estudio agendado + estudios extra marcados '
              '"procesar ahora". Es el precio que usan Caja, reportes, finanzas, comisiones y planilla.' % CODIGO,
              'Cambios programados: el administrador puede dejar un cambio de estudio/precio con fecha de '
              'vigencia (<font face="%s">CambioEstudioProgramado</font>); se aplica solo por middleware.' % CODIGO,
              'Para listados de muchas citas, precargar <font face="%s">PREFETCH_PRECIO_CITA</font> junto con '
              '<font face="%s">select_related("tipo_estudio", "sucursal")</font>: el precio se calcula en memoria '
              'en vez de hacer ~4 consultas por cita.' % ((CODIGO,) * 2),
          ])]
    h += [P('6.3 Caja y órdenes de pago', 'h2'),
          *vinetas([
              'El <font face="%s">Cobro</font> es solo administrativo (no mueve dinero): registra forma de pago, '
              'número de boleta, comprobante bancario y constancia firmada. Un cobro pendiente solo bloquea el '
              'envío de resultados de Privado.' % CODIGO,
              'COEX y Emergencia IGSS se liquidan con <font face="%s">OrdenPago</font> agrupadas por convenio y '
              'rango de fechas (muchos pacientes), solo con estudios que el técnico ya verificó. Se pagan con una '
              'boleta global (<font face="%s">pagar_orden_pago</font>).' % ((CODIGO,) * 2),
              'PDFs: boleta de pago, constancia y orden de pago (ReportLab, datos de la clínica en '
              '<font face="%s">views/comun.py</font>).' % CODIGO,
          ])]
    h += [P('6.4 Reportes', 'h2'),
          *vinetas([
              '<b>Reporte diario</b> por convenio, fecha y sucursal (<font face="%s">ReporteDiario</font>): se crea '
              'en borrador al confirmar la primera cita del día y las citas se calculan al vuelo. Recepción '
              'corrige médico tratante y placas (Privado) y lo envía cuando el día terminó y no hay pacientes '
              'con datos pendientes. Finanzas recibe aviso y descarga PDF/Excel.' % CODIGO,
              '<b>Informe anual</b>: facturación por mes y convenio con el precio vigente de cada fecha.',
              '<b>Panel del administrador</b>: estadísticas (<font face="%s">accounts/estadisticas.py</font>), '
              'finanzas (<font face="%s">finanzas.py</font>, con CSV) y "Estado de la Clínica" '
              '(<font face="%s">pacientes/estado_clinica.py</font>).' % ((CODIGO,) * 3),
              '<b>Comisiones</b>: técnicos y radiólogos por %% según convenio (<font face="%s">accounts/planilla.py</font>, '
              'pagos por línea para no pagar dos veces) y médicos tratantes por citas Privado referidas '
              '(<font face="%s">comisiones_medico_tratante.py</font>).' % ((CODIGO,) * 2),
          ])]
    h += [P('6.5 Correos: verificación y confirmación', 'h2'),
          *vinetas([
              'Verificación del correo sin servicios pagos (<font face="%s">clinica/validators.py</font>): se '
              'consulta el DNS del dominio (MX, o A/AAAA como respaldo) y se rechazan dominios desechables. Se '
              'puede apagar con <font face="%s">VERIFICAR_CORREO_EXISTENTE=False</font>.' % ((CODIGO,) * 2),
              'Usuarios nuevos: <font face="%s">crear_usuario</font> deja la cuenta inactiva y envía un enlace; '
              '<font face="%s">confirmar_correo_usuario</font> la activa si el token no venció.' % ((CODIGO,) * 2),
              'Si el envío SMTP falla (por ejemplo, red que bloquea el puerto 587), las funciones devuelven un '
              'texto de error y la pantalla avisa sin romper el flujo.',
          ])]
    h += [P('6.6 Seguridad y auditoría', 'h2'),
          *vinetas([
              'Inicio de sesión en dos pasos: usuario+contraseña y luego código TOTP si el administrador activó '
              'MFA; primer ingreso con QR para vincular la app.',
              'Límite de intentos fallidos por IP+usuario y por IP (<font face="%s">accounts/limitador.py</font>).'
              % CODIGO,
              'Sesión única por usuario, sin caché en páginas con sesión, admin de Django solo con OTP.',
              'Bitácora (<font face="%s">Bitacora.registrar</font>) con la IP real del visitante (cabecera '
              'CF-Connecting-IP de Cloudflare).' % CODIGO,
          ])]
    h += [P('6.7 Respaldos', 'h2'),
          *vinetas([
              'Manual desde "Respaldos": base de datos con <font face="%s">mysqldump</font>, opcionalmente con '
              'media/, cifrado AES-256-GCM si hay <font face="%s">RESPALDOS_CLAVE</font>, subida a Google Drive '
              '(OAuth, credenciales cifradas). Un solo trabajo a la vez en segundo plano.' % ((CODIGO,) * 2),
              'Automático diario (<font face="%s">programador.py</font>, hilo dentro del servidor): base de datos '
              'completa (se conservan las últimas 6) e imágenes en paquetes incrementales; hasta 3 reintentos.'
              % CODIGO,
              'Restauración: pide contraseña y escribir RESTAURAR, guarda antes un respaldo de seguridad y deja '
              'el sitio en modo mantenimiento mientras dura.',
          ])]
    h += [P('6.8 Agente de borrado en las PCs que suben estudios', 'h2'),
          *vinetas([
              'Al subir imágenes se guarda la huella SHA-256 de cada archivo tal como llegó '
              '(<font face="%s">ImagenEstudio.huella_sha256</font>; del DICOM original, no del JPG convertido).'
              % CODIGO,
              'En cada PC autorizada corre <font face="%s">agente_borrado/agente_borrado.ps1</font> (PowerShell, '
              'tarea programada cada 5 min): calcula la huella de los archivos de la carpeta de RadiAnt, pregunta '
              'a <font face="%s">POST /api/agente/huellas/</font> cuáles ya están en el sistema y solo esos los '
              'manda a la Papelera (o los borra). Si el servidor no responde, no borra nada.' % ((CODIGO,) * 2),
              'Cada PC usa su propio token (<font face="%s">AgenteEquipo</font>, guardado como hash), que solo sirve '
              'para esa consulta: <font face="%s">manage.py token_agente crear|renovar|revocar|listar</font>.'
              % ((CODIGO,) * 2),
              'No se confirma una imagen cuyo archivo ya no está en el servidor (p. ej. JPG descartado), se '
              'ignoran archivos modificados hace menos de 5 minutos, y las imágenes subidas antes de este cambio '
              'no tienen huella. Instalación paso a paso en <font face="%s">agente_borrado/LEEME.md</font>.' % CODIGO,
          ])]
    h.append(PageBreak())

    # 7. Módulos y funciones
    h += [P('7. Módulos y funciones clave', 'h1'),
          P('Para cada archivo: su propósito (docstring del módulo) y sus funciones/clases de nivel superior con '
            'el primer párrafo de su docstring. Las que empiezan con guion bajo son de uso interno del módulo o '
            'del paquete.')]
    for base in ('clinica', 'accounts', 'pacientes'):
        h.append(P(f'{base}/', 'h2'))
        for m in modulos_de(base):
            if not m['funciones'] and not m['doc']:
                continue
            h.append(P(f'{m["ruta"]} <font size="8" color="#6B7280">· {m["lineas"]} líneas</font>', 'h3'))
            if m['doc']:
                h.append(P(doc_html(primer_parrafo(m['doc']))))
            filas = [(n, primer_parrafo(d) or '—') for n, _t, d in m['funciones']]
            if filas:
                h.append(tabla(['Nombre', 'Descripción'], filas, [5 * cm, 12 * cm], ['celda_cod', 'celda']))
    h.append(PageBreak())

    # 8. Despliegue
    h += [P('8. Instalación, despliegue y operación', 'h1'),
          P('8.1 Configuración (.env)', 'h2'),
          tabla(['Variable', 'Para qué'], [
              ('SECRET_KEY, DEBUG, ALLOWED_HOSTS', 'Básicos de Django. En producción DEBUG=False.'),
              ('DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT', 'Conexión a MySQL.'),
              ('CSRF_TRUSTED_ORIGINS', 'Debe incluir https://clinica.cimeimagenes.com.'),
              ('SECURE_SSL_REDIRECT, SECURE_HSTS_SECONDS', 'HTTPS detrás del túnel.'),
              ('EMAIL_HOST_USER, EMAIL_HOST_PASSWORD', 'SMTP de Gmail (contraseña de aplicación). Vacíos: no '
                                                       'se envían correos.'),
              ('VISOR_BASE_URL', 'URL pública que va en los enlaces/QR del visor.'),
              ('VERIFICAR_CORREO_EXISTENTE', 'Activa la verificación DNS de correos.'),
              ('BACKUP_DIR, MYSQLDUMP_PATH, RESPALDOS_CLAVE', 'Carpeta de respaldos, ruta de mysqldump y clave '
                                                                'de cifrado (mín. 16 caracteres).'),
              ('RESPALDOS_AUTOMATICOS, RESPALDOS_AUTOMATICOS_CONSERVAR, RESPALDOS_AUTOMATICOS_INCLUYEN_ARCHIVOS',
               'Copia automática diaria.'),
              ('SERVIR_MEDIA', 'Sirve media/ desde Django aunque DEBUG=False.'),
          ], [7 * cm, 10 * cm], ['celda_cod', 'celda']),
          P('8.2 Instalación', 'h2'),
          cod(r'''
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt      (usar "python -m pip", no venv\Scripts\pip)
copy .env.example .env                                       (y completar los valores)
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py collectstatic --noinput
venv\Scripts\python run_waitress.py 8005
'''),
          P('8.3 Producción (seminario subida)', 'h2'),
          *vinetas([
              'Waitress corre como tarea programada <font face="%s">ClinicaImagenes-Waitress</font> '
              '(<font face="%s">run_waitress.py 8005</font>, confía en X-Forwarded-Proto solo desde 127.0.0.1).'
              % ((CODIGO,) * 2),
              'Cloudflare Tunnel (cloudflared) apunta a http://127.0.0.1:8005 y publica '
              'https://clinica.cimeimagenes.com. Si la sesión que lo levantó termina, hay que reiniciarlo.',
              'Reiniciar Waitress corta el sitio un instante: avisar antes a quien esté usando el sistema.',
          ]),
          cod(r'''
schtasks /End /TN "ClinicaImagenes-Waitress"
schtasks /Run /TN "ClinicaImagenes-Waitress"
'''),
          tabla(['Tipo de cambio', 'Qué hacer para que se vea en el sitio'], [
              ('Plantillas (.html)', 'Reiniciar Waitress (Django guarda las plantillas en caché).'),
              ('Código Python (.py)', 'Reiniciar Waitress.'),
              ('CSS / JS / imágenes estáticas', 'collectstatic --noinput y luego reiniciar Waitress.'),
              ('Modelos (migraciones nuevas)', 'Respaldo, migrate y luego reiniciar Waitress.'),
          ], [5.5 * cm, 11.5 * cm]),
          P('8.4 Pruebas y calidad', 'h2'),
          cod(r'''
venv\Scripts\python manage.py check
venv\Scripts\python -m pytest              (usa clinica.settings_test: correo en memoria, media_test/)
venv\Scripts\python -m pytest --create-db  (si la BD de pruebas quedó con otro esquema)
venv\Scripts\python -m flake8
'''),
          P('No usar <font face="%s">manage.py test</font>: usa settings.py con SMTP real y escribe en media/. '
            'La base de pruebas test_* es compartida entre copias del proyecto.' % CODIGO),
          P('8.5 Particularidades conocidas', 'h2'),
          *vinetas([
              'MySQL local sin tablas de zona horaria: los lookups <font face="%s">__date</font> sobre DateTimeField '
              'devuelven vacío. Usar rangos (<font face="%s">__range</font> / <font face="%s">__gte</font> + '
              '<font face="%s">__lt</font>).' % ((CODIGO,) * 4),
              'El campo sexo es obligatorio; un <font face="%s">&lt;select disabled&gt;</font> no se envía en el POST, '
              'así que no usar disabled en campos obligatorios (usar readonly/hidden).' % CODIGO,
              'El envío por SMTP puede fallar en redes que bloquean el puerto 587 (no es un error del código).',
          ]),
          PageBreak()]

    # 9. Cambios de la reorganización
    h += [P('9. Reorganización y optimización (octubre 2026)', 'h1'),
          *vinetas([
              '<font face="%s">pacientes/views.py</font> → paquete <font face="%s">pacientes/views/</font> con 14 '
              'módulos por responsabilidad; se eliminaron 4 vistas que estaban definidas dos veces.'
              % ((CODIGO,) * 2),
              'Código muerto eliminado: función duplicada en accounts/models.py, helpers y constantes sin uso, '
              'y accounts/tests2.py (pytest nunca lo recogía; su test nuevo pasó a accounts/tests.py).',
              'Consultas N+1 corregidas (sin cambiar resultados): informe anual, comisión de médico tratante, '
              'reporte diario, planilla y pago de comisiones, caja, historial del paciente, órdenes pendientes '
              'y pantalla de turnos (tabla de abajo).',
              'Docstrings en español en vistas, modelos y módulos que no tenían.',
          ]),
          P('Consultas SQL por página, medidas con datos de prueba (2 pacientes → 8 pacientes, 12 citas cada '
            'uno). Antes crecían con la cantidad de citas; ahora quedan fijas:'),
          tabla(['Página', 'Antes (2 → 8 pacientes)', 'Después (2 → 8 pacientes)'], [
              ('Informe anual', '93 → 333', '13 → 13'),
              ('Comisión de médico tratante', '63 → 219', '14 → 14'),
              ('Reporte diario', '63 → 171', '34 → 34'),
              ('Planilla', '38 → 110', '16 → 16'),
              ('Planilla de un empleado', '36 → 108', '14 → 14'),
              ('Registrar pago de comisión', '33 → 105', '11 → 11'),
              ('Historial del paciente', '42 → 114', '20 → 20'),
              ('Órdenes pendientes (técnico)', '27 → 51', '20 → 20'),
              ('Pantalla de turnos', '19 → 31', '15 → 15'),
          ], [7 * cm, 5 * cm, 5 * cm]),
          P('Pendientes sugeridos', 'h2'),
          *vinetas([
              'Los middlewares de ausentes y cambios programados hacen consultas en cada request; se podrían '
              'limitar a una vez por minuto.',
              '<font face="%s">Usuario.tiene_rol</font> consulta los roles adicionales en cada llamada (~7 '
              'consultas por página); se podría cachear por request.' % CODIGO,
              'El test test_cada_sucursal_tiene_su_propia_agenda ya fallaba antes de la reorganización.',
          ])]

    doc = Documento(str(SALIDA), pagesize=letter, leftMargin=2 * cm, rightMargin=2 * cm,
                    topMargin=1.8 * cm, bottomMargin=2 * cm,
                    title='Documentación técnica — Sistema Clínica de Imágenes', author='Clínica de Imágenes')
    doc.multiBuild(h, onFirstPage=lambda c_, d: None, onLaterPages=pie)
    print(f'PDF generado: {SALIDA}')


if __name__ == '__main__':
    construir()

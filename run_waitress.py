"""Levanta la app con Waitress (servidor WSGI de produccion, sirve bien en
Windows) en vez de 'manage.py runserver', que es solo para desarrollo.

Uso:
    venv/Scripts/python run_waitress.py [puerto]

El Cloudflare Tunnel apunta a http://127.0.0.1:<puerto> (o a
http://0.0.0.0:<puerto> si vas a seguir probando tambien desde la LAN).
"""
import sys

from waitress import serve

from clinica.wsgi import application

if __name__ == '__main__':
    puerto = sys.argv[1] if len(sys.argv) > 1 else '8005'
    print(f'Sirviendo clinica.wsgi en http://0.0.0.0:{puerto} (Waitress)')
    serve(application, listen=f'0.0.0.0:{puerto}')

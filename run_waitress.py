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
    # cloudflared conecta desde esta misma máquina y Cloudflare manda X-Forwarded-Proto: https.
    # Waitress descarta esa cabecera si no se confía en quien la manda, y sin ella Django cree
    # que todo llega por http:// (no envía HSTS ni marca la conexión como segura). Solo se
    # confía cuando viene de 127.0.0.1; los equipos de la LAN no pueden falsificarla.
    serve(
        application,
        listen=f'0.0.0.0:{puerto}',
        trusted_proxy='127.0.0.1',
        trusted_proxy_headers={'x-forwarded-proto'},
        clear_untrusted_proxy_headers=True,
    )

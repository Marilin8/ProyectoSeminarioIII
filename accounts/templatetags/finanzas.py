from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def quetzales(valor):
    """Monto con el formato de Guatemala: Q1,234.56 (independiente del locale)."""
    try:
        return f'Q{Decimal(valor):,.2f}'
    except (InvalidOperation, TypeError, ValueError):
        return 'Q0.00'

from decimal import Decimal
from django import template
from cafe.permissions import is_manager
register = template.Library()

@register.filter
def peso(value):
    try:
        return f'₱{Decimal(value):,.2f}'
    except (TypeError, ValueError):
        return '₱0.00'

@register.filter
def qty(value):
    return f'{Decimal(value):,.3f}'.rstrip('0').rstrip('.')

@register.filter
def manager(user):
    return is_manager(user)

@register.filter
def user_label(user, fallback='Guest'):
    """Nullable audit actors include guests, system actions, and deleted users.

    Keep the fallback inside Python: a template filter argument such as
    ``default:event.user.username`` is resolved before ``default`` is called,
    so it raises VariableDoesNotExist when event.user is None.
    Return plain text so Django still escapes names in HTML output.
    """
    return getattr(user, 'first_name', '') or getattr(user, 'username', '') or fallback

@register.simple_tag(takes_context=True)
def page_query(context, page):
    query = context['request'].GET.copy()
    query['page'] = page
    return '?' + query.urlencode()

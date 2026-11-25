from django.db.models import F
from .models import Ingredient, Order
from .permissions import is_admin, is_manager

def cafe_context(request):
    context = {'shop_name': 'Coffee de Luna', 'is_manager': is_manager(request.user),
               'is_admin': is_admin(request.user), 'app_version': '1.10'}
    if request.user.is_authenticated:
        context['low_stock_count'] = Ingredient.objects.filter(is_active=True, quantity__lte=F('reorder_level')).count()
        context['open_order_count'] = Order.objects.filter(status__in=['pending', 'preparing', 'ready']).count()
    return context

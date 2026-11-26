"""Customer history and fresh basket drafts; past orders remain immutable."""
from collections import defaultdict
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from .customizations import drink_capacity, plan_drink
from .models import Order, OrderItem, Product


def owned_orders(user):
    items = OrderItem.objects.select_related('product__category', 'parent_item')
    return Order.objects.filter(customer=user).prefetch_related(Prefetch('items', queryset=items))


def decorate_orders(orders):
    for order in orders:
        order.main_items = [item for item in order.items.all() if item.parent_item_id is None]
        order.preview_items = order.main_items[:3]
    return orders


def recent_drinks(user):
    items = (OrderItem.objects.filter(order__customer=user, parent_item__isnull=True)
             .exclude(order__status='cancelled').select_related('product__category', 'order')
             .order_by('-order__created_at', '-pk')[:36])
    seen, drinks = set(), []
    for item in items:
        signature = (item.product_id or item.name, item.customization_summary)
        if signature in seen:
            continue
        seen.add(signature)
        item.available = bool(item.product_id and item.product.is_active and not item.product.is_add_on)
        drinks.append(item)
        if len(drinks) == 4:
            break
    return drinks


def reorder_lines(order, item_id=None):
    """Rebuild exact drink/extras choices using today's menu and availability.

    This makes a reviewable draft only. Checkout still validates prices and the
    combined inventory needs before it creates a new order or reserves stock.
    Never silently drop a missing extra or substitute another drink.
    """
    snapshots = list(order.items.all())
    bases = [item for item in snapshots if item.parent_item_id is None]
    if item_id is not None:
        bases = [item for item in bases if item.pk == item_id]
    if not bases:
        raise ValidationError('This drink is no longer available to order again.')
    children = defaultdict(list)
    for item in snapshots:
        if item.parent_item_id:
            children[item.parent_item_id].append(item)
    product_ids = {item.product_id for item in snapshots if item.product_id}
    products = {p.pk: p for p in Product.objects.filter(pk__in=product_ids)
                .prefetch_related('recipe_items__ingredient')}
    lines, counts = [], defaultdict(int)
    for base in bases:
        product = products.get(base.product_id)
        if not product or not product.is_active or product.is_add_on or not 1 <= base.quantity <= 99:
            raise ValidationError('A drink in that order is no longer available. Please choose from the current menu.')
        choices = []
        for child in children[base.pk]:
            extra = products.get(child.product_id)
            if not extra or child.quantity % base.quantity:
                raise ValidationError('An extra from that order is no longer available. Please customise a new drink.')
            choices.append((extra, child.quantity // base.quantity))
        plan_drink(product, choices)
        if drink_capacity(product, choices) < base.quantity:
            raise ValidationError('There is not enough stock for that selection right now. Please choose another drink or quantity.')
        counts[product.pk] += base.quantity
        if counts[product.pk] > 99:
            raise ValidationError('Please choose no more than 99 of the same drink.')
        lines.append({'id': product.pk, 'quantity': base.quantity,
                      'add_ons': [{'id': extra.pk, 'quantity': qty} for extra, qty in choices]})
    return lines

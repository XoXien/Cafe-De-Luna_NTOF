"""All stock and order changes run in transactions and use server-side prices."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import uuid
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .customizations import plan_drink
from .permissions import is_customer, is_team
from .models import Ingredient, Order, OrderEvent, OrderIngredient, OrderItem, Product, Purchase, StockMovement

ZERO = Decimal('0')

def money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) > Decimal('99999999'):
            raise ValueError
        return result.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Enter a valid amount.')

def decimal_quantity(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) > Decimal('999999999'):
            raise ValueError
        if result != result.quantize(Decimal('0.001')):
            raise ValidationError('Use at most three decimal places for quantities.')
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Enter a valid quantity.')

def _movement(ingredient, delta, kind, user, note, order=None):
    """Caller must hold the ingredient lock within an atomic transaction."""
    new_balance = ingredient.quantity + delta
    if new_balance < 0:
        raise ValidationError(f'Not enough {ingredient.name}. Available: {ingredient.quantity:g} {ingredient.unit}.')
    ingredient.quantity = new_balance
    ingredient.save(update_fields=['quantity', 'updated_at'])
    StockMovement.objects.create(ingredient=ingredient, quantity=delta, balance_after=new_balance,
                                 kind=kind, user=user, note=note, order=order)

@transaction.atomic
def adjust_stock(ingredient_id, delta, kind, user, note):
    if kind not in ['opening', 'adjust', 'waste']:
        raise ValidationError('Invalid stock movement.')
    delta = decimal_quantity(delta)
    if not delta or not note.strip():
        raise ValidationError('Enter a non-zero quantity and a reason.')
    if kind == 'waste' and delta > 0:
        raise ValidationError('Waste must reduce stock.')
    ingredient = Ingredient.objects.select_for_update().get(pk=ingredient_id)
    _movement(ingredient, delta, kind, user, note.strip()[:250])
    return ingredient

@transaction.atomic
def add_stock(purchase, user):
    ingredient = Ingredient.objects.select_for_update().get(pk=purchase.ingredient_id)
    if not ingredient.is_active:
        raise ValidationError('Choose an active ingredient.')
    quantity = decimal_quantity(purchase.quantity)
    # Resolve a blank cost under the stock lock, using the latest balance/cost.
    try:
        cost = ingredient.cost_per_unit if purchase.unit_cost is None else Decimal(str(purchase.unit_cost))
        if not cost.is_finite() or cost < 0 or cost > Decimal('99999999.9999'):
            raise ValueError
        if cost != cost.quantize(Decimal('0.0001')):
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Enter a non-negative unit cost with up to four decimal places.')
    if quantity <= 0:
        raise ValidationError('The quantity to add must be greater than zero.')
    purchase.unit_cost = cost
    new_cost = ((ingredient.stock_value + quantity * purchase.unit_cost) / (ingredient.quantity + quantity))
    ingredient.cost_per_unit = new_cost.quantize(Decimal('0.0001'))
    ingredient.save(update_fields=['cost_per_unit'])
    purchase.received_by = user
    purchase.save()
    detail = purchase.notes or purchase.reference
    note = f'Stock addition #{purchase.pk}' + (f' · {detail}' if detail else '')
    _movement(ingredient, quantity, 'receive', user, note[:250])
    return purchase

@transaction.atomic
def create_order(*, lines, submission_key, user=None, source='pos', customer_name='', phone='',
                 order_type='dine_in', table_number='', notes='', discount_percent=0,
                 payment_method='cash', paid=False, amount_tendered=0, customer=None):
    try:
        checkout_key = uuid.UUID(str(submission_key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Your checkout expired. Reload the page and try again.')
    if source not in ('pos', 'online') or (source == 'pos' and not is_team(user)):
        raise ValidationError('Invalid order source.')
    if customer is not None and (source != 'online' or not is_customer(customer)):
        raise ValidationError('Invalid customer account.')
    existing = Order.objects.filter(submission_key=checkout_key).first()
    if existing:
        return existing
    if order_type not in dict(Order.TYPES) or payment_method not in dict(Order.PAYMENT):
        raise ValidationError('Choose a valid order type and payment method.')
    if not isinstance(lines, list) or not 1 <= len(lines) <= 50:
        raise ValidationError('Add at least one item to your order (maximum 50 different items).')
    # A line is one drink configuration. Extra quantities are PER drink.
    # Equal configurations merge, while two versions of one drink stay separate.
    configurations, drink_quantities, product_ids = {}, defaultdict(int), set()
    def integer(value, maximum):
        if isinstance(value, bool):
            raise ValueError
        number = int(value)
        if str(number) != str(value) or not 1 <= number <= maximum:
            raise ValueError
        return number
    for line in lines:
        try:
            product_id = integer(line['id'], 9223372036854775807)
            qty = integer(line['quantity'], 99)
            extras = line.get('add_ons', [])
            if not isinstance(extras, list) or len(extras) > 12:
                raise ValueError
            choices = {}
            for extra in extras:
                extra_id = integer(extra['id'], 9223372036854775807)
                portions = integer(extra['quantity'], 3)
                if extra_id in choices:
                    raise ValueError
                choices[extra_id] = portions
            signature = (product_id, tuple(sorted(choices.items())))
            configurations[signature] = configurations.get(signature, 0) + qty
            drink_quantities[product_id] += qty
            if drink_quantities[product_id] > 99:
                raise ValueError
            product_ids.update([product_id, *choices])
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            raise ValidationError('Use 1–99 drinks and valid add-ons per drink, with no duplicate add-on choices.')
    products = {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=product_ids).order_by('pk')
                .prefetch_related('recipe_items__ingredient')}
    if len(products) != len(product_ids):
        raise ValidationError('An item is no longer on the menu. Please refresh your order.')
    requirements, plans, subtotal = defaultdict(Decimal), [], ZERO
    for (product_id, choices), qty in configurations.items():
        parts = plan_drink(products[product_id], [(products[key], count) for key, count in choices])
        plans.append((qty, parts))
        for part in parts:
            portions = part['portions'] * qty
            subtotal += part['product'].price * portions
            for key, (ingredient, amount) in part['ingredients'].items():
                requirements[key] += amount * portions
    ingredients = list(Ingredient.objects.select_for_update().filter(pk__in=requirements).order_by('pk'))
    locked = {ingredient.pk: ingredient for ingredient in ingredients}
    if len(locked) != len(requirements):
        raise ValidationError('An ingredient is unavailable. Please refresh your order.')
    for ingredient in ingredients:
        if not ingredient.is_active or ingredient.quantity < requirements[ingredient.pk]:
            raise ValidationError(f'Not enough {ingredient.name} for this order. Reduce the quantity or select another item.')
    discount_percent = money(discount_percent)
    if not ZERO <= discount_percent <= 20:
        raise ValidationError('Discount must be between 0% and 20%.')
    if source == 'online':
        discount_percent, paid, payment_method, amount_tendered = ZERO, False, 'cash', ZERO
    discount = money(subtotal * discount_percent / 100)
    total = money(subtotal - discount)
    tendered = money(amount_tendered)
    if paid and payment_method == 'cash' and tendered < total:
        raise ValidationError('Cash received must cover the order total.')
    if not paid:
        tendered = ZERO
    elif payment_method != 'cash':
        tendered = total
    customer_name = str(customer_name).strip()[:100] or 'Walk-in guest'
    order = Order.objects.create(submission_key=checkout_key, customer_name=customer_name, phone=str(phone).strip()[:30],
        order_type=order_type, table_number=str(table_number).strip()[:12] if order_type == 'dine_in' else '',
        source=source, notes=str(notes).strip()[:400], subtotal=subtotal, discount=discount, total=total,
        created_by=user, customer=customer, payment_method=payment_method, paid=paid, amount_tendered=tendered)
    for qty, parts in plans:
        parent = None
        for part in parts:
            # Use the locked ingredient costs and effective milk recipe for the snapshot.
            cost = sum((amount * locked[key].cost_per_unit
                        for key, (ingredient, amount) in part['ingredients'].items()), ZERO)
            item = OrderItem.objects.create(order=order, product=part['product'], parent_item=parent,
                name=part['name'], quantity=qty * part['portions'], unit_price=part['product'].price,
                unit_cost=cost, customization_summary=part.get('summary', ''))
            if parent is None:
                parent = item
    for ingredient in ingredients:
        qty = requirements[ingredient.pk]
        OrderIngredient.objects.create(order=order, ingredient=ingredient, quantity=qty)
        _movement(ingredient, -qty, 'sale', user, f'Reserved for {order.number}', order)
    OrderEvent.objects.create(order=order, user=user, message='Order placed. Ingredients reserved.' + (' Payment recorded.' if paid else ''))
    return order

TRANSITIONS = {'pending': ['preparing', 'cancelled'], 'preparing': ['ready', 'cancelled'],
               'ready': ['completed', 'cancelled'], 'completed': [], 'cancelled': []}

@transaction.atomic
def change_order_status(order_id, status, user):
    order = Order.objects.select_for_update().get(pk=order_id)
    if status == order.status:
        return order
    if status not in TRANSITIONS.get(order.status, []):
        raise ValidationError('That status change is not available.')
    if status == 'completed' and not order.paid:
        raise ValidationError('Record payment before completing this order.')
    if status == 'cancelled':
        used = {row.ingredient_id: row.quantity for row in order.ingredients_used.all()}
        for ingredient in Ingredient.objects.select_for_update().filter(pk__in=used).order_by('pk'):
            _movement(ingredient, used[ingredient.pk], 'return', user, f'{order.number} cancelled', order)
        order.refund_due = order.paid
    if status == 'completed':
        order.completed_at = timezone.now()
    order.status = status
    order.save(update_fields=['status', 'completed_at', 'refund_due', 'updated_at'])
    OrderEvent.objects.create(order=order, user=user, message=f'Order marked {order.get_status_display().lower()}.' +
                              (' Manual refund required.' if order.refund_due else ''))
    return order

@transaction.atomic
def record_payment(order_id, method, amount, user):
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.status == 'cancelled':
        raise ValidationError('A cancelled order cannot be paid.')
    if order.paid:
        return order
    if method not in dict(Order.PAYMENT):
        raise ValidationError('Choose a valid payment method.')
    tendered = money(amount) if method == 'cash' else order.total
    if tendered < order.total:
        raise ValidationError('Cash received must cover the order total.')
    order.paid, order.payment_method, order.amount_tendered = True, method, tendered
    order.save(update_fields=['paid', 'payment_method', 'amount_tendered', 'updated_at'])
    OrderEvent.objects.create(order=order, user=user, message=f'Payment recorded via {order.get_payment_method_display()}.')
    return order

@transaction.atomic
def record_refund(order_id, user):
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.status != 'cancelled' or not order.refund_due:
        raise ValidationError('There is no outstanding refund for this order.')
    order.refund_due = False
    order.save(update_fields=['refund_due', 'updated_at'])
    OrderEvent.objects.create(order=order, user=user, message='Manager confirmed the manual refund was issued.')
    return order

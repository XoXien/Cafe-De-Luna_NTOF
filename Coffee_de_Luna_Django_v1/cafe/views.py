import csv
import hashlib
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.models import Group, User
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Sum, Q, ExpressionWrapper, DecimalField, Prefetch
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe
from .customizations import drink_capacity, extra_label
from .forms import (AdjustmentForm, CategoryForm, IngredientForm, LoginForm, ProductForm,
                    ProfileForm, AddStockForm, RecipeFormSet, StaffForm)
from .models import (Category, Ingredient, LoginAttempt, Order, OrderEvent, OrderItem,
                     Product, Purchase, StockMovement)
from .permissions import admin_required, is_admin, is_manager, manager_required
from .services import (TRANSITIONS, adjust_stock, change_order_status, create_order,
                       add_stock, record_payment, record_refund)

def errors_text(exc):
    return ' '.join(exc.messages)

class CafeLoginView(LoginView):
    template_name = 'cafe/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True
    def post(self, request, *args, **kwargs):
        identity = request.META.get('REMOTE_ADDR', '') + '|' + request.POST.get('username', '').lower()[:150]
        self.attempt_key = hashlib.sha256((settings.SECRET_KEY + identity).encode()).hexdigest()
        attempt = LoginAttempt.objects.filter(key=self.attempt_key).first()
        if attempt and attempt.last_attempt < timezone.now() - timedelta(minutes=15):
            attempt.delete()
            attempt = None
        if attempt and attempt.failures >= 5:
            form = self.get_form()
            form.is_valid()
            form.add_error(None, 'Too many sign-in attempts. Please try again in 15 minutes.')
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)
    def form_invalid(self, form):
        attempt, _ = LoginAttempt.objects.get_or_create(key=self.attempt_key)
        LoginAttempt.objects.filter(pk=attempt.pk).update(failures=F('failures') + 1, last_attempt=timezone.now())
        return super().form_invalid(form)
    def form_valid(self, form):
        LoginAttempt.objects.filter(key=self.attempt_key).delete()
        return super().form_valid(form)

def catalog():
    return Product.objects.select_related('category').prefetch_related('recipe_items__ingredient')

def sales_for(queryset):
    return queryset.filter(status='completed', paid=True).aggregate(total=Sum('total'))['total'] or Decimal('0')

def chart_days(start, end):
    daily_sales = (Order.objects.filter(status='completed', paid=True, completed_at__date__range=[start, end])
                   .order_by().annotate(day=TruncDate('completed_at')).values('day').annotate(total=Sum('total')))
    totals = {row['day']: row['total'] for row in daily_sales}
    rows = []
    current = start
    while current <= end:
        amount = totals.get(current, Decimal('0'))
        rows.append({'label': current.strftime('%a'), 'date': current, 'amount': amount})
        current += timedelta(days=1)
    maximum = max([row['amount'] for row in rows] + [Decimal('1')])
    for row in rows:
        row['height'] = max(2, round(float(row['amount'] / maximum) * 100))
    return rows

@login_required
def dashboard(request):
    if is_admin(request.user):
        return redirect('admin_dashboard')
    today = timezone.localdate()
    orders = Order.objects.filter(created_at__date=today)
    revenue = sales_for(Order.objects.filter(completed_at__date=today))
    completed = Order.objects.filter(status='completed', paid=True, completed_at__date=today).count()
    best = (OrderItem.objects.filter(order__status='completed', order__completed_at__date=today, parent_item__isnull=True).exclude(product__is_add_on=True)
            .values('name', 'product__artwork').annotate(sold=Sum('quantity')).order_by('-sold')[:4])
    context = {'page': 'dashboard', 'today': today, 'revenue': revenue,
        'order_count': orders.exclude(status='cancelled').count(), 'completed_count': completed,
        'average': revenue / completed if completed else 0,
        'recent_orders': Order.objects.prefetch_related('items')[:5],
        'low_stock': Ingredient.objects.filter(is_active=True, quantity__lte=F('reorder_level'))[:5],
        'best_sellers': best, 'chart': chart_days(today - timedelta(days=6), today),
        'week_revenue': sales_for(Order.objects.filter(completed_at__date__gte=today - timedelta(days=6)))}
    return render(request, 'cafe/dashboard.html', context)

@admin_required
def admin_dashboard(request):
    """Owner's dashboard: period sales are based on paid order completion dates.

    Queue, inventory, and team figures describe the current state of the café,
    independently of the selected sales period. No operational data is changed.
    """
    today = timezone.localdate()
    days = 30 if request.GET.get('period') == '30' else 7
    start = today - timedelta(days=days - 1)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    completed_orders = Order.objects.filter(status='completed', paid=True,
                                            completed_at__date__range=[start, today])
    sales = completed_orders.aggregate(total=Sum('total'), count=Count('id'))
    revenue = sales['total'] or Decimal('0')
    previous_revenue = sales_for(Order.objects.filter(
        completed_at__date__range=[previous_start, previous_end]))
    change = ((revenue - previous_revenue) / previous_revenue * 100).quantize(Decimal('0.1')) if previous_revenue else None
    items = OrderItem.objects.filter(order__in=completed_orders)
    recipe_cost = items.aggregate(total=Sum(F('unit_cost') * F('quantity'),
        output_field=DecimalField(max_digits=20, decimal_places=4)))['total'] or Decimal('0')

    # One grouped query supplies the full open queue, including older orders.
    open_orders = Order.objects.filter(status__in=['pending', 'preparing', 'ready'])
    counts = {row['status']: row['count'] for row in open_orders.values('status').annotate(count=Count('id'))}
    queue = [{'status': value, 'label': label, 'count': counts.get(value, 0)}
             for value, label in Order.STATUS if value in ['pending', 'preparing', 'ready']]
    unpaid = open_orders.filter(paid=False).aggregate(count=Count('id'), total=Sum('total'))
    refunds = Order.objects.filter(refund_due=True).aggregate(count=Count('id'), total=Sum('total'))
    inventory = Ingredient.objects.filter(is_active=True)
    low_stock = inventory.filter(quantity__lte=F('reorder_level'))
    stock_value = inventory.aggregate(total=Sum(F('quantity') * F('cost_per_unit'),
        output_field=DecimalField(max_digits=20, decimal_places=4)))['total'] or Decimal('0')

    best_sellers = list(items.filter(parent_item__isnull=True).exclude(product__is_add_on=True).values('name', 'product__artwork').annotate(
        sold=Sum('quantity'), item_sales=Sum(F('unit_price') * F('quantity'))).order_by('-sold', 'name')[:4])
    most_sold = max([row['sold'] for row in best_sellers] + [1])
    for row in best_sellers:
        row['width'] = round(row['sold'] / most_sold * 100)
    payment_labels = dict(Order.PAYMENT)
    payments = list(completed_orders.values('payment_method').annotate(
        total=Sum('total'), count=Count('id')).order_by('-total', 'payment_method'))
    for row in payments:
        row['label'] = payment_labels.get(row['payment_method'], row['payment_method'])
        row['percent'] = round(row['total'] / revenue * 100) if revenue else 0

    context = {
        'page': 'admin_dashboard', 'period': str(days), 'period_days': days,
        'start': start, 'end': today, 'today': today,
        'revenue': revenue, 'completed_count': sales['count'], 'recipe_cost': recipe_cost,
        'gross_profit': revenue - recipe_cost,
        'average_order': revenue / sales['count'] if sales['count'] else Decimal('0'),
        'previous_revenue': previous_revenue, 'revenue_change': change,
        'trend_direction': 'up' if revenue > previous_revenue else 'down' if revenue < previous_revenue else 'same',
        'revenue_change_absolute': abs(change) if change is not None else None,
        'chart': chart_days(start, today), 'best_sellers': best_sellers, 'payments': payments,
        'order_queue': queue, 'active_order_count': sum(counts.values()),
        'unpaid_count': unpaid['count'], 'unpaid_total': unpaid['total'] or Decimal('0'),
        'refund_count': refunds['count'], 'refund_total': refunds['total'] or Decimal('0'),
        'inventory_value': stock_value, 'ingredient_count': inventory.count(),
        'stock_alert_count': low_stock.count(), 'out_of_stock_count': inventory.filter(quantity=0).count(),
        'stock_alerts': low_stock.order_by('quantity', 'name')[:5],
        'recent_orders': Order.objects.select_related('created_by')[:6],
        'recent_activity': OrderEvent.objects.select_related('order', 'user')[:5],
        'team_count': User.objects.filter(is_active=True).count(),
        'menu_count': Product.objects.filter(is_active=True).count(),
    }
    return render(request, 'cafe/admin_dashboard.html', context)

def _ordering_page(request, public=False):
    key = str(uuid.uuid4())
    keys = request.session.get('checkout_keys', [])[-9:] + [key]
    request.session['checkout_keys'] = keys
    products = list(catalog().filter(is_active=True).order_by('category__sort_order', 'pk'))
    milk_choices = [p for p in products if p.is_add_on and p.customization_type == 'milk']
    data = []
    for p in products:
        milk_options = {}
        if not p.is_add_on:
            for addon in milk_choices:
                replacing = any(r.ingredient_id == addon.replaces_ingredient_id for r in p.recipe_items.all())
                milk_options[str(addon.pk)] = {'mode': 'replace' if replacing else 'extra',
                    'label': extra_label(addon) if replacing else 'Add ' + extra_label(addon),
                    'capacity': drink_capacity(p, [(addon, 1)])}
        bits = [bit.strip() for bit in p.variant_label.split('·') if bit.strip()]
        option = bits[0] if len(bits) > 2 or (len(bits) == 2 and p.category.name == 'Fruit Tea') else ''
        serving = ' · '.join(bits[1:] if option else bits) or p.variant_label or 'House serving'
        default_capacity = p.capacity
        data.append({'id': p.pk, 'name': p.name, 'menu_name': p.menu_name or p.name,
            'category': p.category.name, 'price': str(p.price), 'variant_label': p.variant_label,
            'serving': serving, 'option': option, 'option_title': 'Included topping' if p.category.name == 'Fruit Tea' else 'Flavour',
            'description': p.description, 'artwork': p.artwork, 'badge': p.badge,
            'image': p.image.url if p.image else '', 'default_capacity': default_capacity,
            'capacity': max([default_capacity] + [m['capacity'] for m in milk_options.values()]),
            'is_add_on': p.is_add_on, 'customization_type': p.customization_type,
            'max_per_drink': p.max_per_drink, 'extra_label': extra_label(p) if p.is_add_on else '',
            'milk_options': milk_options})
    grouped = {}
    for p, item in zip(products, data):
        group_key = (p.category_id, p.menu_name or p.name, p.is_add_on)
        if group_key not in grouped:
            grouped[group_key] = {'name': p.menu_name or p.name, 'category': p.category.name,
                'description': p.description, 'badge': p.badge, 'is_add_on': p.is_add_on, 'variants': []}
        grouped[group_key]['variants'].append({'id': p.pk, 'name': p.name, 'label': p.variant_label or p.name,
            'price': p.price, 'capacity': item['capacity'], 'artwork': p.artwork, 'image': item['image']})
    groups = list(grouped.values())
    for group in groups:
        group['variant_ids'] = ','.join(str(v['id']) for v in group['variants'])
        group['from_price'] = min(v['price'] for v in group['variants'])
        group['selected'] = next((v for v in group['variants'] if v['capacity'] > 0), group['variants'][0])
        group['available'] = any(v['capacity'] > 0 for v in group['variants'])
        group['search_name'] = group['name'] + ' ' + ' '.join(v['name'] + ' ' + v['label'] for v in group['variants'])
    drink_groups = [g for g in groups if not g['is_add_on']]
    add_on_groups = [g for g in groups if g['is_add_on']]
    return render(request, 'cafe/shop.html' if public else 'cafe/pos.html',
        {'page': 'pos', 'categories': Category.objects.filter(products__is_active=True, products__is_add_on=False).distinct(),
         'products': products, 'products_data': data, 'drink_groups': drink_groups, 'add_on_groups': add_on_groups,
         'checkout_key': key, 'public': public})

def shop(request):
    return _ordering_page(request, public=True)

@login_required
def pos(request):
    return _ordering_page(request)

def api_errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ValidationError as exc:
            return JsonResponse({'ok': False, 'error': errors_text(exc)}, status=400)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'Please check your order details and try again.'}, status=400)
    return wrapped

@require_POST
@api_errors
def submit_order(request):
    data = json.loads(request.body)
    if not isinstance(data, dict):
        raise ValidationError('Invalid order request.')
    public = data.get('source') == 'online'
    if not public and not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'error': 'Sign in before using the counter.'}, status=403)
    key = str(data.get('submission_key', ''))
    if key not in request.session.get('checkout_keys', []):
        raise ValidationError('Your checkout expired. Reload the page and try again.')
    if public:
        if len(str(data.get('customer_name', '')).strip()) < 2:
            raise ValidationError('Enter your name for pickup.')
        phone = str(data.get('phone', '')).strip()
        if len(phone) < 7 or len(phone) > 30 or not all(c.isdigit() or c in '+- ()' for c in phone):
            raise ValidationError('Enter a valid contact number.')
        previous = request.session.get('online_orders', [])
        active = Order.objects.filter(token__in=previous, paid=False, status__in=['pending', 'preparing', 'ready'])
        if active.count() >= 3 and not Order.objects.filter(submission_key=key).exists():
            raise ValidationError('Please collect your open orders before placing another one.')
    order = create_order(lines=data.get('items'), submission_key=key,
        user=request.user if request.user.is_authenticated and not public else None,
        source='online' if public else 'pos', customer_name=data.get('customer_name', ''), phone=data.get('phone', ''),
        order_type=data.get('order_type', 'pickup' if public else 'dine_in'), table_number=data.get('table_number', ''),
        notes=data.get('notes', ''), discount_percent=data.get('discount_percent', 0),
        payment_method=data.get('payment_method', 'cash'), paid=data.get('paid') is True,
        amount_tendered=data.get('amount_tendered', 0))
    if public:
        request.session['online_orders'] = list(dict.fromkeys(request.session.get('online_orders', []) + [str(order.token)]))[-10:]
    return JsonResponse({'ok': True, 'number': order.number,
        'redirect': reverse('tracking', args=[order.token]) if public else reverse('order_detail', args=[order.pk])})

def private_order_response(response):
    """Tracking tokens also grant receipt access; keep these responses private."""
    response['Cache-Control'] = 'no-store, private, max-age=0'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response

def tracking(request, token):
    order = get_object_or_404(Order.objects.prefetch_related(Prefetch('items', queryset=OrderItem.objects.select_related('parent_item'))), token=token)
    response = render(request, 'cafe/tracking.html', {'order': order, 'public': True})
    return private_order_response(response)

@require_safe
def tracking_status(request, token):
    order = get_object_or_404(Order.objects.only('paid', 'status', 'refund_due'), token=token)
    return private_order_response(JsonResponse({'paid': order.paid, 'status': order.status,
        'refund_due': order.refund_due}))

@require_safe
def customer_receipt(request, token):
    # A public receipt uses the private tracking token and confirmed payment.
    # Query strings and the customer's browser cannot mark an order as paid.
    order = get_object_or_404(Order.objects.filter(paid=True).prefetch_related(
        Prefetch('items', queryset=OrderItem.objects.select_related('parent_item'))), token=token)
    return private_order_response(render(request, 'cafe/receipt.html',
        {'order': order, 'customer_receipt': True}))

@login_required
def orders(request):
    qs = Order.objects.prefetch_related('items')
    query, status = request.GET.get('q', '').strip(), request.GET.get('status', '')
    payment = request.GET.get('payment', '')
    if query:
        condition = Q(customer_name__icontains=query) | Q(phone__icontains=query)
        number = query.upper().replace('CDL-', '')
        if number.isdigit():
            condition |= Q(pk=int(number))
        qs = qs.filter(condition)
    if status in dict(Order.STATUS):
        qs = qs.filter(status=status)
    if payment == 'unpaid':
        qs = qs.filter(paid=False).exclude(status='cancelled')
    elif payment == 'refund':
        qs = qs.filter(refund_due=True)
    elif payment == 'paid':
        qs = qs.filter(paid=True).exclude(status='cancelled')
    if request.GET.get('date'):
        try:
            qs = qs.filter(created_at__date=date.fromisoformat(request.GET['date']))
        except ValueError:
            messages.error(request, 'Choose a valid date.')
    counts = {row['status']: row['count'] for row in Order.objects.values('status').annotate(count=Count('id'))}
    tabs = [{'value': value, 'label': label, 'count': counts.get(value, 0)} for value, label in Order.STATUS]
    return render(request, 'cafe/orders.html', {'page': 'orders', 'orders': Paginator(qs, 15).get_page(request.GET.get('page')),
                 'tabs': tabs, 'status': status, 'query': query, 'payment': payment})

@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order.objects.prefetch_related(Prefetch('items', queryset=OrderItem.objects.select_related('parent_item')), 'events__user'), pk=pk)
    actions = [{'value': value, 'label': dict(Order.STATUS)[value]} for value in TRANSITIONS[order.status] if value != 'cancelled']
    return render(request, 'cafe/order_detail.html', {'page': 'orders', 'order': order,
                  'actions': actions, 'can_cancel': 'cancelled' in TRANSITIONS[order.status]})

@login_required
@require_POST
def order_action(request, pk):
    get_object_or_404(Order, pk=pk)
    try:
        action = request.POST.get('action')
        if action == 'payment':
            record_payment(pk, request.POST.get('method'), request.POST.get('amount', 0), request.user)
            messages.success(request, 'Payment recorded.')
        elif action == 'refund':
            if not is_manager(request.user):
                return HttpResponse('Manager access is required.', status=403)
            record_refund(pk, request.user)
            messages.success(request, 'Manual refund recorded.')
        else:
            change_order_status(pk, action, request.user)
            messages.success(request, 'Order updated.')
    except ValidationError as exc:
        messages.error(request, errors_text(exc))
    return redirect('order_detail', pk=pk)

@login_required
def receipt(request, pk):
    order = get_object_or_404(Order.objects.prefetch_related(Prefetch('items', queryset=OrderItem.objects.select_related('parent_item'))), pk=pk)
    return render(request, 'cafe/receipt.html', {'order': order})

@login_required
def inventory(request):
    qs = Ingredient.objects.all()
    query, stock = request.GET.get('q', '').strip(), request.GET.get('stock', '')
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(sku__icontains=query))
    if stock == 'low':
        qs = qs.filter(quantity__lte=F('reorder_level'), is_active=True)
    elif stock == 'inactive':
        qs = qs.filter(is_active=False)
    else:
        qs = qs.filter(is_active=True)
    storage = request.GET.get('storage', '')
    if storage in dict(Ingredient.STORAGE_CHOICES):
        qs = qs.filter(storage_type=storage)
    active = Ingredient.objects.filter(is_active=True)
    return render(request, 'cafe/inventory.html', {'page': 'inventory', 'ingredients': Paginator(qs, 15).get_page(request.GET.get('page')),
        'ingredient_count': active.count(), 'inventory_value': sum((i.stock_value for i in active), Decimal('0')),
        'query': query, 'stock': stock, 'storage': storage, 'storage_choices': Ingredient.STORAGE_CHOICES,
        'estimated_count': active.filter(is_estimated=True).count(), 'out_of_stock': active.filter(quantity=0).count()})

@manager_required
def ingredient_edit(request, pk=None):
    instance = get_object_or_404(Ingredient, pk=pk) if pk else None
    form = IngredientForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            if pk:
                # Load the current balance under lock rather than saving a stale form instance.
                locked = Ingredient.objects.select_for_update().get(pk=pk)
                for field in form.Meta.fields:
                    if field != 'opening_stock' and field != 'unit':
                        setattr(locked, field, form.cleaned_data[field])
                locked.save()
            else:
                locked = form.save()
                if form.cleaned_data.get('opening_stock'):
                    adjust_stock(locked.pk, form.cleaned_data['opening_stock'], 'opening', request.user, 'Opening balance')
        messages.success(request, 'Ingredient saved.')
        return redirect('inventory')
    return render(request, 'cafe/form.html', {'page': 'inventory', 'form': form, 'title': 'Edit ingredient' if pk else 'New ingredient',
                  'subtitle': 'Keep every gram, milliliter, and piece accounted for.', 'back': 'inventory'})

@manager_required
def adjustment(request):
    form = AdjustmentForm(request.POST or None, initial={'ingredient': request.GET.get('ingredient')})
    if request.method == 'POST' and form.is_valid():
        try:
            d = form.cleaned_data
            adjust_stock(d['ingredient'].pk, d['quantity'], d['kind'], request.user, d['reason'])
            messages.success(request, 'Stock updated and recorded in the movement history.')
            return redirect('inventory')
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, 'cafe/form.html', {'page': 'inventory', 'form': form, 'title': 'Adjust stock',
                  'subtitle': 'Record a count correction or ingredients lost to waste.', 'back': 'inventory'})

@login_required
def movements(request):
    qs = StockMovement.objects.select_related('ingredient', 'user', 'order')
    if request.GET.get('ingredient', '').isdigit():
        qs = qs.filter(ingredient_id=int(request.GET['ingredient']))
    if request.GET.get('kind') in dict(StockMovement.KIND):
        qs = qs.filter(kind=request.GET['kind'])
    return render(request, 'cafe/movements.html', {'page': 'inventory', 'movements': Paginator(qs, 25).get_page(request.GET.get('page')),
                  'ingredients': Ingredient.objects.all(), 'kinds': StockMovement.KIND})

@login_required
def menu(request):
    products = catalog()
    if request.GET.get('q'):
        products = products.filter(name__icontains=request.GET['q'])
    return render(request, 'cafe/menu.html', {'page': 'menu', 'products': products, 'categories': Category.objects.all()})

@manager_required
def product_edit(request, pk=None):
    with transaction.atomic():
        instance = get_object_or_404(Product.objects.select_for_update(), pk=pk) if pk else Product()
        form = ProductForm(request.POST or None, request.FILES or None, instance=instance)
        formset = RecipeFormSet(request.POST or None, instance=instance, prefix='recipe')
        if request.method == 'POST' and form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, 'Menu item and recipe saved.')
            return redirect('menu')
    return render(request, 'cafe/product_form.html', {'page': 'menu', 'form': form, 'formset': formset,
                  'title': 'Edit menu item' if pk else 'New menu item'})

@manager_required
def category_add(request):
    form = CategoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Category added.')
        return redirect('menu')
    return render(request, 'cafe/form.html', {'page': 'menu', 'form': form, 'title': 'New category',
                  'subtitle': 'Organize your café menu.', 'back': 'menu'})

@manager_required
def stock_receipts(request):
    qs = Purchase.objects.select_related('ingredient', 'received_by')
    return render(request, 'cafe/stock_receipts.html', {'page': 'stock',
        'receipts': Paginator(qs, 20).get_page(request.GET.get('page'))})

@manager_required
def stock_add(request):
    form = AddStockForm(request.POST or None, initial={'ingredient': request.GET.get('ingredient')})
    if request.method == 'POST' and form.is_valid():
        try:
            add_stock(form.save(commit=False), request.user)
            messages.success(request, 'Stock added. The inventory balance and movement history are updated.')
            return redirect('stock_receipts')
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, 'cafe/form.html', {'page': 'stock', 'form': form, 'title': 'Add supply stock',
        'subtitle': 'Choose an ingredient and enter the quantity to add. Cost and notes are optional.',
        'back': 'stock_receipts', 'submit_label': 'Add stock'})

def report_range(request):
    today = timezone.localdate()
    try:
        start = date.fromisoformat(request.GET.get('start', (today - timedelta(days=6)).isoformat()))
        end = date.fromisoformat(request.GET.get('end', today.isoformat()))
        if end < start or (end - start).days > 366:
            raise ValueError
    except ValueError:
        messages.error(request, 'Select a valid date range of up to 366 days.')
        start, end = today - timedelta(days=6), today
    return start, end

@manager_required
def reports(request):
    start, end = report_range(request)
    qs = Order.objects.filter(status='completed', paid=True, completed_at__date__range=[start, end])
    items = OrderItem.objects.filter(order__in=qs)
    cost = sum((i.unit_cost * i.quantity for i in items), Decimal('0'))
    revenue = sales_for(qs)
    tops = list(items.filter(parent_item__isnull=True).exclude(product__is_add_on=True).values('name').annotate(sold=Sum('quantity'),
                gross_sales=Sum(F('unit_price') * F('quantity'))).order_by('-sold')[:8])
    max_sold = max([t['sold'] for t in tops] + [1])
    for item in tops:
        item['width'] = round(item['sold'] / max_sold * 100)
    chart = chart_days(start, end) if (end - start).days <= 30 else []
    return render(request, 'cafe/reports.html', {'page': 'reports', 'start': start, 'end': end,
        'revenue': revenue, 'cost': cost, 'profit': revenue - cost, 'completed': qs.count(),
        'discount': qs.aggregate(total=Sum('discount'))['total'] or 0, 'top_products': tops, 'chart': chart,
        'refunds_due': Order.objects.filter(refund_due=True).count(),
        'payments': list(qs.values('payment_method').annotate(total=Sum('total'), count=Count('id')))})

def csv_cell(value):
    value = str(value)
    return "'" + value if value.startswith(('=', '+', '-', '@', '\t', '\r')) else value

@manager_required
def export_csv(request, kind):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="coffee_de_luna_{kind}.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    if kind == 'inventory':
        writer.writerow(['SKU', 'Ingredient', 'Unit', 'Quantity', 'Reorder level', 'Unit cost', 'Stock value', 'Active', 'Storage', 'Estimated stock/cost', 'Notes'])
        for i in Ingredient.objects.all():
            writer.writerow([csv_cell(i.sku), csv_cell(i.name), i.unit, i.quantity, i.reorder_level, i.cost_per_unit, i.stock_value, i.is_active, i.get_storage_type_display(), i.is_estimated, csv_cell(i.notes)])
    elif kind == 'sales':
        start, end = report_range(request)
        writer.writerow(['Order', 'Completed (Manila)', 'Customer', 'Source', 'Payment', 'Subtotal', 'Discount', 'Total'])
        for o in Order.objects.filter(status='completed', paid=True, completed_at__date__range=[start, end]):
            writer.writerow([o.number, timezone.localtime(o.completed_at).isoformat(), csv_cell(o.customer_name), o.source,
                             o.payment_method, o.subtotal, o.discount, o.total])
    else:
        return HttpResponse('Unknown export.', status=404)
    return response

@manager_required
def team(request):
    return render(request, 'cafe/team.html', {'page': 'team', 'staff': User.objects.prefetch_related('groups').all().order_by('username')})

@manager_required
def staff_add(request):
    form = StaffForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            if form.cleaned_data['role'] == 'manager':
                user.groups.add(Group.objects.get_or_create(name='Managers')[0])
        messages.success(request, 'Staff account created.')
        return redirect('team')
    return render(request, 'cafe/form.html', {'page': 'team', 'form': form, 'title': 'Add team member',
                  'subtitle': 'Cashiers handle orders. Managers also manage inventory, menu, reports, and staff.', 'back': 'team'})

@manager_required
@require_POST
def staff_toggle(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.pk == request.user.pk or user.is_superuser:
        messages.error(request, 'Your own account and superuser accounts cannot be deactivated here.')
    else:
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        messages.success(request, 'Account access updated.')
    return redirect('team')

@manager_required
def staff_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.pk == request.user.pk:
        return redirect('account')
    if user.is_superuser:
        return HttpResponse('Administrator passwords must be changed through Administration.', status=403)
    form = SetPasswordForm(user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Password updated for {user.username}. Share it with the team member privately.')
        return redirect('team')
    return render(request, 'cafe/form.html', {'page': 'team', 'form': form,
        'title': f'Reset password for {user.username}', 'subtitle': 'Set a new password. Existing passwords cannot be viewed.', 'back': 'team'})

@login_required
def account(request):
    profile_form = ProfileForm(request.POST if request.POST.get('action') == 'profile' else None, instance=request.user)
    password_form = PasswordChangeForm(request.user, request.POST if request.POST.get('action') == 'password' else None)
    if request.method == 'POST':
        if request.POST.get('action') == 'profile' and profile_form.is_valid():
            profile_form.save()
            messages.success(request, 'Profile updated.')
            return redirect('account')
        if request.POST.get('action') == 'password' and password_form.is_valid():
            user = password_form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Password changed.')
            return redirect('account')
    return render(request, 'cafe/account.html', {'page': 'account', 'profile_form': profile_form, 'password_form': password_form})

"""Catalog, recipe inventory, and immutable order snapshots."""
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

ZERO = Decimal('0')

class Ingredient(models.Model):
    UNIT_CHOICES = [('g', 'Grams (g)'), ('ml', 'Milliliters (ml)'), ('pcs', 'Pieces (pcs)')]
    STORAGE_CHOICES = [('unspecified', 'Not specified'), ('dry', 'Dry / shelf-stable'),
                       ('chilled', 'Chilled'), ('frozen', 'Frozen'), ('packaging', 'Packaging')]
    name = models.CharField(max_length=100, unique=True)
    sku = models.CharField(max_length=30, unique=True)
    unit = models.CharField(max_length=5, choices=UNIT_CHOICES)
    storage_type = models.CharField(max_length=15, choices=STORAGE_CHOICES, default='unspecified')
    notes = models.CharField(max_length=250, blank=True)
    is_estimated = models.BooleanField(default=False, verbose_name='Stock and cost are estimates')
    quantity = models.DecimalField(max_digits=13, decimal_places=3, default=0, validators=[MinValueValidator(ZERO)])
    reorder_level = models.DecimalField(max_digits=13, decimal_places=3, default=0, validators=[MinValueValidator(ZERO)])
    cost_per_unit = models.DecimalField(max_digits=12, decimal_places=4, default=0, validators=[MinValueValidator(ZERO)])
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['name']
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gte=0), name='stock_nonnegative'),
                       models.CheckConstraint(condition=models.Q(cost_per_unit__gte=0), name='cost_nonnegative')]
    @property
    def low_stock(self):
        return self.quantity <= self.reorder_level
    @property
    def stock_value(self):
        return self.quantity * self.cost_per_unit
    def __str__(self):
        return f'{self.name} ({self.unit})'

class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    class Meta:
        ordering = ['sort_order', 'name']
    def __str__(self):
        return self.name

class Product(models.Model):
    CUSTOMIZATIONS = [('extra', 'Other extra'), ('espresso', 'Extra espresso'), ('syrup', 'Syrup flavour'),
                      ('milk', 'Milk choice'), ('whip', 'Whipped cream'), ('sea_salt', 'Sea salt cream')]
    ART_CHOICES = [('latte', 'Latte'), ('iced', 'Iced coffee'), ('espresso', 'Espresso'),
                   ('matcha', 'Matcha'), ('chocolate', 'Chocolate'), ('croissant', 'Croissant'), ('cake', 'Cake'),
                   ('frappe', 'Frappé'), ('fruit_tea', 'Fruit tea')]
    name = models.CharField(max_length=100, unique=True)
    menu_name = models.CharField(max_length=80, blank=True, help_text='Optional shared name for size or flavour choices.')
    variant_label = models.CharField(max_length=80, blank=True, help_text='For example: Hot · 8oz or Caramel · Iced · 16oz.')
    menu_key = models.CharField(max_length=80, unique=True, null=True, blank=True, editable=False)
    is_add_on = models.BooleanField(default=False, verbose_name='Add-on item')
    customization_type = models.CharField(max_length=12, choices=CUSTOMIZATIONS, default='extra')
    max_per_drink = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(3)])
    replaces_ingredient = models.ForeignKey(Ingredient, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='milk_alternatives', help_text='For a milk choice only: replace this ingredient with the same amount of the add-on’s single recipe ingredient. Otherwise add the normal portion.')
    recipe_is_estimated = models.BooleanField(default=False, verbose_name='Recipe quantities are estimates')
    recipe_notes = models.CharField(max_length=250, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    description = models.CharField(max_length=240, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    image = models.ImageField(upload_to='menu/', blank=True)
    artwork = models.CharField(max_length=20, choices=ART_CHOICES, default='latte')
    badge = models.CharField(max_length=25, blank=True)
    is_active = models.BooleanField(default=True)
    class Meta:
        ordering = ['category__sort_order', 'name']
        constraints = [models.CheckConstraint(condition=models.Q(price__gt=0), name='positive_price')]
    @property
    def capacity(self):
        recipes = list(self.recipe_items.all())
        if not self.is_active or not recipes or any(not r.ingredient.is_active for r in recipes):
            return 0
        return min(int(r.ingredient.quantity // r.quantity) for r in recipes)
    @property
    def recipe_cost(self):
        return sum((r.quantity * r.ingredient.cost_per_unit for r in self.recipe_items.all()), ZERO)
    def __str__(self):
        return self.name

class RecipeItem(models.Model):
    product = models.ForeignKey(Product, related_name='recipe_items', on_delete=models.CASCADE)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal('0.001'))])
    class Meta:
        constraints = [models.UniqueConstraint(fields=['product', 'ingredient'], name='unique_recipe_ingredient'),
                       models.CheckConstraint(condition=models.Q(quantity__gt=0), name='positive_recipe_quantity')]
    def __str__(self):
        return f'{self.product}: {self.quantity} {self.ingredient.unit} {self.ingredient.name}'

class Order(models.Model):
    STATUS = [('pending', 'Pending'), ('preparing', 'Preparing'), ('ready', 'Ready'),
              ('completed', 'Completed'), ('cancelled', 'Cancelled')]
    TYPES = [('dine_in', 'Dine in'), ('takeaway', 'Takeaway'), ('pickup', 'Pickup')]
    PAYMENT = [('cash', 'Cash'), ('gcash', 'GCash · manual'), ('card', 'Card · external terminal')]
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    submission_key = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    customer_name = models.CharField(max_length=100, default='Walk-in guest')
    phone = models.CharField(max_length=30, blank=True)
    order_type = models.CharField(max_length=12, choices=TYPES, default='dine_in')
    table_number = models.CharField(max_length=12, blank=True)
    source = models.CharField(max_length=10, choices=[('pos', 'Counter'), ('online', 'Online')], default='pos')
    status = models.CharField(max_length=12, choices=STATUS, default='pending')
    payment_method = models.CharField(max_length=10, choices=PAYMENT, default='cash')
    paid = models.BooleanField(default=False)
    refund_due = models.BooleanField(default=False)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    amount_tendered = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.CharField(max_length=400, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-created_at']
    @property
    def number(self):
        return f'CDL-{self.pk:05d}'
    @property
    def change(self):
        return max(ZERO, self.amount_tendered - self.total) if self.payment_method == 'cash' else ZERO
    @property
    def drink_count(self):
        return sum(item.quantity for item in self.items.all() if item.parent_item_id is None)
    def __str__(self):
        return self.number

class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, null=True, on_delete=models.SET_NULL)
    parent_item = models.ForeignKey('self', null=True, blank=True, related_name='add_ons', on_delete=models.CASCADE)
    customization_summary = models.CharField(max_length=400, blank=True)
    name = models.CharField(max_length=100)
    quantity = models.PositiveSmallIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    class Meta:
        ordering = ['pk']
    @property
    def line_total(self):
        return self.unit_price * self.quantity

class StockMovement(models.Model):
    KIND = [('opening', 'Opening balance'), ('receive', 'Stock added'), ('sale', 'Order reservation'),
            ('return', 'Order cancellation'), ('waste', 'Waste / spoilage'), ('adjust', 'Stock adjustment')]
    ingredient = models.ForeignKey(Ingredient, related_name='movements', on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=KIND)
    quantity = models.DecimalField(max_digits=13, decimal_places=3)
    balance_after = models.DecimalField(max_digits=13, decimal_places=3)
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.PROTECT)
    note = models.CharField(max_length=250)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at', '-pk']

class OrderIngredient(models.Model):
    """A recipe snapshot so cancellation remains correct after recipe edits."""
    order = models.ForeignKey(Order, related_name='ingredients_used', on_delete=models.CASCADE)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=13, decimal_places=3)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['order', 'ingredient'], name='unique_order_ingredient')]

class Purchase(models.Model):
    """Stock added directly to inventory; the existing table preserves receipt history."""
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=13, decimal_places=3, validators=[MinValueValidator(Decimal('0.001'))])
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, validators=[MinValueValidator(ZERO)])
    reference = models.CharField(max_length=80, blank=True)
    notes = models.CharField(max_length=250, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'stock addition'
        verbose_name_plural = 'stock additions'
    @property
    def total(self):
        return self.quantity * self.unit_cost

class LoginAttempt(models.Model):
    """Only hashes are stored, never raw IP addresses or passwords."""
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveSmallIntegerField(default=0)
    last_attempt = models.DateTimeField(auto_now=True)

class OrderEvent(models.Model):
    order = models.ForeignKey(Order, related_name='events', on_delete=models.CASCADE)
    message = models.CharField(max_length=250)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at', '-pk']

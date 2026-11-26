from django.contrib import admin
from .models import Category, Ingredient, Order, OrderEvent, OrderIngredient, OrderItem, Product, Purchase, RecipeItem, StockMovement

class AuditAdmin(admin.ModelAdmin):
    """Operational records are changed through app services, preserving the ledger."""
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Ingredient)
class IngredientAdmin(AuditAdmin):
    list_display = ['name', 'sku', 'quantity', 'unit', 'reorder_level', 'is_active']
    search_fields = ['name', 'sku']

@admin.register(Order)
class OrderAdmin(AuditAdmin):
    list_display = ['number', 'customer_name', 'status', 'paid', 'total', 'created_at']
    list_filter = ['status', 'paid', 'source']
    search_fields = ['customer_name']

for model in [Product, RecipeItem, OrderItem, OrderIngredient, OrderEvent, Purchase, StockMovement]:
    admin.site.register(model, AuditAdmin)
admin.site.register(Category)

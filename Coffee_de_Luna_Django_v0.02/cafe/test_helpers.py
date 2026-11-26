"""Small fixtures for isolated service tests and the built-in menu tests."""
from importlib import import_module
from types import SimpleNamespace
from django.apps import apps
from django.db import connection
from .models import Category, Ingredient, Order, Product, Purchase, StockMovement


def ensure_catalog():
    import_module('cafe.migrations.0006_builtin_menu').install_catalog(apps, SimpleNamespace(connection=connection))


def empty_catalog():
    # Called only in isolated test transactions before constructing tiny recipes.
    StockMovement.objects.all().delete()
    Order.objects.all().delete()
    Product.objects.all().delete()
    Purchase.objects.all().delete()
    Ingredient.objects.all().delete()
    Category.objects.all().delete()

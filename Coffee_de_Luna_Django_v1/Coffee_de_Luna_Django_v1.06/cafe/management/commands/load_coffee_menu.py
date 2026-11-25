"""Load the supplied menu and clearly marked ingredient/recipe estimates."""
import json
from decimal import Decimal
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from cafe.models import Category, Ingredient, Product, RecipeItem
from cafe.services import adjust_stock


class Command(BaseCommand):
    help = 'Add the supplied Coffee de Luna menu, estimated recipes, and initial ingredient stocks. Existing records are kept.'

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(__file__).resolve().parents[2] / 'data' / 'coffee_menu.json'
        data = json.loads(path.read_text())
        categories = {}
        for index, name in enumerate(data['categories'], 1):
            categories[name] = Category.objects.get_or_create(name=name, defaults={'sort_order': index})[0]
        ingredients = {}
        added_ingredients = added_products = 0
        for row in data['ingredients']:
            ingredient = Ingredient.objects.filter(sku=row['sku']).first() or Ingredient.objects.filter(name=row['name']).first()
            if ingredient and ingredient.unit != row['unit']:
                raise CommandError(f"{row['name']} already exists in a different unit. Resolve that ingredient before importing.")
            if not ingredient:
                ingredient = Ingredient.objects.create(name=row['name'], sku=row['sku'], unit=row['unit'],
                    storage_type=row['storage_type'], reorder_level=Decimal(row['reorder_level']),
                    cost_per_unit=Decimal(row['cost_per_unit']), notes=row['notes'], is_estimated=True)
                adjust_stock(ingredient.pk, row['opening_stock'], 'opening', None, 'Menu setup: assumed opening stock, verify by actual count')
                added_ingredients += 1
            ingredients[row['key']] = ingredient
        for row in data['products']:
            product = Product.objects.filter(menu_key=row['key']).first() or Product.objects.filter(name=row['name']).first()
            if product:
                continue
            product = Product.objects.create(name=row['name'], menu_key=row['key'], menu_name=row['menu_name'],
                variant_label=row['variant_label'], category=categories[row['category']], price=Decimal(row['price']),
                artwork=row['artwork'], description=row['description'], is_add_on=row['is_add_on'],
                customization_type=row.get('customization_type', 'extra'), max_per_drink=row.get('max_per_drink', 1),
                replaces_ingredient=ingredients.get(row.get('replaces_key')),
                recipe_is_estimated=True, recipe_notes='Estimated quantities and ingredient forms for setup; confirm the café recipe before actual service.')
            RecipeItem.objects.bulk_create([RecipeItem(product=product, ingredient=ingredients[key], quantity=Decimal(quantity))
                                           for key, quantity in row['recipe'].items()])
            added_products += 1
        self.stdout.write(self.style.SUCCESS(f'Menu ready: {added_products} new menu variants and {added_ingredients} new ingredients. Existing prices, recipes, and stock balances were kept.'))
        self.stdout.write('Opening quantities, costs, storage forms, and recipes are estimates. Review MENU_ASSUMPTIONS.md and verify actual supplies.')

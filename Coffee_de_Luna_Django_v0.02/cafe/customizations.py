"""One drink's recipe, including its chosen extras and any milk replacement.

Both availability hints and checkout use this planner. Checkout still locks stock
and checks the combined requirements of the entire basket before reserving it.
"""
from collections import defaultdict
from decimal import Decimal
from django.core.exceptions import ValidationError


def extra_label(product):
    labels = {'espresso': 'Extra espresso', 'whip': 'Extra whipped cream', 'sea_salt': 'Sea salt cream'}
    if product.customization_type == 'syrup':
        return f'{product.variant_label or product.menu_name or product.name} syrup'
    return labels.get(product.customization_type, product.menu_name or product.name.replace(' (Add on)', ''))


def plan_drink(product, extras):
    """Return separately priced parts with effective ingredient amounts per portion."""
    if product.is_add_on:
        raise ValidationError('Choose a drink, then attach add-ons using Customize.')
    recipe = list(product.recipe_items.all())
    if not product.is_active or not recipe:
        raise ValidationError(f'{product.name} is currently unavailable.')
    base = {row.ingredient_id: (row.ingredient, row.quantity) for row in recipe}
    parts = [{'product': product, 'name': product.name, 'portions': 1, 'ingredients': base}]
    used_types, summary = set(), []
    for addon, portions in extras:
        kind = addon.customization_type
        if (not addon.is_active or not addon.is_add_on or kind not in dict(addon.CUSTOMIZATIONS)
                or not 1 <= portions <= min(addon.max_per_drink, 3)):
            raise ValidationError('An add-on is unavailable or exceeds its limit per drink. Refresh your menu.')
        if kind != 'extra' and kind in used_types:
            raise ValidationError('Choose only one option for each type of customization per drink.')
        if kind in ('milk', 'whip', 'sea_salt') and portions != 1:
            raise ValidationError('Choose one portion of this topping or milk option per drink.')
        used_types.add(kind)
        rows = list(addon.recipe_items.all())
        if not rows:
            raise ValidationError(f'{addon.name} is currently unavailable.')
        ingredients = {row.ingredient_id: (row.ingredient, row.quantity) for row in rows}
        label = extra_label(addon)
        if addon.replaces_ingredient_id:
            if kind != 'milk' or len(rows) != 1 or rows[0].ingredient_id == addon.replaces_ingredient_id:
                raise ValidationError('This milk choice needs a valid single-ingredient replacement recipe.')
            replaced = base.get(addon.replaces_ingredient_id)
            if replaced:
                if replaced[0].unit != rows[0].ingredient.unit:
                    raise ValidationError('The milk choice and replaced ingredient must use the same unit.')
                del base[addon.replaces_ingredient_id]
                ingredients[rows[0].ingredient_id] = (rows[0].ingredient, replaced[1])
                label += ' (replaces whole milk)' if replaced[0].sku == 'CDL-002' else f' (replaces {replaced[0].name})'
            else:
                label = 'Add ' + label
        if any(not ingredient.is_active for ingredient, amount in ingredients.values()):
            raise ValidationError(f'{addon.name} is currently unavailable.')
        parts.append({'product': addon, 'name': label[:100], 'portions': portions, 'ingredients': ingredients})
        summary.append(label + (f' × {portions}' if portions > 1 else ''))
    if any(not ingredient.is_active for ingredient, amount in base.values()):
        raise ValidationError(f'{product.name} is currently unavailable with this recipe. Choose another milk or drink.')
    parts[0]['summary'] = ' · '.join(summary)[:400]
    return parts


def drink_capacity(product, extras=()):
    try:
        parts = plan_drink(product, extras)
    except ValidationError:
        return 0
    needs, ingredients = defaultdict(Decimal), {}
    for part in parts:
        for key, (ingredient, amount) in part['ingredients'].items():
            needs[key] += amount * part['portions']
            ingredients[key] = ingredient
    return min((int(ingredients[key].quantity // amount) for key, amount in needs.items()), default=0)

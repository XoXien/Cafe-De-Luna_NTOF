# Coffee de Luna · v1.06

Django inventory and ordering configured from the supplied Coffee de Luna menu image. Use your **existing virtual environment**.

From the folder containing `manage.py`, with your environment activated:

```shell
python manage.py migrate
python manage.py load_coffee_menu
python manage.py runserver
```

For a new installation without an administrator, run `python manage.py createsuperuser` once before starting the server. Existing accounts keep their current passwords. If dependencies are missing, install them into your active environment using `python -m pip install -r requirements.txt`.

Choose a drink → **Customize** → size/flavour → milk and extras → **Add to order**. Each extra is attached to that drink. The screen shows the base price, each added charge, price per drink, and quantity total. **Edit drink** reopens its choices from the basket.

For example: Iced Vanilla Latte ₱110 + extra espresso ₱40 + oat milk ₱35 = **₱185 per drink**. Two of that configuration total ₱370. A plain Vanilla Latte stays on a separate line.

Oat milk replaces the whole-milk quantity in a milk-based drink; for an Americano it adds the configured extra portion. Cream and condensed milk already in the recipe stay included. See MENU_ASSUMPTIONS.md for these editable assumptions.

This update includes migration `0004_drink_customizations`. Keep your current database and run `migrate` before opening the updated ordering page. Existing accounts, stock, prices, recipes, and historical orders are retained.

The menu includes 52 drink variants, 8 add-on variants, and 34 ingredient/packaging supplies. Prices and offered sizes follow the supplied image. Fruit teas include crystals-or-chia choices.

Frozen strawberry and mango purées, prepared toppings, syrups, concentrates, powders, and packaging are tracked in Inventory. Recipes, opening balances, costs, and storage forms are estimates; read **MENU_ASSUMPTIONS.md**.

The menu import is explicit and repeatable. Existing balances, edited prices, and recipes are retained. For later starts, use `python manage.py runserver`.

No virtual environment, default accounts, customer records, orders, or database file are packaged. No supplier module is required.

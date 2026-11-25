# Upgrade to Coffee de Luna v1.06

1. Stop the server and back up your database and uploaded menu photos.
2. Copy the updated source into your installation while keeping your own virtual environment, working database, media, local secret, and environment settings.
3. Activate your existing environment and open the folder containing `manage.py`.
4. Run:

```shell
python manage.py migrate
python manage.py load_coffee_menu
python manage.py runserver
```

The menu import keeps existing balances, edited prices, recipes, accounts, and orders. If your database already contains the requested menu, it is safe to repeat the command.

For a fresh database, run `python manage.py createsuperuser` once before starting the server. There are no preset credentials.

This release adds migration `0004_drink_customizations` for per-drink extras and milk choices. Apply it before opening either ordering page. It classifies the existing source-menu add-ons and links the oat-milk option to the whole-milk ingredient. It preserves existing prices, recipes, quantities, cost history, accounts, and order records. Historical flat extras remain as originally recorded because their intended drink cannot be inferred.

Oat milk now replaces the whole-milk amount in a milk-based drink for the menu's ₱35 charge. For drinks without whole milk, it adds the extra's configured portion. Existing cream and condensed milk remain. Confirm this assumption with the café and edit the option/recipe if needed. No stock is changed by the upgrade itself.

The new basket format keeps each drink and its extras together. Open a fresh ordering page after updating; an old tab must be refreshed to use the new checkout format. The v1.05 flat basket is not imported into the new per-drink basket because the association of its extras is unknown.

Use your existing virtual environment and ordinary manage.py commands. No startup scripts or additional environment are supplied.

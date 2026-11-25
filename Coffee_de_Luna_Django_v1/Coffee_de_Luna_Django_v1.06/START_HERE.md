# Coffee de Luna · v1.06

Use your existing virtual environment. Activate it as you normally do, then open a terminal in the project folder containing `manage.py`.

## First setup or after an update

```shell
python manage.py migrate
python manage.py load_coffee_menu
```

If your existing environment needs the project's dependencies, run `python -m pip install -r requirements.txt` in that activated environment.

The menu command loads the requested menu and estimated ingredient inventory from the supplied photo. Repeating it preserves existing balances, prices, recipes, accounts, and orders. See **MENU_ASSUMPTIONS.md** for all recipe, storage, quantity, and cost assumptions.

If this is a fresh database without an administrator, create your own account once:

```shell
python manage.py createsuperuser
```

Existing installations keep their accounts and passwords. The download contains no database file or preset credentials. Keep your current database and uploaded photos when updating an existing installation.

## Start the app

```shell
python manage.py runserver
```

Open **http://127.0.0.1:8000/login/** for staff, or **http://127.0.0.1:8000/** for the customer menu. Keep the terminal open while using the app; press **Ctrl+C** to stop it.

For subsequent starts, activate your existing environment and run `python manage.py runserver`. There is no automatic menu import at server startup; use the management command when needed.

## Set up your café

After creating your administrator and signing in, review MENU_ASSUMPTIONS.md, then:

1. Review the imported ingredients, storage labels, estimate flags, quantities, and unit costs in **Inventory**.
2. Choose **Add stock**, select an ingredient, and enter the quantity to add. Cost per unit and notes are optional.
3. Verify the imported menu prices and estimated recipes in **Menu & recipes**. Size, flavour, and fruit-tea topping choices have their own recipes.
4. Create manager and cashier accounts through **Our team**.
5. Use **New order** for counter orders, or the customer menu for pickup ordering.

The provided menu and estimated ingredient stocks are preloaded after the import command runs. Sales and staff accounts remain empty until you create and use them. Verify recipe and stock estimates before actual service.

## Pages

| Page | Address |
| --- | --- |
| Customer menu and ordering | http://127.0.0.1:8000/ |
| Staff sign in | http://127.0.0.1:8000/login/ |
| Administrator dashboard | http://127.0.0.1:8000/app/admin/ |
| Manager/cashier overview | http://127.0.0.1:8000/app/ |
| Counter ordering | http://127.0.0.1:8000/app/counter/ |
| Order queue and history | http://127.0.0.1:8000/app/orders/ |
| Ingredient inventory | http://127.0.0.1:8000/app/inventory/ |
| Menu and recipes | http://127.0.0.1:8000/app/menu/ |
| Add supply stock | http://127.0.0.1:8000/app/stock/add/ |
| Stock additions | http://127.0.0.1:8000/app/stock/ |
| Sales reports | http://127.0.0.1:8000/app/reports/ |
| Team accounts | http://127.0.0.1:8000/app/team/ |
| Django administration | http://127.0.0.1:8000/admin/ |

## The administrator dashboard

Administrators land on the custom dashboard automatically. It includes 7-day and 30-day sales, previous-period comparisons, daily sales bars, the current order queue, unpaid balances, refund follow-ups, stock alerts, favorites, recorded payment totals, workspace counts, recent activity, and management shortcuts. Report and CSV links carry the selected dates.

The custom admin dashboard requires a superuser account. Managers and cashiers continue to use their overview.

## Add supply stock

Open **Add stock** in the sidebar or the **Add stock** button in Inventory. The only required fields are the ingredient and quantity. The ingredient selector shows its base unit (g, ml, or pcs); 1 kg is entered as 1,000 g. Leave cost blank to retain the current average cost, or enter the cost per base unit to update the weighted average. Notes are optional.

Saving adds the quantity to inventory immediately. The record shows who added it, the time, quantity, and value in **Stock additions**. **Movement history** also records the change. Admins and managers can add stock; cashiers keep read-only inventory access.

## Customize a drink

1. Choose **Customize** on a drink card.
2. Select the actual menu size and temperature. Flavoured Latte also offers flavour choices; fruit tea offers crystals or chia.
3. Keep the house recipe, or choose milk and optional extras. Each option shows its extra price.
4. Check **Your drink, at a glance** and the live total, then choose **Add to order**.
5. Use **Edit drink** in the basket to change its choices. Differently customized drinks stay on separate lines.

Extras apply to **each drink** in that basket line. To order one plain drink and one with extra espresso, add the plain drink first, then add a second drink with extra espresso. Order notes are for general instructions; drink options are selected on the drink itself.

| Example | Per drink |
| --- | ---: |
| Vanilla Latte · Iced 16oz | ₱110 |
| Extra espresso · one portion | +₱40 |
| Oat milk instead of whole milk | +₱35 |
| Configured drink total | **₱185** |
| Two of this drink | **₱370** |

Oat milk replaces only the whole milk in a milk-based recipe, in equal volume. Drinks without whole milk show **Add Oat Milk**, using the extra's normal recipe portion (assumed 100 ml). Cream, condensed milk, and other ingredients remain as defined in the recipe. Frappés already include an estimated topping portion; **Extra whipped cream** adds more. Recipes and portion limits remain estimates to verify with the café.

Prices and effective ingredient requirements are checked by the server for the entire basket. A stock error keeps the basket so you can edit it and retry. The counter and customer pages use the same customization flow, and order details, tracking, and receipts show each extra beside its drink.

## Orders and inventory

- Ingredients use **grams, milliliters, or pieces**. A 1 kg delivery is entered as **1,000 g**. Unit costs use the same base unit.
- Every menu item needs a recipe per serving. A drink can require beans, milk, and a cup.
- Stock is reserved when an order is placed. Requirements are combined across the cart, and insufficient stock rejects the whole order.
- Repeated checkout submissions reuse the same order. Preparation and completion do not deduct stock again.
- Cancelling an open order returns its original reserved quantities once, even if its recipe changed later.
- Paid cancellations are flagged for a manual refund. After issuing it, a manager confirms the refund in the order details.
- Complete an order by choosing **Start preparing**, **Mark ready for pickup**, recording payment, and **Complete order**.
- **Add stock** increases the chosen ingredient balance and records the addition. If cost is blank, the current average cost is used; if provided, the weighted average is updated. No supplier or invoice is required. Use **Adjust stock** for count corrections or negative waste entries, with a reason.
- Archive ingredients or menu items when they are no longer used. Missing recipes and inactive ingredients block ordering.

Customers can place an order without a staff account. Their private tracking link shows progress when they choose **Refresh status**. Guest timelines, automated expiry events, and audit records whose staff account was deleted render safely in this version.

## Payments and reports

Cash payments calculate change. GCash and card selections record payments already confirmed on your own app or terminal; no live gateway is included. Customer orders remain unpaid until staff record the payment.

All prices use Philippine pesos, and operational dates use Asia/Manila. Reports include paid, completed orders by completion date. Gross profit subtracts ingredient cost snapshots from discounted sales and excludes rent, labor, waste, and other expenses. Print receipts are order acknowledgments, not tax invoices.

## Team access

Cashiers handle orders, payments, and receipts and can view stock and recipes. Managers also manage stock, menu items, stock additions, reports, and staff. Managers can set a new staff password but cannot view the old password. Administrators have the custom admin dashboard and Django Administration.

## Uncollected online orders

Staff can cancel uncollected orders. To release stock from unpaid, pending online orders older than 30 minutes:

```powershell
python manage.py expire_pending_orders --minutes 30
```

On a hosted installation, schedule this command with the host's scheduler. It does not expire paid or preparing orders. Expiry is not automatic until the command is scheduled.

## Checks and hosting

```powershell
python manage.py check
python manage.py test
```

For hosting, use a Python-capable WSGI/ASGI host and set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`, and `DJANGO_CSRF_TRUSTED_ORIGINS` as environment variables. `.env.example` is a reference and is not loaded automatically. Use HTTPS, run `collectstatic`, and serve `/static/` and `/media/` from their configured directories. `config/wsgi.py` provides the WSGI application. Use Django runserver for local development and a WSGI/ASGI server for hosting.

Back up your newly created database and uploaded photos while the server is stopped. No API key is required. Dependency installation guidance: https://docs.djangoproject.com/en/5.2/topics/install/

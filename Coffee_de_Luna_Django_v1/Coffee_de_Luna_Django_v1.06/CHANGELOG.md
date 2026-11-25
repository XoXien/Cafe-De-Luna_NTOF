# Coffee de Luna v1.06

- Replaced separate extra-item cards with a drink customizer shared by customer and counter ordering.
- Added actual menu size/temperature choices, flavoured-latte flavours, fruit-tea toppings, milk choices, extra espresso, extra syrup, and cream options.
- Showed base price, individual upcharges, configured price per drink, and live quantity total before adding a drink.
- Attached extras to each drink in the basket, with editing and separate lines for different configurations.
- Added server-validated nested add-ons, portion limits, per-drink price/ingredient snapshots, and equal-volume whole-milk-to-oat replacement.
- Checked effective stock across the whole basket, including milk swaps; preserved idempotent checkout and exact cancellation returns.
- Updated tracking, receipts, order details, and sales favourites to respect drink/extra relationships.
- Added a migration that preserves existing business data while configuring the known source-menu extras.
- Retained the supplied menu prices, frozen/prepared ingredient assumptions, direct Add stock flow, own-venv setup, and clean archive.

# Coffee de Luna v1.05

- Removed the batch and shell startup scripts.
- Updated setup, upgrade, and menu-import instructions to use the user's existing activated virtual environment.
- Kept ordinary `python manage.py` commands for migrations, menu loading, administrator creation, and the development server.
- Preserved the supplied menu, ingredient inventory preset, recipes, and all application features.

# Coffee de Luna v1.04

- Added the menu from the supplied image, with 52 drink variants and 8 add-on variants at the listed prices.
- Grouped sizes/flavours on the ordering pages and included crystals-or-chia choices for fruit tea.
- Added 34 inventory supplies with estimated recipes, quantities, unit costs, and storage labels.
- Assumed frozen strawberry/mango purées, purchased powders/syrups/concentrates, and prepared chilled toppings.
- Added editable estimate flags and notes for ingredients and recipes, plus a storage filter and CSV export fields.
- Included source-menu, price-reference, and assumed-recipe reference files.
- Added safe repeatable menu loading without resetting existing balances, recipes, prices, accounts, or orders.
- Add-ons require a drink and participate in price calculation, combined stock checks, and cancellation returns.

# Coffee de Luna v1.03

- Removed supplier pages, forms, navigation, administration registration, and model fields.
- Added direct supply stock entry at `/app/stock/add/`, available from the sidebar, Inventory, and admin dashboard.
- Required fields are ingredient and quantity. Unit cost and notes are optional.
- Blank unit cost uses the current cost under the inventory lock; provided costs update the weighted average.
- Stock additions update balances and movement history together in one transaction.
- Added a stock additions journal without supplier or invoice requirements.
- Added a migration that preserves existing ingredients, balances, orders, and stock receipt history.
- Preserved clean installation with no packaged database or default accounts.

# Coffee de Luna v1.02

- Fixed `VariableDoesNotExist: Failed lookup for key [username] in None` for guest order timelines.
- Fixed the same nullable-user issue in admin activity, stock movements, and delivery records, including records whose original staff account was deleted.
- Added a shared `user_label` template filter with safe fallbacks and normal HTML escaping.
- Added regressions for guest orders, public checkout, deleted staff accounts, system expiry events, and blank staff first names.
- Removed the bundled database and all stored accounts, orders, ingredients, recipes, menu items, suppliers, and stock history.
- Removed the demonstration data loader and automatic demo loading from the startup scripts.
- Added first-administrator setup that prompts for credentials on a fresh installation and retains subsequently entered data.

# Coffee de Luna v1.01

Added the custom administrator dashboard, sales analytics, current order and stock alerts, payment filters, and management shortcuts.

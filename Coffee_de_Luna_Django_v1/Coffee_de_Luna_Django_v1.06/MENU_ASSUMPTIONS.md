# Coffee de Luna menu and inventory assumptions · v1.06

The item names, prices, offered temperatures, and cup sizes were transcribed from the menu image in `reference/provided_menu.png`. Hot drinks are 8oz; iced drinks, frappés, and fruit teas are 16oz. A dash in the photo means that variant is not offered: iced Cappuccino and iced Flat White were not added.

The setup includes **52 drink variants, 8 add-on variants, and 34 inventory supplies**. The customer menu groups these into 33 drink cards. Each opens a size/flavour/topping selector and optional milk/extras on the same screen. The price reference is in `reference/menu_prices.csv`.

## Assumptions, not confirmed café recipes

- Strawberry and mango drinks use **ready-made frozen purées**, rather than fresh fruit.
- Ice is frozen stock. Prepared whipped topping, sea salt cream premix, crystal jelly, and milk products are assumed to be kept chilled for service.
- Chocolate sauces, flavour syrups, fruit tea concentrates, cookie crumbs, chocolate crumble, and frappé base are purchased supplies rather than prepared from fresh ingredients.
- Fruit tea still uses **freshly brewed black tea**, as stated on the menu. Crystal/coconut jelly is the assumed meaning of crystals; confirm the actual inclusion. Crystals and chia are separate same-price recipe choices.
- Syrup add-on flavours are assumed to be caramel, salted caramel, vanilla, and hazelnut, matching the flavoured-latte list.
- Espresso portions, recipe quantities, starting stock, reorder levels, storage classifications, and unit costs are estimates. Check actual product labels and the café's methods before treating these as confirmed.
- The oat milk choice costs the menu’s **₱35** and replaces the whole-milk ingredient with the **same volume of oat milk**. Where the base recipe contains no whole milk (for example, Americano), it adds the extra recipe’s normal **100 ml** portion. This is an assumed substitution rule for clearer ordering. Cream, condensed milk, and all other ingredients stay unchanged; the choice does not imply a dairy-free drink. Confirm the café’s actual recipe and charge.
- Included whipped topping in frappés is an assumed 20 ml; the separately charged Whip Cream extra adds another 30 ml. Milk and cream choices allow one portion per drink. Extra espresso and one selected syrup flavour allow 0–3 extra portions, an assumed ordering limit. Each portion is charged at the menu price.
- Packaging is deducted for every serving, including dine-in. Change the recipe if reusable dine-in cups are used.

## Initial inventory estimates

All rows below are marked as estimates in Inventory. The figures are illustrative starting balances and costs, not the café's actual stock count or purchase prices.

| Supply | Storage assumption | Starting quantity | Cost per base unit (PHP) |
| --- | --- | ---: | ---: |
| House blend coffee beans | Dry / shelf-stable | 4000 g | .75 |
| UHT whole milk | Chilled | 12000 ml | .085 |
| Oat milk | Chilled | 4000 ml | .15 |
| Condensed milk | Chilled | 3000 ml | .13 |
| Filtered drinking water | Dry / shelf-stable | 20000 ml | .003 |
| Ice cubes | Frozen | 15000 g | .002 |
| Dark chocolate sauce | Dry / shelf-stable | 2000 ml | .45 |
| White chocolate sauce | Dry / shelf-stable | 1500 ml | .50 |
| Caramel syrup | Dry / shelf-stable | 2000 ml | .35 |
| Salted caramel syrup | Dry / shelf-stable | 1500 ml | .38 |
| Vanilla syrup | Dry / shelf-stable | 1500 ml | .32 |
| Hazelnut syrup | Dry / shelf-stable | 1500 ml | .38 |
| Matcha powder | Dry / shelf-stable | 500 g | 2.80 |
| Dark cocoa powder | Dry / shelf-stable | 1000 g | .65 |
| Frappé base powder | Dry / shelf-stable | 1500 g | .55 |
| Strawberry purée (frozen) | Frozen | 3000 g | .22 |
| Mango purée (frozen) | Frozen | 3000 g | .18 |
| Cookies and cream crumbs | Dry / shelf-stable | 1000 g | .16 |
| Dark chocolate crumble | Dry / shelf-stable | 1000 g | .24 |
| Prepared whipped topping | Chilled | 2000 ml | .14 |
| Sea salt cream premix | Chilled | 1500 ml | .18 |
| Black tea leaves | Dry / shelf-stable | 500 g | .70 |
| Lemon tea concentrate | Dry / shelf-stable | 1500 ml | .25 |
| Lychee tea concentrate | Dry / shelf-stable | 1500 ml | .25 |
| Kiwi tea concentrate | Dry / shelf-stable | 1500 ml | .25 |
| Passion fruit tea concentrate | Dry / shelf-stable | 1500 ml | .25 |
| Crystal jelly (ready-made) | Chilled | 2000 g | .10 |
| Chia seeds | Dry / shelf-stable | 500 g | .35 |
| Sugar syrup | Dry / shelf-stable | 2000 ml | .08 |
| Hot cup · 8oz | Packaging | 200 pcs | 4 |
| Hot cup lid · 8oz | Packaging | 200 pcs | 1.50 |
| Cold cup · 16oz | Packaging | 300 pcs | 3 |
| Cold cup lid · 16oz | Packaging | 300 pcs | 1.50 |
| Straw | Packaging | 300 pcs | .50 |

## Review and change

Use **Inventory → Edit ingredient** to change storage, notes, and estimate status. Use Add stock or an audited stock adjustment to bring balances in line with actual counted supplies. Confirm costs before using the gross-profit figures as business results.

Use **Menu & recipes → Edit item & recipe** to change ingredient quantities, price, flavour label, or the recipe estimate flag. Each serving option has its own recipe and exact listed price. The full assumed recipe list is in `reference/assumed_recipes.csv`.

With your existing virtual environment activated, run `python manage.py migrate` followed by `python manage.py load_coffee_menu`. Repeating it adds missing records and leaves existing prices, recipes, notes, estimate flags, and stock balances unchanged. No customer records, orders, staff accounts, or suppliers are created by this import. Your first administrator is still created using your own credentials.

Add-ons are attached to an individual drink in **Customize**. Their quantities are per drink: two drinks with one extra espresso each are charged for two extras and consume two extra portions. Different configurations stay separate in the basket. The effective base recipe plus each selected extra is reserved together; a milk replacement removes the original whole-milk requirement before adding oat milk. Cancelling returns that exact combined snapshot, even after recipes are edited.

The `Oat Milk` row in `reference/assumed_recipes.csv` is the 100 ml fallback portion used when a drink has no whole milk. For a replacement, the actual amount is taken from the selected drink’s whole-milk recipe quantity (for example, 150 ml hot or 180 ml iced for the provided flavoured lattes). The editable **Replaces ingredient** setting controls this behaviour. Use one different ingredient in the same unit for a milk-replacement recipe. `reference/customization_rules.csv` lists the default option types, limits, and replacement target.

The menu image establishes prices and offered sizes. Replacement behaviour, ingredients, portions, and per-drink limits are implementation assumptions, not confirmed café instructions.

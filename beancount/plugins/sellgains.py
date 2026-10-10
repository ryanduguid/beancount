"""A plugin that cross-checks declared gains against prices on lot sales.

When you sell stock, the gains can be automatically implied by the corresponding
cash amounts. For example, in the following transaction the 2nd and 3rd postings
should match the value of the stock sold:

    1999-07-31 * "Sell"
      Assets:US:BRS:Company:ESPP          -81 ADSK {26.3125 USD}
      Assets:US:BRS:Company:Cash      2141.36 USD
      Expenses:Financial:Fees            0.08 USD
      Income:US:Company:ESPP:PnL      -10.125 USD

The cost basis is checked against: 2141.36 + 008 + -10.125. That is, the balance
checks computes

  -81 x 26.3125  = -2131.3125  +
                    2141.36    +
                       0.08    +
                     -10.125

and checks that the residual is below a small tolerance.

But... usually the income leg isn't given to you in statements. Beancount can
automatically infer it using the balance, which is convenient, like this:

    1999-07-31 * "Sell"
      Assets:US:BRS:Company:ESPP          -81 ADSK {26.3125 USD}
      Assets:US:BRS:Company:Cash      2141.36 USD
      Expenses:Financial:Fees            0.08 USD
      Income:US:Company:ESPP:PnL

Additionally, most often you have the sales prices given to you on your
transaction confirmation statement, so you can enter this:

    1999-07-31 * "Sell"
      Assets:US:BRS:Company:ESPP          -81 ADSK {26.3125 USD} @ 26.4375 USD
      Assets:US:BRS:Company:Cash      2141.36 USD
      Expenses:Financial:Fees            0.08 USD
      Income:US:Company:ESPP:PnL

So in theory, if the price is given (26.4375 USD), we could verify that the
proceeds from the sale at the given price match non-Income postings. That is,
verify that

  -81 x 26.4375  = -2141.4375  +
                    2141.36    +
                       0.08    +

is below a small tolerance value. So this plugin does this.

In general terms, it does the following: For transactions with postings that
have a cost and a price, it verifies that the sum of the positions on all
postings to non-income accounts is below tolerance.

An unpriced acquisition can be valued at cost when it cannot reduce the account's
holdings and has no opposing posting in the same commodity. Transfers, round trips
and uncertain inventory histories still require prices on every cost posting.

This provides yet another level of verification and allows you to elide the
income amounts, knowing that the price is there to provide an extra level of
error-checking in case you enter a typo.
"""

__copyright__ = "Copyright (C) 2015-2021, 2024-2026  Martin Blais"
__license__ = "GNU GPLv2"

import collections
from decimal import Decimal

from beancount.core import account_types
from beancount.core import amount
from beancount.core import convert
from beancount.core import data
from beancount.core import interpolate
from beancount.core import inventory
from beancount.core.number import ZERO
from beancount.core.position import Cost
from beancount.parser import options

__plugins__ = ("validate_sell_gains",)


SellGainsError = collections.namedtuple("SellGainsError", "source message entry")


# A multiplier of the regular tolerance being used. This provides a little extra
# space for satisfying two sets of constraints.
EXTRA_TOLERANCE_MULTIPLIER = 2


def validate_sell_gains(entries, options_map):
    """Check the sum of asset account totals for lots sold with a price on them.

    Args:
      entries: A list of directives.
      options_map: An options map.
    Returns:
      A list of new errors, if any were found.
    """
    errors = []
    acc_types = options.get_account_types(options_map)
    proceed_types = set(
        [acc_types.assets, acc_types.liabilities, acc_types.equity, acc_types.expenses]
    )
    balances = collections.defaultdict(inventory.Inventory)
    incomplete_accounts = set()

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue

        postings_at_cost = [
            posting for posting in entry.postings if posting.cost is not None
        ]
        fully_priced = postings_at_cost and all(
            posting.price is not None for posting in postings_at_cost
        )
        tracked_postings = []
        for posting in entry.postings:
            if (
                isinstance(posting.units, amount.Amount)
                and isinstance(posting.units.number, Decimal)
                and (
                    posting.cost is None
                    or (
                        isinstance(posting.cost, Cost)
                        and isinstance(posting.cost.number, Decimal)
                    )
                )
            ):
                tracked_postings.append(posting)
            else:
                incomplete_accounts.add(posting.account)

        # Check acquisitions against the holdings before this transaction.
        # shortcut: Skip opposing commodity legs until booking supplies reduction markers.
        can_validate = fully_priced or (
            postings_at_cost
            and any(posting.price is not None for posting in postings_at_cost)
            and len(tracked_postings) == len(entry.postings)
            and all(
                posting.account not in incomplete_accounts
                and not balances[posting.account].is_reduced_by(posting.units)
                and not any(
                    other.units.currency == posting.units.currency
                    and other.units.number * posting.units.number < ZERO
                    for other in tracked_postings
                )
                for posting in postings_at_cost
                if posting.price is None
            )
        )
        for posting in tracked_postings:
            balances[posting.account].add_position(posting)
        if not can_validate:
            continue

        # Accumulate the total expected proceeds and the sum of the asset and
        # expenses legs.
        total_price = inventory.Inventory()
        total_proceeds = inventory.Inventory()
        for posting in entry.postings:
            # If the posting is held at cost, add the priced value to the balance.
            if posting.cost is not None:
                price = (
                    posting.price
                    if posting.price is not None
                    else amount.Amount(posting.cost.number, posting.cost.currency)
                )
                total_price.add_amount(amount.mul(price, -posting.units.number))
            else:
                # Otherwise, use the weight and ignore postings to Income accounts.
                atype = account_types.get_account_type(posting.account)
                if atype in proceed_types:
                    total_proceeds.add_amount(convert.get_weight(posting))

        # Compare inventories, currency by currency.
        dict_price = {pos.units.currency: pos.units.number for pos in total_price}
        dict_proceeds = {pos.units.currency: pos.units.number for pos in total_proceeds}

        tolerances = interpolate.infer_tolerances(entry.postings, options_map)
        invalid = False
        for currency, price_number in dict_price.items():
            # Accept a looser than usual tolerance because rounding occurs
            # differently. Also, it would be difficult for the user to satisfy
            # two sets of constraints manually.
            tolerance = tolerances.get(currency) * EXTRA_TOLERANCE_MULTIPLIER

            proceeds_number = dict_proceeds.pop(currency, ZERO)
            diff = abs(price_number - proceeds_number)
            if diff > tolerance:
                invalid = True
                break

        if invalid or dict_proceeds:
            errors.append(
                SellGainsError(
                    entry.meta,
                    "Invalid price vs. proceeds/gains: {} vs. {}; difference: {}".format(
                        total_price, total_proceeds, (total_price + -total_proceeds)
                    ),
                    entry,
                )
            )

    return entries, errors

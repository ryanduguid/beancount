__copyright__ = "Copyright (C) 2015-2019, 2024-2025  Martin Blais"
__license__ = "GNU GPLv2"

import textwrap
import unittest

from beancount import loader
from beancount.core import data
from beancount.ops import validation
from beancount.parser import booking
from beancount.parser import parser
from beancount.parser import printer
from beancount.plugins import sellgains


class TestSellGains(unittest.TestCase):
    def check_exchange(self, ledger, expected_errors=(), options=""):
        entries, errors, _ = loader.load_string(
            'plugin "beancount.plugins.auto_accounts"\n'
            'plugin "beancount.plugins.sellgains"\n' + options + textwrap.dedent(ledger)
        )
        self.assertEqual(list(expected_errors), list(map(type, errors)))
        for error in errors:
            self.assertIs(error.source, error.entry.meta)
            self.assertTrue(error.message.startswith("Invalid price vs. proceeds/gains:"))
        return [entry for entry in entries if isinstance(entry, data.Transaction)]

    def test_commodity_exchange(self):
        ledger = textwrap.dedent("""
        2000-01-01 * "Buy"
          Assets:Old 1.00 OLD {{100.00 USD}}
          Assets:Cash -100.00 USD
        {holding}
        2000-01-02 * "Exchange"
          Assets:Old -1.00 OLD {{}} @ 200.00 USD
          Assets:New 1.00 NEW {{{cost} USD}}{price}
          Income:Gains {income}
        """)
        for cost, income in [("200.00", "-100.00 USD"), ("300.00", "-200.00 USD")]:
            for price in ["", f" @ {cost} USD"]:
                for explicit_income in [False, True]:
                    for existing in [False, True]:
                        with self.subTest(
                            cost=cost,
                            price=price,
                            explicit_income=explicit_income,
                            existing=existing,
                        ):
                            holding = (
                                '2000-01-01 * "Existing holding"\n'
                                f"  Assets:New 1.00 NEW {{{cost} USD}}\n"
                                f"  Assets:Cash -{cost} USD\n"
                                if existing
                                else ""
                            )
                            text = ledger.format(
                                holding=holding,
                                cost=cost,
                                price=price,
                                income=income if explicit_income else "",
                            )
                            errors = (sellgains.SellGainsError,) if cost == "300.00" else ()
                            transactions = self.check_exchange(text, errors)
                            acquisition = transactions[-1].postings[1]
                            if not price:
                                self.assertIsNone(acquisition.price)

    def test_unpriced_reductions(self):
        for units, cash, reduction, income in [
            ("1.00", "-100.00", "-1.00", "-200.00"),
            ("-1.00", "100.00", "1.00", "-400.00"),
        ]:
            with self.subTest(units=units):
                self.check_exchange(f"""
                2000-01-01 * "Establish holding"
                  Assets:Old {units} OLD {{100.00 USD}}
                  Assets:Cash {cash} USD
                2000-01-02 * "Exchange without disposal quote"
                  Assets:Old {reduction} OLD {{}}
                  Assets:New 1.00 NEW {{300.00 USD}} @ 200.00 USD
                  Income:Gains {income} USD
                """)

    def test_unpriced_short_augmentations(self):
        ledger = textwrap.dedent("""
        2000-01-01 * "Buy"
          Assets:Old 1.00 OLD {{100.00 USD}}
          Assets:Cash -100.00 USD
        {holding}
        2000-01-02 * "Sell and open short"
          Assets:Old -1.00 OLD {{}} @ 200.00 USD
          Assets:New -1.00 NEW {{{cost} USD}}
          Assets:Cash 500.00 USD
          Income:Gains {income} USD
        """)
        for cost, income in [("300.00", "-100.00"), ("400.00", "0.00")]:
            for existing in [False, True]:
                with self.subTest(cost=cost, existing=existing):
                    holding = (
                        '2000-01-01 * "Existing short"\n'
                        f"  Assets:New -1.00 NEW {{{cost} USD}}\n"
                        f"  Assets:Cash {cost} USD\n"
                        if existing
                        else ""
                    )
                    errors = (sellgains.SellGainsError,) if cost == "400.00" else ()
                    self.check_exchange(
                        ledger.format(holding=holding, cost=cost, income=income), errors
                    )

    def test_transfers(self):
        for commodity in ["OLD", "NEW"]:
            for price, errors in [
                ("", ()),
                (" @ 200.00 USD", ()),
                (" @ 100.00 USD", (sellgains.SellGainsError,)),
            ]:
                with self.subTest(commodity=commodity, price=price):
                    transactions = self.check_exchange(
                        f"""
                2000-01-01 * "Buy"
                  Assets:Source 1.00 OLD {{100.00 USD}}
                  Assets:Cash -100.00 USD
                2000-01-02 * "Transfer historical cost"
                  Assets:Source -1.00 OLD {{}} @ 200.00 USD
                  Assets:Target 1.00 {commodity} {{100.00 USD, 2000-01-01}}{price}
                """,
                        errors,
                    )
                    self.assertEqual(
                        transactions[-1].postings[1].cost.date, transactions[0].date
                    )

    def test_none_booking_opposing_lots(self):
        for date in ["", ", 2000-01-01"]:
            with self.subTest(date=date):
                self.check_exchange(f"""
                2000-01-01 open Assets:Old OLD "NONE"
                2000-01-01 * "Open short"
                  Assets:Old -1.00 OLD {{100.00 USD}}
                  Assets:Cash 100.00 USD
                2000-01-02 * "Opposing lot"
                  Assets:Old 1.00 OLD {{100.00 USD{date}}}
                  Assets:New 1.00 NEW {{300.00 USD}} @ 200.00 USD
                  Assets:Cash -400.00 USD
                """)

    def test_same_transaction_opposing_postings(self):
        postings = [
            "  Assets:Old 1.00 OLD {100.00 USD}",
            "  Assets:Old -1.00 OLD {100.00 USD}",
        ]
        for order in [postings, postings[::-1]]:
            with self.subTest(order=order):
                self.check_exchange(
                    '2000-01-02 * "Round trip"\n'
                    + "\n".join(order)
                    + "\n  Assets:New 1.00 NEW {300.00 USD} @ 200.00 USD\n"
                    + "  Assets:Cash -300.00 USD\n"
                )

    def test_commodity_exchange_zero_price(self):
        for cost, price, income, errors in [
            ("0.00", "", "100.00", ()),
            ("1.00", "", "99.00", (sellgains.SellGainsError,)),
            ("1.00", " @ 0 USD", "99.00", ()),
        ]:
            with self.subTest(cost=cost, price=price):
                self.check_exchange(
                    f"""
                2000-01-01 * "Buy"
                  Assets:Old 1.00 OLD {{100.00 USD}}
                  Assets:Cash -100.00 USD
                2000-01-02 * "Zero price"
                  Assets:Old -1.00 OLD {{}} @ 0 USD
                  Assets:New 1.00 NEW {{{cost} USD}}{price}
                  Income:Gains {income} USD
                """,
                    errors,
                )

    def test_commodity_exchange_tolerance(self):
        for cost, errors in [
            ("200.010000", ()),
            ("200.010001", (sellgains.SellGainsError,)),
        ]:
            with self.subTest(cost=cost):
                self.check_exchange(
                    f"""
                2000-01-01 * "Buy"
                  Assets:Old 1.00 OLD {{100.00 USD}}
                  Assets:Cash -100.00 USD
                2000-01-02 * "Rounded exchange"
                  Assets:Old -1.00 OLD {{}} @ 200.00 USD
                  Assets:New 1.00 NEW {{{cost} USD}}
                  Income:Gains -100.01 USD
                """,
                    errors,
                )

    def test_commodity_exchange_zero_net_tolerance(self):
        for currency in ["USD", "CAD"]:
            for cash in ["0.01", "0.02"]:
                for price in ["", " @ 200.00 USD"]:
                    with self.subTest(currency=currency, cash=cash, price=price):
                        errors = (
                            ()
                            if currency == "USD" and cash == "0.01" and not price
                            else (sellgains.SellGainsError,)
                        )
                        self.check_exchange(
                            f"""
                        2000-01-01 * "Buy"
                          Assets:Old 1.00 OLD {{100.00 USD}}
                          Assets:Cash -100.00 USD
                        2000-01-02 * "Exchange with rounding"
                          Assets:Old -1.00 OLD {{}} @ 200.00 USD
                          Assets:New 1.00 NEW {{200.00 USD}}{price}
                          Assets:Cash {cash} {currency}
                          Income:Gains -100.00 USD
                          Income:Gains -{cash} {currency}
                        """,
                            errors,
                            'option "infer_tolerance_from_cost" "FALSE"\n',
                        )

    def test_commodity_exchange_cost_tolerance(self):
        for infer_cost, errors in [("FALSE", (sellgains.SellGainsError,)), ("TRUE", ())]:
            with self.subTest(infer_cost=infer_cost):
                self.check_exchange(
                    """
                2000-01-01 * "Buy"
                  Assets:Old 1.00000 OLD {100.00 USD}
                  Assets:Cash -100.00 USD
                2000-01-02 * "Rounded exchange"
                  Assets:Old -1.00000 OLD {} @ 200.00 USD
                  Assets:New 1.00000 NEW {200.001001 USD}
                  Income:Gains
                """,
                    errors,
                    f'option "infer_tolerance_from_cost" "{infer_cost}"\n',
                )

    def test_commodity_exchange_multiple_lots(self):
        for cost, errors in [("400.00", ()), ("500.00", (sellgains.SellGainsError,))]:
            with self.subTest(cost=cost):
                transactions = self.check_exchange(
                    f"""
                2000-01-01 open Assets:Old OLD "FIFO"
                2000-01-01 * "First lot"
                  Assets:Old 1.00 OLD {{100.00 USD}}
                  Assets:Cash -100.00 USD
                2000-01-02 * "Second lot"
                  Assets:Old 1.00 OLD {{150.00 USD}}
                  Assets:Cash -150.00 USD
                2000-01-03 * "Exchange both lots"
                  Assets:Old -2.00 OLD {{}} @ 200.00 USD
                  Assets:New 1.00 NEW {{{cost} USD}}
                  Income:Gains
                """,
                    errors,
                )
                reductions = [
                    p for p in transactions[-1].postings if p.account == "Assets:Old"
                ]
                self.assertEqual(2, len(reductions))

    def test_commodity_exchange_fees_and_currencies(self):
        ledger = textwrap.dedent("""
        2000-01-01 * "Buy"
          Assets:Old 1.00 OLD {{100.00 USD}}
          Assets:Cash -100.00 USD
        2000-01-02 * "Exchange with cash and fees"
          Assets:Old -1.00 OLD {{}} @ 200.00 USD
          Assets:New 1.00 NEW {{180.00 USD}}
          Assets:Cash 20.00 CAD {price}
          Expenses:Fees 10.00 USD
          {income}
        """)
        self.check_exchange(ledger.format(price="@ 0.50 USD", income="Income:Gains"))
        self.check_exchange(
            ledger.format(
                price="", income="Income:Gains -90.00 USD\n  Income:Gains -20.00 CAD"
            ),
            (sellgains.SellGainsError,),
        )
        customised = ledger.format(price="@ 0.50 USD", income="Income:Gains")
        for original, custom in [
            ("Assets", "Actif"),
            ("Expenses", "Frais"),
            ("Income", "Revenu"),
        ]:
            customised = customised.replace(original + ":", custom + ":")
        self.check_exchange(
            customised,
            options='option "name_assets" "Actif"\n'
            'option "name_expenses" "Frais"\noption "name_income" "Revenu"\n',
        )

    def test_no_cost_posting_price(self):
        self.check_exchange("""
        2000-01-01 * "Buy"
          Assets:Old 1.00 OLD {100.00 USD}
          Assets:Cash -100.00 USD
        2000-01-02 * "Only cash has a quote"
          Assets:Old -1.00 OLD {}
          Assets:New 1.00 NEW {300.00 USD}
          Assets:Cash 20.00 CAD @ 0.50 USD
          Income:Gains -210.00 USD
        """)

    def test_incomplete_inventory_history(self):
        entries, errors, options_map = parser.parse_string(
            textwrap.dedent("""
        2000-01-01 open Assets:New NEW "NONE"
        2000-01-01 * "Buy"
          Assets:Old 1.00 OLD {100.00 USD}
          Assets:Cash -100.00 USD
        2000-01-02 * "Incomplete posting"
          Assets:New NEW {0 # 100 USD}
          Assets:Cash -100.00 USD
        2000-01-03 * "Exchange with uncertain history"
          Assets:Old -1.00 OLD {} @ 200.00 USD
          Assets:New 1.00 NEW {300.00 USD}
          Income:Gains -200.00 USD
        """)
        )
        self.assertEqual([], errors)
        entries, errors = booking.book(entries, options_map)
        self.assertEqual(2, len(errors))
        self.assertIn("Cannot infer per-unit cost only from total", errors[0].message)
        self.assertEqual("Transaction has incomplete elements", errors[1].message)
        checked_entries, plugin_errors = sellgains.validate_sell_gains(entries, options_map)
        self.assertIs(entries, checked_entries)
        self.assertEqual([], plugin_errors)

    @loader.load_doc()
    def test_sellgains_success(self, entries, errors, options_map):
        """
        plugin "beancount.plugins.auto_accounts"
        plugin "beancount.plugins.sellgains"

        1999-07-31 * "Sell"
          Assets:US:Company:ESPP          -81 ADSK {26.3125 USD} @ 26.4375 USD
          Assets:US:Company:Cash      2141.36 USD
          Expenses:Financial:Fees        0.08 USD
          Income:US:Company:ESPP:PnL
        """
        printer.print_errors(errors)
        self.assertEqual([], errors)

    @loader.load_doc(expect_errors=True)
    def test_sellgains_fail_balance(self, entries, errors, options_map):
        """
        plugin "beancount.plugins.auto_accounts"
        plugin "beancount.plugins.sellgains"

        1999-07-31 * "Sell"
          Assets:US:Company:ESPP          -81 ADSK {26.3125 USD} @ 26.4375 USD
          Assets:US:Company:Cash      2141.36 USD
          Expenses:Financial:Fees        1.08 USD
          Income:US:Company:ESPP:PnL   -11.13 USD
        """
        self.assertEqual([sellgains.SellGainsError], list(map(type, errors)))

    @loader.load_doc(expect_errors=True)
    def test_sellgains_fail_imbalance(self, entries, errors, options_map):
        """
        plugin "beancount.plugins.auto_accounts"
        plugin "beancount.plugins.sellgains"

        1999-07-31 * "Sell"
          Assets:US:Company:ESPP          -81 ADSK {26.3125 USD} @ 26.4375 USD
          Assets:US:Company:Cash      2141.36 USD
          Income:US:Company:ESPP:PnL   -11.13 USD
        """
        self.assertEqual(
            [sellgains.SellGainsError, validation.ValidationError], list(map(type, errors))
        )

    @loader.load_doc()
    def test_sellgains_other_currency(self, entries, errors, options_map):
        """
        plugin "beancount.plugins.auto_accounts"
        plugin "beancount.plugins.sellgains"

        1999-07-31 * "Sell"
          Assets:US:Company:ESPP          -80 ADSK {26.50 USD} @ 27.50 USD
          Expenses:Commissions           9.95 USD
          Assets:US:Company:Cash      2433.39 CAD @ 0.9000 USD
          Income:US:Company:ESPP:PnL   -80.00 USD
        """
        self.assertEqual([], list(map(type, errors)))

    @loader.load_doc()
    def test_sellgains_zero_price(self, entries, errors, options_map):
        """
        plugin "beancount.plugins.auto_accounts"
        plugin "beancount.plugins.sellgains"

        1999-07-31 * "Sell"
          Assets:US:Broker:Options     -8000 VTI180216C200 {2.50 USD} @ 0 USD
          Income:US:Company:ESPP:PnL    20000 USD
        """
        self.assertEqual([], list(map(type, errors)))


if __name__ == "__main__":
    unittest.main()

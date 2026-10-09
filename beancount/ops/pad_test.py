__copyright__ = "Copyright (C) 2013-2017, 2019, 2021, 2023-2025  Martin Blais"
__license__ = "GNU GPLv2"

import datetime
import decimal
import itertools
import tempfile
import textwrap
import unittest
from os import path

from beancount import loader
from beancount.core import data
from beancount.core import inventory
from beancount.core import realization
from beancount.core.amount import A
from beancount.ops import balance
from beancount.ops import pad
from beancount.parser import cmptest


class TestPadding(cmptest.TestCase):
    @loader.load_doc()
    def test_pad_simple(self, entries, errors, __):
        """

        2013-05-01 open Assets:Checking
        2013-05-01 open Equity:Opening-Balances

        ;; Test the simple case that this directive generates a padding entry.
        2013-05-01 pad Assets:Checking Equity:Opening-Balances

        2013-05-03 balance Assets:Checking                                 172.45 USD

        """
        self.assertFalse(errors)
        self.assertEqualEntries(
            """

          2013-05-01 open Assets:Checking
          2013-05-01 open Equity:Opening-Balances

          2013-05-01 pad Assets:Checking Equity:Opening-Balances

          ;; Check this is inserted.
          2013-05-01 P "(Padding inserted for Balance of 172.45 USD for difference 172.45 USD)"
            Assets:Checking                                                        172.45 USD
            Equity:Opening-Balances                                                -172.45 USD

          2013-05-03 balance Assets:Checking                                 172.45 USD

        """,
            entries,
        )

        self.assertTrue(all(isinstance(p.meta, dict) for p in entries[3].postings))

    @loader.load_doc()
    def test_pad_to_zero(self, entries, errors, __):
        """
        ;; Test the case that this directive generates a padding entry, padding to zero.
        2013-01-01 open Assets:Checking
        2013-01-01 open Equity:Opening-Balances

        2013-02-01 *
          Assets:Checking           234.56 USD
          Equity:Opening-Balances  -234.56 USD

        2013-05-01 pad Assets:Checking Equity:Opening-Balances

        2013-05-03 balance Assets:Checking                                 0.00 USD

        """
        self.assertFalse(errors)
        self.assertEqualEntries(
            """

          2013-01-01 open Assets:Checking
          2013-01-01 open Equity:Opening-Balances

          2013-02-01 *
            Assets:Checking           234.56 USD
            Equity:Opening-Balances  -234.56 USD

          2013-05-01 pad Assets:Checking Equity:Opening-Balances

          ;; Check this is inserted.
          2013-05-01 P "(Padding inserted for Balance of 0.00 USD for difference -234.56 USD)"
            Assets:Checking          -234.56 USD
            Equity:Opening-Balances   234.56 USD

          2013-05-03 balance Assets:Checking                                 0.00 USD

        """,
            entries,
        )

    @loader.load_doc(expect_errors=True)
    def test_pad_no_overflow(self, entries, errors, __):
        """

        2013-05-01 open Assets:Checking
        2013-05-01 open Assets:Cash
        2013-05-01 open Equity:Opening-Balances

        ;; Pad before the next check.
        2013-05-01 pad Assets:Checking Equity:Opening-Balances

        ;; The check that is being padded.
        2013-05-03 balance Assets:Checking                                 172.45 USD

        2013-05-15 * "Add 20$"
          Assets:Checking                                                   20.00 USD
          Assets:Cash                                                      -20.00 USD

        ;; This is the next check, should not have been padded.
        2013-06-01 balance Assets:Checking                                 200.00 USD

        """
        self.assertEqual([balance.BalanceError], list(map(type, errors)))
        self.assertEqualEntries(
            """

          2013-05-01 open Assets:Checking
          2013-05-01 open Assets:Cash
          2013-05-01 open Equity:Opening-Balances

          2013-05-01 pad Assets:Checking Equity:Opening-Balances

          2013-05-01 P "(Padding inserted for Balance of 172.45 USD for difference 172.45 USD)"
            Assets:Checking                                                        172.45 USD
            Equity:Opening-Balances                                                -172.45 USD

          2013-05-03 balance Assets:Checking                                 172.45 USD

          2013-05-15 * "Add 20$"
            Assets:Checking                                                         20.00 USD
            Assets:Cash                                                            -20.00 USD

          2013-06-01 balance Assets:Checking                                 200.00 USD

        """,
            entries,
        )

    @loader.load_doc()
    def test_pad_used_twice_legally(self, entries, errors, __):
        """

        2013-05-01 open Assets:Checking
        2013-05-01 open Assets:Cash
        2013-05-01 open Equity:Opening-Balances

        ;; First pad.
        2013-05-01 pad  Assets:Checking   Equity:Opening-Balances

        2013-05-03 balance Assets:Checking   172.45 USD

        2013-05-15 txn "Add 20$"
          Assets:Checking             20 USD
          Assets:Cash

        ;; Second pad.
        2013-05-20 pad  Assets:Checking   Equity:Opening-Balances

        2013-06-01 balance Assets:Checking   200 USD

        """
        self.assertFalse(errors)
        self.assertEqualEntries(
            """

          2013-05-01 open Assets:Checking
          2013-05-01 open Assets:Cash
          2013-05-01 open Equity:Opening-Balances

          2013-05-01 pad Assets:Checking Equity:Opening-Balances

          2013-05-01 P "(Padding inserted for Balance of 172.45 USD for difference 172.45 USD)"
            Assets:Checking                                                        172.45 USD
            Equity:Opening-Balances                                                -172.45 USD

          2013-05-03 balance Assets:Checking                                 172.45 USD

          2013-05-15 * "Add 20$"
            Assets:Checking                                                         20 USD
            Assets:Cash                                                            -20 USD

          2013-05-20 pad Assets:Checking Equity:Opening-Balances

          2013-05-20 P "(Padding inserted for Balance of 200 USD for difference 7.55 USD)"
            Assets:Checking                                                          7.55 USD
            Equity:Opening-Balances                                                  -7.55 USD

          2013-06-01 balance Assets:Checking                                 200 USD

        """,
            entries,
        )

    @loader.load_doc(expect_errors=True)
    def test_pad_used_twice_illegally(self, entries, errors, __):
        """

        2013-05-01 open Assets:Checking
        2013-05-01 open Equity:Opening-Balances

        2013-05-03 balance Assets:Checking   0.00 USD

        ;; Two pads in between checks.
        2013-05-10 pad  Assets:Checking   Equity:Opening-Balances
        2013-05-20 pad  Assets:Checking   Equity:Opening-Balances

        2013-06-01 balance Assets:Checking   200 USD

        """
        self.assertEqual([pad.PadError], list(map(type, errors)))
        self.assertEqualEntries(
            """

          2013-05-01 open Assets:Checking
          2013-05-01 open Equity:Opening-Balances

          2013-05-03 balance Assets:Checking                                 0.00 USD

          2013-05-10 pad Assets:Checking Equity:Opening-Balances

          2013-05-20 pad Assets:Checking Equity:Opening-Balances

          2013-05-20 P "(Padding inserted for Balance of 200 USD for difference 200 USD)"
            Assets:Checking                                                        200 USD
            Equity:Opening-Balances                                               -200 USD

          2013-06-01 balance Assets:Checking                                 200 USD

        """,
            entries,
        )

    @loader.load_doc(expect_errors=True)
    def test_pad_unused(self, entries, errors, __):
        """

        2013-05-01 open Assets:Checking
        2013-05-01 open Assets:Cash
        2013-05-01 open Equity:Opening-Balances

        2013-05-10 * "Add 200$"
          Assets:Checking       200.00 USD
          Assets:Cash          -200.00 USD

        ;; This pad will do nothing, should raise a warning..
        2013-05-20 pad  Assets:Checking   Equity:Opening-Balances

        2013-06-01 balance Assets:Checking   200.00 USD

        """
        self.assertEqual([pad.PadError], list(map(type, errors)))
        self.assertEqualEntries(
            """

          2013-05-01 open Assets:Checking
          2013-05-01 open Assets:Cash
          2013-05-01 open Equity:Opening-Balances

          2013-05-10 * "Add 200$"
            Assets:Checking                                                        200.00 USD
            Assets:Cash                                                           -200.00 USD

          2013-05-20 pad Assets:Checking Equity:Opening-Balances

          2013-06-01 balance Assets:Checking                                 200.00 USD

        """,
            entries,
        )

    @loader.load_doc()
    def test_pad_parents(self, entries, errors, __):
        """

        2013-05-01 open Assets:US
        2013-05-01 open Assets:US:Bank1:Checking
        2013-05-01 open Assets:US:Bank1:Savings
        2013-05-01 open Assets:US:Bank2:Checking
        2013-05-01 open Assets:US:Bank2:Savings
        2013-05-01 open Equity:Opening-Balances

        2013-05-10 *
          Assets:US:Bank1:Checking                                 1.00 USD
          Assets:US:Bank1:Savings                                  2.00 USD
          Assets:US:Bank2:Checking                                 3.00 USD
          Assets:US:Bank2:Savings                                  4.00 USD
          Equity:Opening-Balances                                 -10.00 USD

        2013-05-20 pad Assets:US Equity:Opening-Balances

        2013-06-01 balance Assets:US                                       100.00 USD

        """
        self.assertFalse(errors)
        self.assertEqualEntries(
            """

          2013-05-01 open Assets:US
          2013-05-01 open Assets:US:Bank1:Checking
          2013-05-01 open Assets:US:Bank1:Savings
          2013-05-01 open Assets:US:Bank2:Checking
          2013-05-01 open Assets:US:Bank2:Savings
          2013-05-01 open Equity:Opening-Balances

          2013-05-10 *
            Assets:US:Bank1:Checking                                                 1.00 USD
            Assets:US:Bank1:Savings                                                  2.00 USD
            Assets:US:Bank2:Checking                                                 3.00 USD
            Assets:US:Bank2:Savings                                                  4.00 USD
            Equity:Opening-Balances                                                 -10.00 USD

          2013-05-20 pad Assets:US Equity:Opening-Balances

          ;; A single pad that does not include child accounts should be inserted.
          2013-05-20 P "(Padding inserted for Balance of 100.00 USD for difference 90.00 USD)"
            Assets:US                                                              90.00 USD
            Equity:Opening-Balances                                                -90.00 USD

          2013-06-01 balance Assets:US                                       100.00 USD

        """,
            entries,
        )

    @loader.load_doc()
    def test_pad_multiple_currencies(self, entries, errors, __):
        """
        2013-05-01 open Assets:Checking
        2013-05-01 open Equity:Opening-Balances

        2013-05-10 *
          Assets:Checking                     1.00 USD
          Assets:Checking                     1.00 CAD
          Assets:Checking                     1.00 EUR
          Equity:Opening-Balances

        ;; This should insert two entries: one for USD, one for CAD (different
        ;; amount) and none for EUR.
        2013-05-20 pad Assets:Checking Equity:Opening-Balances

        2013-06-01 balance Assets:Checking    5.00 USD
        2013-06-01 balance Assets:Checking    3.00 CAD
        2013-06-01 balance Assets:Checking    1.00 EUR

        """
        self.assertFalse(errors)
        self.assertEqualEntries(
            """

          2013-05-01 open Assets:Checking
          2013-05-01 open Equity:Opening-Balances

          2013-05-10 *
            Assets:Checking                    1.00 USD
            Assets:Checking                    1.00 CAD
            Assets:Checking                    1.00 EUR
            Equity:Opening-Balances           -1.00 USD
            Equity:Opening-Balances           -1.00 CAD
            Equity:Opening-Balances           -1.00 EUR

          2013-05-20 pad Assets:Checking Equity:Opening-Balances

          2013-05-20 P "(Padding inserted for Balance of 5.00 USD for difference 4.00 USD)"
            Assets:Checking                    4.00 USD
            Equity:Opening-Balances           -4.00 USD

          2013-05-20 P "(Padding inserted for Balance of 3.00 CAD for difference 2.00 CAD)"
            Assets:Checking                    2.00 CAD
            Equity:Opening-Balances           -2.00 CAD

          2013-06-01 balance Assets:Checking   5.00 USD
          2013-06-01 balance Assets:Checking   3.00 CAD
          2013-06-01 balance Assets:Checking   1.00 EUR

        """,
            entries,
        )

    @loader.load_doc()
    def test_pad_check_balances(self, entries, errors, __):
        """
        2013-05-01 open Assets:Checking
        2013-05-01 open Assets:Cash
        2013-05-01 open Equity:Opening-Balances

        2013-05-01 pad  Assets:Checking   Equity:Opening-Balances

        2013-05-03 txn "Add 20$"
          Assets:Checking                        10 USD
          Assets:Cash

        2013-05-10 balance Assets:Checking      105 USD

        2013-05-15 txn "Add 20$"
          Assets:Checking                        20 USD
          Assets:Cash

        2013-05-16 txn "Add 20$"
          Assets:Checking                        20 USD
          Assets:Cash

        2013-06-01 balance Assets:Checking      145 USD

        """
        post_map = realization.postings_by_account(entries)
        txn_postings = post_map["Assets:Checking"]

        balances = []
        pad_balance = inventory.Inventory()
        for txn_posting in txn_postings:
            if isinstance(txn_posting, data.TxnPosting):
                position_, _ = pad_balance.add_position(txn_posting.posting)
            balances.append((type(txn_posting), pad_balance.get_currency_units("USD")))

        self.assertEqual(
            balances,
            [
                (data.Open, A("0.00 USD")),
                (data.Pad, A("0.00 USD")),
                (data.TxnPosting, A("95.00 USD")),
                (data.TxnPosting, A("105.00 USD")),
                (data.Balance, A("105.00 USD")),
                (data.TxnPosting, A("125.00 USD")),
                (data.TxnPosting, A("145.00 USD")),
                (data.Balance, A("145.00 USD")),
            ],
        )

    # Note: You could try padding A into B and B into A to see if it works.

    @loader.load_doc(expect_errors=True)
    def test_pad_multiple_times(self, entries, errors, __):
        """
        2013-05-01 open Assets:Checking
        2013-05-01 open Equity:Opening-Balances

        2013-06-01 pad Assets:Checking Equity:Opening-Balances
        2013-07-01 pad Assets:Checking Equity:Opening-Balances

        2013-10-01 balance Assets:Checking    5.00 USD
        """
        self.assertEqual([pad.PadError], list(map(type, errors)))

    @loader.load_doc(expect_errors=True)
    def test_pad_at_cost(self, entries, errors, __):
        """
        2013-05-01 open Assets:Investments
        2013-05-01 open Equity:Opening-Balances

        2013-05-15 *
          Assets:Investments   10 MSFT {54.30 USD}
          Equity:Opening-Balances

        2013-06-01 pad Assets:Investments Equity:Opening-Balances

        2013-10-01 balance Assets:Investments   12 MSFT
        """
        self.assertEqual([pad.PadError], list(map(type, errors)))
        self.assertRegex(errors[0].message, "Attempt to pad an entry with cost for")

    @loader.load_doc()
    def test_pad_parent(self, entries, errors, __):
        """
        1998-01-01 open Assets:CA:Bank:Checking     CAD
        1998-01-01 open Assets:CA:Bank:CheckingOld  CAD
        1998-01-01 open Income:CA:Something         USD
        1998-01-01 open Equity:Beginning-Balances

        2006-01-01 pad Assets:CA:Bank:Checking   Equity:Beginning-Balances

        2006-04-04 balance Assets:CA:Bank:Checking      742.50 CAD

        2001-01-15 * "Referral"
          Assets:CA:Bank:CheckingOld   1000.00 CAD @ 0.6625 USD
          Income:CA:Something          -662.50 USD
        """
        self.assertFalse(errors)

    @loader.load_doc(expect_errors=True)
    def test_pad_tolerance(self, entries, errors, __):
        """
        1998-01-01 open Assets:CA:Bank:Checking
        1998-01-01 open Income:CA:Something
        1998-01-01 open Equity:Beginning-Balances

        2006-01-01 pad Assets:CA:Bank:Checking   Equity:Beginning-Balances

        2001-01-15 * "Referral"
          Assets:CA:Bank:Checking   999.95 CAD
          Income:CA:Something

        2006-04-04 balance Assets:CA:Bank:Checking      1000.00 ~ 0.05 CAD

        """
        self.assertEqual(1, len(errors))
        self.assertRegex(errors[0].message, "Unused Pad entry")

    @loader.load_doc(expect_errors=True)
    def test_pad_zero_padding_issue78a(self, entries, errors, __):
        """
        1970-01-01 open Assets:Cash
        1970-01-01 open Expenses:Food

        2015-09-15 pad Assets:Cash Expenses:Food

        2015-09-16 balance Assets:Cash 0 HKD

        ;; The error should be reported here, not on the previous balance check.
        2015-11-02 balance Assets:Cash 1000 HKD
        """
        self.assertEqual(2, len(errors))

        self.assertRegex(errors[0].message, "Unused")
        self.assertEqual(datetime.date(2015, 9, 15), errors[0].entry.date)

        self.assertRegex(errors[1].message, "Balance failed")
        self.assertEqual(datetime.date(2015, 11, 2), errors[1].entry.date)

    @loader.load_doc(expect_errors=True)
    def test_pad_zero_padding_issue78a_original(self, entries, errors, __):
        """
        1970-01-01 open Assets:Cash
        1970-01-01 open Expenses:Food

        ;; Inserted this before the pad, because it was in the original example.
        2015-09-15 balance Assets:Cash 0 HKD

        2015-09-15 pad Assets:Cash Expenses:Food

        2015-09-16 balance Assets:Cash 0 HKD

        ;; The error should be reported here, not on the previous balance check.
        2015-11-02 balance Assets:Cash 1000 HKD
        """
        self.assertEqual(2, len(errors))

        self.assertRegex(errors[0].message, "Unused")
        self.assertEqual(datetime.date(2015, 9, 15), errors[0].entry.date)

        self.assertRegex(errors[1].message, "Balance failed")
        self.assertEqual(datetime.date(2015, 11, 2), errors[1].entry.date)

    @loader.load_doc(expect_errors=True)
    def test_pad_zero_padding_issue78b(self, entries, errors, __):
        """
        1970-01-01 open Assets:Cash
        1970-01-01 open Expenses:Food

        ;; Balance should fail here.
        2015-09-15 balance Assets:Cash 1 HKD

        ;; This will not end up being marked as unused because it will fill in a transaction
        ;; for the missing amount, even though there was a matching balance check earlier. A
        ;; failing balance check does not automatically bring the balance to its value.
        2015-09-15 pad Assets:Cash Expenses:Food

        2015-09-16 balance Assets:Cash 1 HKD
        """
        self.assertTrue(any(isinstance(entry, data.Transaction) for entry in entries))

        self.assertEqual(1, len(errors))

        self.assertRegex(errors[0].message, "Balance failed")
        self.assertEqual(datetime.date(2015, 9, 15), errors[0].entry.date)

    @loader.load_doc()
    def test_pad_issue362(self, entries, errors, __):
        """
        1970-01-01 open Assets:Bank
        1970-01-01 open Assets:Bank-Two
        1970-01-01 open Equity:Opening-Balance
        1970-01-01 open Equity:Adjustments
        1970-01-01 open Expenses:Food

        2019-01-01 * "Opening balance"
          Assets:Bank                  20.00 GBP
          Equity:Opening-Balance      -20.00 GBP

        2019-01-03 * "Tesco" "Buy food"
          Expenses:Food                30.00 GBP
          Assets:Bank                 -30.00 GBP

        2019-01-04 balance Assets:Bank -10.00 GBP

        2019-01-03 * "Tesco" "Buy food"
          Expenses:Food                 6.00 GBP
          Assets:Bank-Two              -6.00 GBP

        ; Get rid of overdraft somehow and get a £50 balance

        2019-01-04 pad Assets:Bank Equity:Adjustments
        2019-01-05 balance Assets:Bank 50.00 GBP
        """
        # self.assertTrue(any(isinstance(entry, data.Transaction)
        #                     for entry in entries))
        # self.assertEqual(1, len(errors))
        # self.assertRegex(errors[0].message, "Balance failed")
        # self.assertEqual(datetime.date(2015, 9, 15), errors[0].entry.date)

    def test_pad_plugin_modify(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_fn = path.join(tmpdir, "my.beancount")
            with open(ledger_fn, "w", encoding="utf-8") as ledger_file:
                ledger_file.write(
                    textwrap.dedent("""
                    option "insert_pythonpath" "True"
                    plugin "plugin_temp"

                    2020-01-01 open Equity:Opening-Balances
                    2020-01-01 open Assets:Checking
                    2020-01-01 open Assets:Cash

                    2023-02-01 * "Add 20$"
                      Assets:Checking            20.0 USD
                      Assets:Cash               -20.0 USD

                    2023-03-01 pad Assets:Checking Equity:Opening-Balances
                    2023-03-02 balance Assets:Checking 100.0 USD
                    """)
                )

            plugin_fn = path.join(tmpdir, "plugin_temp.py")
            with open(plugin_fn, "w", encoding="utf-8") as plugin_file:
                plugin_file.write(
                    textwrap.dedent("""
                    from beancount.core import data

                    __plugins__ = ('plugin_temp',)

                    def plugin_temp(entries, unused_options_map):
                        new_entries = list(
                                e._replace(narration=e.narration + " - Duplicate")
                                for e in data.filter_txns(entries)
                                if e.flag == '*'
                                )
                        return new_entries + entries, []
                    """)
                )
            entries, errors, options_map = loader.load_file(ledger_fn)

        self.assertFalse(errors)
        self.assertEqualEntries(
            """
            option "insert_pythonpath" "True"
            plugin "plugin_temp"

            2020-01-01 open Equity:Opening-Balances
            2020-01-01 open Assets:Checking
            2020-01-01 open Assets:Cash

            2023-02-01 * "Add 20$ - Duplicate"
              Assets:Checking            20.0 USD
              Assets:Cash               -20.0 USD

            2023-02-01 * "Add 20$"
              Assets:Checking            20.0 USD
              Assets:Cash               -20.0 USD

            2023-03-01 pad Assets:Checking Equity:Opening-Balances

            2023-03-01 P "(Padding inserted for Balance of 100.0 USD for difference 60.0 USD)"
              Assets:Checking                                                        60.0 USD
              Equity:Opening-Balances                                                -60.0 USD

            2023-03-02 balance Assets:Checking 100.0 USD
            """,
            entries,
        )


class TestPaddingChains(cmptest.TestCase):
    def test_backdated_own_pad_carries_actual_ledger_balance(self):
        for precision, number in ((6, "9999.99"), (28, "99999999999999999999999999.99")):
            with self.subTest(precision=precision), decimal.localcontext() as context:
                context.prec = precision
                entries, errors, options = loader.load_string(
                    textwrap.dedent(f"""
                    2010-01-01 open Assets:Cash
                    2010-01-01 open Equity:Opening
                    2010-01-01 * "Opening"
                      Assets:Cash {number} AUD
                      Equity:Opening -{number} AUD
                    2010-01-02 pad Assets:Cash Equity:Opening
                    2010-01-03 * "Later posting"
                      Assets:Cash 1 AUD
                      Equity:Opening -1 AUD
                    2010-01-04 balance Assets:Cash 0 ~ 0 AUD
                    2010-01-05 pad Assets:Cash Equity:Opening
                    2010-01-06 balance Assets:Cash 1 ~ 0 AUD
                    """)
                )
                transactions = [e for e in data.filter_txns(entries) if e.flag == "P"]
                self.assertEqual(
                    [e.postings[0].units.number for e in transactions],
                    [-(decimal.Decimal(number) + 1), decimal.Decimal("1.01")],
                )
                self.assertEqual([type(e) for e in errors], [balance.BalanceError])
                self.assertEqual(errors[0].entry.date, datetime.date(2010, 1, 4))
                self.assertIn("accumulated -0.01 AUD", errors[0].message)
                self.assertEqual(len(balance.check(data.sorted(entries), options)[1]), 1)

    def test_parent_check_uses_exact_account_balances(self):
        for precision, number in ((6, "9999.99"), (28, "99999999999999999999999999.99")):
            with self.subTest(precision=precision), decimal.localcontext() as context:
                context.prec = precision
                entries, errors, options = loader.load_string(
                    textwrap.dedent(f"""
                    2010-01-01 open Assets:Cash
                    2010-01-01 open Assets:Cash:Wallet
                    2010-01-01 open Equity:Opening
                    2010-01-02 * "Opening"
                      Assets:Cash {number} AUD
                      Equity:Opening -{number} AUD
                    2010-01-03 * "Wallet"
                      Assets:Cash:Wallet 1 AUD
                      Equity:Opening -1 AUD
                    2010-01-04 * "Withdrawal"
                      Assets:Cash -{number} AUD
                      Equity:Opening {number} AUD
                    2010-01-05 pad Assets:Cash Equity:Opening
                    2010-01-06 balance Assets:Cash 1 ~ 0 AUD
                    """)
                )
                self.assertEqual([e.message for e in errors], ["Unused Pad entry"])
                self.assertFalse([e for e in data.filter_txns(entries) if e.flag == "P"])
                self.assertFalse(balance.check(data.sorted(entries), options)[1])

    def test_common_ancestor_checks_both_generated_postings(self):
        with decimal.localcontext() as context:
            context.prec = 6
            entries, errors, options = loader.load_string(
                textwrap.dedent("""
                2010-01-01 open Assets:Cash
                2010-01-01 open Assets:Cash:A
                2010-01-01 open Assets:Cash:B
                2010-01-01 open Equity:Opening
                2010-01-01 * "Opening"
                  Assets:Cash:A -9999.99 AUD
                  Equity:Opening 9999.99 AUD
                2010-01-02 pad Assets:Cash Equity:Opening
                2010-01-03 pad Assets:Cash:B Assets:Cash:A
                2010-01-04 balance Assets:Cash:B 10000.0 ~ 0 AUD
                2010-01-05 balance Assets:Cash -10000.0 ~ 0 AUD
                """)
            )
            self.assertEqual([e.message for e in errors], ["Unused Pad entry"])
            transactions = [e for e in data.filter_txns(entries) if e.flag == "P"]
            self.assertEqual(
                [e.postings[0].account for e in transactions], ["Assets:Cash:B"]
            )
            self.assertEqual(
                [e.postings[0].units for e in transactions], [A("10000.0 AUD")]
            )
            self.assertFalse(balance.check(data.sorted(entries), options)[1])

    def test_sign_changing_original_postings_keep_decimal_order(self):
        for precision, number in ((6, "9999.99"), (28, "99999999999999999999999999.99")):
            with decimal.localcontext() as exact:
                exact.prec = precision + 2
                doubled = format(decimal.Decimal(number) * 2, "f")
            with self.subTest(precision=precision), decimal.localcontext() as context:
                context.prec = precision
                entries, errors, _ = loader.load_string(
                    textwrap.dedent(f"""
                    2010-01-01 open Assets:Cash
                    2010-01-01 open Equity:Opening
                    2010-01-02 * "Opening"
                      Assets:Cash -{number} AUD
                      Equity:Opening {number} AUD
                    2010-01-03 pad Assets:Cash Equity:Opening
                    2010-01-04 balance Assets:Cash -{number} ~ 0 AUD
                    2010-01-05 * "Sign change"
                      Assets:Cash {doubled} AUD
                      Equity:Opening -{doubled} AUD
                    2010-01-06 pad Assets:Cash Equity:Opening
                    2010-01-07 balance Assets:Cash {number} ~ 0 AUD
                    """)
                )
                self.assertFalse([e for e in data.filter_txns(entries) if e.flag == "P"])
                self.assertEqual([e.message for e in errors], ["Unused Pad entry"] * 2)

    def test_generated_source_precedes_later_original_posting(self):
        for precision, number in ((6, "9999.99"), (28, "99999999999999999999999999.99")):
            with self.subTest(precision=precision), decimal.localcontext() as context:
                context.prec = precision
                entries, errors, options = loader.load_string(
                    textwrap.dedent(f"""
                    2010-01-01 open Assets:A
                    2010-01-01 open Assets:Cash
                    2010-01-01 open Equity:Opening
                    2010-01-01 * "Opening"
                      Assets:Cash {number} AUD
                      Equity:Opening -{number} AUD
                    2010-01-02 pad Assets:A Assets:Cash
                    2010-01-03 * "Later posting"
                      Assets:Cash 1 AUD
                      Equity:Opening -1 AUD
                    2010-01-04 pad Assets:Cash Equity:Opening
                    2010-01-05 balance Assets:A {number} ~ 0 AUD
                    2010-01-06 balance Assets:Cash 1 ~ 0 AUD
                    """)
                )
                self.assertEqual([e.message for e in errors], ["Unused Pad entry"])
                transactions = [e for e in data.filter_txns(entries) if e.flag == "P"]
                self.assertEqual(
                    [e.postings[0].units for e in transactions], [A(f"{number} AUD")]
                )
                self.assertFalse(balance.check(data.sorted(entries), options)[1])

    def test_passing_cost_lots_do_not_retain_historical_inventories(self):
        count = 200
        lines = ["2010-01-01 open Assets:Stocks", "2010-01-01 open Equity:Opening"]
        for index in range(count):
            date = datetime.date(2010, 1, 2) + datetime.timedelta(days=3 * index)
            lines.extend(
                [
                    f'{date} * "Lot"',
                    f"  Assets:Stocks 1 MSFT {{{index + 1} USD}}",
                    f"  Equity:Opening -{index + 1} USD",
                    f"{date + datetime.timedelta(days=1)} pad Assets:Stocks Equity:Opening",
                    f"{date + datetime.timedelta(days=2)} balance Assets:Stocks {index + 1} ~ 0 MSFT",
                ]
            )
        entries, errors, options = loader.load_string("\n".join(lines) + "\n")
        self.assertFalse([e for e in data.filter_txns(entries) if e.flag == "P"])
        self.assertEqual([e.message for e in errors], ["Unused Pad entry"] * count)
        self.assertFalse(balance.check(data.sorted(entries), options)[1])
        slots = pad._padding_slots(entries)
        self.assertEqual(len(slots), count)
        self.assertTrue(all(slot._fields == ("pad", "check") for slot in slots))

    @loader.load_doc(expect_errors=True)
    def test_impossible_parent_transfer_does_not_block_child(self, entries, errors, _):
        """
        2010-01-01 open Assets:Cash
        2010-01-01 open Assets:Cash:Wallet
        2010-01-01 open Equity:Opening
        2010-01-02 pad Assets:Cash Assets:Cash:Wallet
        2010-01-02 pad Assets:Cash:Wallet Equity:Opening
        2010-01-03 balance Assets:Cash 10 AUD
        2010-01-04 balance Assets:Cash:Wallet 5 AUD
        2010-01-05 pad Assets:Cash Equity:Opening
        2010-01-06 balance Assets:Cash 12 AUD
        """
        self.assertEqual(
            [type(e) for e in errors], [pad.PadError, pad.PadError, balance.BalanceError]
        )
        self.assertRegex(errors[0].message, "source.*subtree")
        self.assertRegex(errors[1].message, "Unused")
        self.assertEqual(errors[2].entry.account, "Assets:Cash")
        self.assertIn("accumulated 5 AUD", errors[2].message)
        transactions = list(data.filter_txns(entries))
        self.assertEqual(
            [e.postings[0].account for e in transactions],
            ["Assets:Cash:Wallet", "Assets:Cash"],
        )
        self.assertEqual(
            [e.postings[0].units for e in transactions], [A("5 AUD"), A("7 AUD")]
        )

    def test_many_currencies_keep_only_checked_positions(self):
        currencies = [f"CUR{index:04}" for index in range(200)]
        lines = [
            "2010-01-01 open Assets:Cash",
            "2010-01-01 open Equity:Opening",
            '2010-01-02 * "Opening"',
        ]
        for currency in currencies:
            lines.extend([f"  Assets:Cash 1 {currency}", f"  Equity:Opening -1 {currency}"])
        lines.append("2010-01-03 pad Assets:Cash Equity:Opening")
        lines.extend(f"2010-01-04 balance Assets:Cash 2 ~ 0 {c}" for c in currencies)
        entries, errors, options = loader.load_string("\n".join(lines) + "\n")
        self.assertFalse(errors)
        transactions = [e for e in data.filter_txns(entries) if e.flag == "P"]
        self.assertEqual(
            [e.postings[0].units for e in transactions], [A(f"1 {c}") for c in currencies]
        )
        original = [e for e in entries if e not in transactions]
        slots = pad._padding_slots(original)
        self.assertEqual(len(slots), len(currencies))
        self.assertTrue(all(slot._fields == ("pad", "check") for slot in slots))
        self.assertFalse(balance.check(data.sorted(entries), options)[1])

    @loader.load_doc(expect_errors=True)
    def test_cost_diagnostic_retains_legacy_transfer_and_source_effect(
        self, entries, errors, _
    ):
        """
        2010-01-01 open Assets:Stocks
        2010-01-01 open Assets:Pool
        2010-01-01 open Equity:Opening
        2010-01-02 * "Opening"
          Assets:Stocks 10 MSFT {54.30 USD}
          Equity:Opening -543 USD
        2010-01-03 pad Assets:Stocks Assets:Pool
        2010-01-04 balance Assets:Stocks 12 MSFT
        2010-01-05 pad Assets:Pool Equity:Opening
        2010-01-06 balance Assets:Pool 0 MSFT
        """
        self.assertEqual([type(e) for e in errors], [pad.PadError])
        self.assertRegex(errors[0].message, "Attempt to pad an entry with cost")
        transactions = [e for e in data.filter_txns(entries) if e.flag == "P"]
        self.assertEqual(
            [e.postings[0].units for e in transactions], [A("2 MSFT"), A("2 MSFT")]
        )

    @loader.load_doc(expect_errors=True)
    def test_already_balanced_reciprocal_cycle_is_rejected(self, entries, errors, _):
        """
        2010-01-01 open Assets:A
        2010-01-01 open Assets:B
        2010-01-02 pad Assets:A Assets:B
        2010-01-02 pad Assets:B Assets:A
        2010-01-03 balance Assets:A 0 AUD
        2010-01-03 balance Assets:B 0 AUD
        """
        self.assertFalse(list(data.filter_txns(entries)))
        self.assertEqual([type(e) for e in errors], [pad.PadError] * 4)
        self.assertEqual(sum("dependencies" in e.message for e in errors), 2)
        self.assertEqual(sum("Unused" in e.message for e in errors), 2)

    def test_inventory_carry_does_not_round_unchanged_balance(self):
        for precision, number in ((6, "9999.99"), (28, "99999999999999999999999999.99")):
            with self.subTest(precision=precision), decimal.localcontext() as context:
                context.prec = precision
                entries, errors, _ = loader.load_string(
                    textwrap.dedent(f"""
                    2010-01-01 open Assets:Cash
                    2010-01-01 open Equity:Opening
                    2010-01-02 * "Opening"
                      Assets:Cash {number} AUD
                      Equity:Opening -{number} AUD
                    2010-01-03 pad Assets:Cash Equity:Opening
                    2010-01-04 balance Assets:Cash {number} ~ 0 AUD
                    2010-01-05 pad Assets:Cash Equity:Opening
                    2010-01-06 balance Assets:Cash {number} ~ 0 AUD
                """)
                )
                self.assertEqual([type(e) for e in errors], [pad.PadError, pad.PadError])
                self.assertTrue(all(e.message == "Unused Pad entry" for e in errors))
                self.assertFalse([e for e in data.filter_txns(entries) if e.flag == "P"])

    @loader.load_doc(expect_errors=True)
    def test_later_pad_carries_actual_balance_within_tolerance(self, entries, errors, _):
        """
        2010-01-01 open Assets:Cash
        2010-01-01 open Equity:Opening
        2010-01-02 * "Opening"
          Assets:Cash 11 AUD
          Equity:Opening -11 AUD
        2010-01-03 pad Assets:Cash Equity:Opening
        2010-01-04 balance Assets:Cash 10 ~ 2 AUD
        2010-01-05 pad Assets:Cash Equity:Opening
        2010-01-06 balance Assets:Cash 12 ~ 0 AUD
        """
        self.assertEqual([type(e) for e in errors], [pad.PadError])
        self.assertRegex(errors[0].message, "Unused")
        transactions = [e for e in data.filter_txns(entries) if e.flag == "P"]
        self.assertEqual([e.postings[0].units for e in transactions], [A("1 AUD")])

    def test_chained_settlement_account_names(self):
        for payable, cash, savings in itertools.permutations(
            ("Assets:A", "Assets:B", "Assets:C")
        ):
            with self.subTest(payable=payable, cash=cash, savings=savings):
                entries, errors, _ = loader.load_string(
                    textwrap.dedent(f"""
                    2010-01-01 open {payable}
                    2010-01-01 open {cash}
                    2010-01-01 open {savings}
                    2010-01-01 open Equity:Opening
                    2010-01-02 * "Opening"
                      {payable} -750 AUD
                      {cash} 10000 AUD
                      Equity:Opening -9250 AUD
                    2010-01-03 pad {payable} {cash}
                    2010-01-04 balance {payable} 0 AUD
                    2010-01-05 pad {cash} {savings}
                    2010-01-06 balance {cash} 0 AUD
                    2010-01-06 balance {savings} 9250 AUD
                """)
                )
                self.assertFalse(errors)
                transactions = [e for e in data.filter_txns(entries) if e.flag == "P"]
                self.assertEqual(
                    [(p.account, p.units) for e in transactions for p in e.postings],
                    [
                        (payable, A("750 AUD")),
                        (cash, A("-750 AUD")),
                        (cash, A("-9250 AUD")),
                        (savings, A("9250 AUD")),
                    ],
                )
                checks = [e for e in entries if isinstance(e, data.Balance)]
                pads = [e for e in entries if isinstance(e, data.Pad)]
                for transaction, directive, check in zip(transactions, pads, checks):
                    self.assertEqual(transaction.date, directive.date)
                    self.assertEqual(transaction.meta, directive.meta)
                    self.assertIsNot(transaction.meta, directive.meta)
                    self.assertEqual(
                        entries.index(transaction), entries.index(directive) + 1
                    )
                    self.assertTrue(all(p.meta == check.meta for p in transaction.postings))

    @loader.load_doc()
    def test_reverse_resolution(self, entries, errors, _):
        """
        2010-01-01 open Assets:A
        2010-01-01 open Assets:B
        2010-01-01 open Equity:Opening
        2010-01-02 pad Assets:A Equity:Opening
        2010-01-02 pad Assets:B Assets:A
        2010-01-03 balance Assets:A 10 AUD
        2010-01-05 balance Assets:B 5 AUD
        """
        self.assertFalse(errors)
        transactions = list(data.filter_txns(entries))
        self.assertEqual(
            [e.postings[0].units for e in transactions], [A("15 AUD"), A("5 AUD")]
        )

    @loader.load_doc()
    def test_return_to_previously_padded_account(self, entries, errors, _):
        """
        2010-01-01 open Assets:A
        2010-01-01 open Assets:B
        2010-01-01 open Equity:Opening
        2010-01-02 pad Assets:A Equity:Opening
        2010-01-03 balance Assets:A 10 AUD
        2010-01-04 pad Assets:B Assets:A
        2010-01-05 balance Assets:B 5 AUD
        2010-01-06 pad Assets:A Assets:B
        2010-01-07 balance Assets:A 7 AUD
        2010-01-08 balance Assets:B 3 AUD
        """
        self.assertFalse(errors)
        self.assertEqual(
            [e.postings[0].units for e in data.filter_txns(entries)],
            [A("10 AUD"), A("5 AUD"), A("2 AUD")],
        )

    @loader.load_doc()
    def test_three_link_chain(self, entries, errors, _):
        """
        2010-01-01 open Assets:A
        2010-01-01 open Assets:B
        2010-01-01 open Assets:C
        2010-01-01 open Assets:D
        2010-01-01 open Equity:Opening
        2010-01-02 * "Opening"
          Assets:A -750 AUD
          Assets:B 10000 AUD
          Equity:Opening -9250 AUD
        2010-01-03 pad Assets:A Assets:B
        2010-01-04 balance Assets:A 0 AUD
        2010-01-05 pad Assets:B Assets:C
        2010-01-06 balance Assets:B 0 AUD
        2010-01-07 pad Assets:C Assets:D
        2010-01-08 balance Assets:C 0 AUD
        2010-01-08 balance Assets:D 9250 AUD
        """
        self.assertFalse(errors)
        self.assertEqual(
            [e.postings[0].units for e in data.filter_txns(entries) if e.flag == "P"],
            [A("750 AUD"), A("-9250 AUD"), A("-9250 AUD")],
        )

    @loader.load_doc()
    def test_parent_receives_generated_child_posting(self, entries, errors, _):
        """
        2010-01-01 open Assets:Cash
        2010-01-01 open Assets:Cash:Wallet
        2010-01-01 open Equity:Opening
        2010-01-02 pad Assets:Cash:Wallet Equity:Opening
        2010-01-03 balance Assets:Cash:Wallet 5 AUD
        2010-01-04 pad Assets:Cash Equity:Opening
        2010-01-05 balance Assets:Cash 10 AUD
        """
        self.assertFalse(errors)
        self.assertEqual(
            [e.postings[0].units for e in data.filter_txns(entries)],
            [A("5 AUD"), A("5 AUD")],
        )

    @loader.load_doc(expect_errors=True)
    def test_parent_pad_consumed_by_own_balance(self, entries, errors, _):
        """
        2010-01-01 open Assets:Cash
        2010-01-01 open Assets:Cash:Wallet
        2010-01-01 open Equity:Opening
        2010-01-02 pad Assets:Cash Equity:Opening
        2010-01-03 balance Assets:Cash:Wallet 5 AUD
        2010-01-04 balance Assets:Cash 10 AUD
        """
        self.assertEqual([type(e) for e in errors], [balance.BalanceError])
        self.assertEqual(errors[0].entry.account, "Assets:Cash:Wallet")
        self.assertEqual(list(data.filter_txns(entries))[0].postings[0].units, A("10 AUD"))

    @loader.load_doc()
    def test_same_day_balance_precedes_generated_transfer(self, entries, errors, _):
        """
        2010-01-01 open Assets:A
        2010-01-01 open Assets:B
        2010-01-01 open Equity:Opening
        2010-01-02 pad Assets:A Equity:Opening
        2010-01-03 balance Assets:A 10 AUD
        2010-01-03 pad Assets:B Assets:A
        2010-01-04 balance Assets:B 5 AUD
        2010-01-04 balance Assets:A 5 AUD
        """
        self.assertFalse(errors)
        self.assertEqual(
            [e.postings[0].units for e in data.filter_txns(entries)],
            [A("10 AUD"), A("5 AUD")],
        )

    @loader.load_doc()
    def test_first_passing_check_includes_later_resolved_transfer(self, entries, errors, _):
        """
        2010-01-01 open Assets:A
        2010-01-01 open Assets:B
        2010-01-01 open Equity:Opening
        2010-01-02 pad Assets:A Equity:Opening
        2010-01-02 pad Assets:B Assets:A
        2010-01-03 balance Assets:A 0 AUD
        2010-01-04 balance Assets:A 0 AUD
        2010-01-05 balance Assets:B 5 AUD
        """
        self.assertFalse(errors)
        self.assertEqual(
            [e.postings[0].units for e in data.filter_txns(entries)],
            [A("5 AUD"), A("5 AUD")],
        )

    @loader.load_doc()
    def test_currency_output_order_is_balance_order(self, entries, errors, _):
        """
        2010-01-01 open Assets:A
        2010-01-01 open Assets:B
        2010-01-01 open Equity:Opening
        2010-01-02 pad Assets:A Equity:Opening
        2010-01-02 pad Assets:B Assets:A
        2010-01-03 balance Assets:A 10 USD
        2010-01-04 balance Assets:A 20 CAD
        2010-01-05 balance Assets:B 5 USD
        """
        self.assertFalse(errors)
        self.assertEqual(
            [e.postings[0].units for e in data.filter_txns(entries)],
            [A("15 USD"), A("20 CAD"), A("5 USD")],
        )

    @loader.load_doc(expect_errors=True)
    def test_parent_source_inside_subtree_cannot_change_total(self, entries, errors, _):
        """
        2010-01-01 open Assets:Cash
        2010-01-01 open Assets:Cash:Wallet
        2010-01-02 pad Assets:Cash Assets:Cash:Wallet
        2010-01-03 balance Assets:Cash 5 AUD
        """
        self.assertFalse(list(data.filter_txns(entries)))
        self.assertEqual(
            [type(e) for e in errors], [pad.PadError, pad.PadError, balance.BalanceError]
        )
        self.assertRegex(errors[0].message, "source.*subtree")
        self.assertRegex(errors[1].message, "Unused")

    @loader.load_doc(expect_errors=True)
    def test_parent_source_inside_subtree_no_adjustment(self, entries, errors, _):
        """
        2010-01-01 open Assets:Cash
        2010-01-01 open Assets:Cash:Wallet
        2010-01-02 pad Assets:Cash Assets:Cash:Wallet
        2010-01-03 balance Assets:Cash 0 AUD
        """
        self.assertFalse(list(data.filter_txns(entries)))
        self.assertEqual([type(e) for e in errors], [pad.PadError])
        self.assertRegex(errors[0].message, "Unused")

    def test_reciprocal_cycle(self):
        for a, b in (("5", "-5"), ("5", "5")):
            with self.subTest(a=a, b=b):
                entries, errors, _ = loader.load_string(
                    textwrap.dedent(f"""
                    2010-01-01 open Assets:A
                    2010-01-01 open Assets:B
                    2010-01-02 pad Assets:A Assets:B
                    2010-01-02 pad Assets:B Assets:A
                    2010-01-03 balance Assets:A {a} AUD
                    2010-01-03 balance Assets:B {b} AUD
                """)
                )
                self.assertFalse(list(data.filter_txns(entries)))
                self.assertEqual(
                    sum(
                        isinstance(e, pad.PadError) and "dependencies" in e.message
                        for e in errors
                    ),
                    2,
                )
                self.assertEqual(
                    sum(isinstance(e, balance.BalanceError) for e in errors), 2
                )

    @loader.load_doc(expect_errors=True)
    def test_cycle_blocks_dependants_but_not_independent_pad(self, entries, errors, _):
        """
        2010-01-01 open Assets:A
        2010-01-01 open Assets:Cash:Wallet
        2010-01-01 open Assets:Cash
        2010-01-01 open Assets:D
        2010-01-01 open Equity:Opening
        2010-01-02 pad Assets:A Assets:Cash:Wallet
        2010-01-02 pad Assets:Cash:Wallet Assets:A
        2010-01-02 pad Assets:D Equity:Opening
        2010-01-03 balance Assets:A 5 AUD
        2010-01-03 balance Assets:Cash:Wallet -5 AUD
        2010-01-03 balance Assets:D 7 AUD
        2010-01-04 pad Assets:Cash Equity:Opening
        2010-01-05 balance Assets:Cash 2 AUD
        """
        transactions = list(data.filter_txns(entries))
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].postings[0].account, "Assets:D")
        self.assertEqual(transactions[0].postings[0].units, A("7 AUD"))
        self.assertEqual(
            sum(
                isinstance(e, pad.PadError) and "dependencies" in e.message for e in errors
            ),
            3,
        )


if __name__ == "__main__":
    unittest.main()

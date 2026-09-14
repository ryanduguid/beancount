from __future__ import annotations

import datetime

import pytest

duckdb = pytest.importorskip("duckdb")

from beancount.core.amount import Amount  # noqa: E402
from beancount.core.inventory import Inventory  # noqa: E402
from beancount.core.number import D  # noqa: E402
from beancount.core.position import Cost  # noqa: E402
from beancount.core.position import Position  # noqa: E402
from experiments.duckdb.duckdb_core import inventory_from_dict  # noqa: E402
from experiments.duckdb.duckdb_core import position_from_dict  # noqa: E402
from experiments.duckdb.duckdb_core import register_duckdb  # noqa: E402


@pytest.mark.parametrize(
    "number",
    [
        "10000000000000000.01",
        "-10000000000000000.01",
        "0.000000000000000001",
        "12345678901234567890.123456789012345678",
    ],
)
def test_duckdb_renderer_preserves_decimal_units(number):
    with register_duckdb(duckdb.connect()) as connection:
        stored, amount, position, inventory = connection.execute(
            """
            with value as (
                select bnpos(cast(? as decimal(38,18)), 'AUD', null, null, null, null) as pos
            )
            select pos.units.number, bnstr(pos.units), bnstr(pos), bnstr(bninv([pos]))
            from value
            """,
            [number],
        ).fetchone()

    assert stored == D(number)
    assert D(amount.split()[0]) == stored
    assert D(position.split()[0]) == stored
    assert D(inventory.removeprefix("(").split()[0]) == stored


def test_duckdb_renderer_preserves_decimal_cost():
    with register_duckdb(duckdb.connect()) as connection:
        stored, rendered = connection.execute(
            """
            select
                bnpos(1, 'SHARE', 10000000000000000.01, 'AUD', date '2024-01-01', 'lot'),
                bnstr(bnpos(1, 'SHARE', 10000000000000000.01, 'AUD', date '2024-01-01', 'lot'))
            """
        ).fetchone()

    assert stored["cost"]["number"] == D("10000000000000000.01")
    assert rendered == '1 SHARE {10000000000000000.01 AUD, 2024-01-01, "lot"}'


def test_duckdb_position_round_trip():
    connection = register_duckdb(duckdb.connect())

    position_value, rendered = connection.execute(
        """
        select
            bnpos(4.5, 'HOOL', 510.23, 'USD', date '2024-02-03', 'lot-1'),
            bnstr(
                bnpos(4.5, 'HOOL', 510.23, 'USD', date '2024-02-03', 'lot-1')
            )
        """
    ).fetchone()

    assert position_from_dict(position_value) == Position(
        Amount(D("4.5"), "HOOL"),
        Cost(D("510.23"), "USD", datetime.date(2024, 2, 3), "lot-1"),
    )
    assert rendered == '4.5 HOOL {510.23 USD, 2024-02-03, "lot-1"}'


def test_duckdb_inventory_aggregate_merges_positions():
    connection = register_duckdb(duckdb.connect())

    inventory_value, rendered = connection.execute(
        """
        with positions(pos) as (
            values
                (bnpos(2, 'HOOL', 100, 'USD', date '2024-01-01', 'lot-a')),
                (bnpos(3, 'HOOL', 100, 'USD', date '2024-01-01', 'lot-a')),
                (bnpos(-1, 'HOOL', 100, 'USD', date '2024-01-01', 'lot-a')),
                (bnpos(5, 'USD', null, null, null, null))
        )
        select
            bnsum(pos),
            bnstr(bnsum(pos))
        from positions
        """
    ).fetchone()

    expected = Inventory(
        [
            Position(
                Amount(D("4"), "HOOL"),
                Cost(D("100"), "USD", datetime.date(2024, 1, 1), "lot-a"),
            ),
            Position(Amount(D("5"), "USD"), None),
        ]
    )

    assert inventory_from_dict(inventory_value) == expected
    assert rendered == '(5 USD, 4 HOOL {100 USD, 2024-01-01, "lot-a"})'


def test_duckdb_inventory_aggregate_groups():
    connection = register_duckdb(duckdb.connect())

    rows = connection.execute(
        """
        with positions(bucket, pos) as (
            values
                ('assets', bnpos(2, 'USD', null, null, null, null)),
                ('assets', bnpos(3, 'USD', null, null, null, null)),
                ('lots', bnpos(1, 'BTC', 60000, 'USD', date '2024-03-01', 'buy'))
        )
        select
            bucket,
            bnstr(bnsum(pos))
        from positions
        group by bucket
        order by bucket
        """
    ).fetchall()

    assert rows == [
        ("assets", "(5 USD)"),
        ("lots", '(1 BTC {60000 USD, 2024-03-01, "buy"})'),
    ]

"""Automatic padding of gaps between entries."""

__copyright__ = "Copyright (C) 2013-2017, 2020, 2024-2025  Martin Blais"
__license__ = "GNU GPLv2"

import bisect
import graphlib
from collections import defaultdict
from typing import NamedTuple

from beancount.core import account
from beancount.core import amount
from beancount.core import data
from beancount.core import flags
from beancount.core import inventory
from beancount.core import position
from beancount.core import realization
from beancount.ops import balance

__plugins__ = ("pad",)


class PadError(NamedTuple):
    """Represents an error encountered during padding."""

    source: data.Meta
    message: str
    entry: data.Pad


class _PaddingSlot(NamedTuple):
    pad: data.Pad
    check: data.Balance


def _padding_slots(entries):
    """Find each Pad account's first check per currency, including passing checks."""
    active = {}
    consumed = {}
    slots = []
    for entry in data.sorted(entries):
        if isinstance(entry, data.Pad):
            active[entry.account] = entry
            consumed[entry.account] = set()
        elif isinstance(entry, data.Balance) and entry.account in active:
            currencies = consumed[entry.account]
            if entry.amount.currency not in currencies:
                slots.append(_PaddingSlot(active[entry.account], entry))
                currencies.add(entry.amount.currency)
    return slots


def _padding_dependencies(slots):
    """Index transfers by the checked subtree, currency and effective date."""
    checks = {}
    for index, slot in enumerate(slots):
        key = (slot.check.account, slot.check.amount.currency)
        dates, indices = checks.setdefault(key, ([], []))
        dates.append(slot.check.date)
        indices.append(index)

    dependencies = {index: set() for index in range(len(slots))}
    previous = {}
    for _, indices in checks.values():
        for earlier, later in zip(indices, indices[1:]):
            previous[later] = earlier
            dependencies[later].add(earlier)
    for index, slot in enumerate(slots):
        # A transfer within the checked subtree cannot change its total and
        # will never be inserted. Keep incoming dependencies but omit its
        # hypothetical posting effects on other checks.
        if account.parent_matcher(slot.check.account)(slot.pad.source_account):
            continue
        # Both legs can change a common ancestor's Decimal result even when
        # their mathematical sum is zero. Replay postings, not coefficients.
        affected = set(account.parents(slot.pad.account))
        affected.update(account.parents(slot.pad.source_account))
        for parent in affected:
            key = (parent, slot.check.amount.currency)
            if key not in checks:
                continue
            dates, indices = checks[key]
            # Balance directives precede transactions on the same date.
            first = bisect.bisect_right(dates, slot.pad.date)
            if first < len(indices):
                dependent = indices[first]
                if dependent != index:
                    dependencies[dependent].add(index)
    return dependencies, previous


def _insert_padding(entries, slots, resolved):
    """Insert resolved transactions in Balance order immediately after their Pad."""
    generated = defaultdict(list)
    for index, slot in enumerate(slots):
        transaction = resolved.get(index)
        if transaction is not None:
            generated[id(slot.pad)].append(transaction)
    output = []
    for entry in entries:
        output.append(entry)
        if isinstance(entry, data.Pad):
            output.extend(generated[id(entry)])
    return output


def _original_postings(entries, slots):
    """Index ordered posting references by checked subtree and units currency."""
    checks = {(slot.check.account, slot.check.amount.currency) for slot in slots}
    streams = {}
    ordered = sorted(enumerate(entries), key=lambda pair: data.entry_sortkey(pair[1]))
    for entry_index, entry in ordered:
        if not isinstance(entry, data.Transaction):
            continue
        for posting_index, posting in enumerate(entry.postings):
            key = (*data.entry_sortkey(entry), entry_index, 0, posting_index)
            for parent in account.parents(posting.account):
                if (parent, posting.units.currency) in checks:
                    dates, postings = streams.setdefault(
                        (parent, posting.units.currency), ([], [])
                    )
                    dates.append(entry.date)
                    postings.append((key, posting))
    return streams


def _replay_postings(root, slot, events, own_key):
    """Replay exact accounts, retaining the target state at its own Pad date."""
    checked = realization.get_or_create(root, slot.check.account)
    before_pad = None
    for key, posting in events:
        if before_pad is None and key >= own_key:
            before_pad = inventory.Inventory(checked.balance)
        realization.get_or_create(root, posting.account).balance.add_position(posting)
    if before_pad is None:
        before_pad = inventory.Inventory(checked.balance)
    return checked, before_pad


def pad(entries, options_map):
    """Insert transfers after Pads for their own account's first Balance per currency.

    Each Balance checks its account and descendants. Generated transfers take
    effect at their Pad dates, including both target and source postings in
    other padding calculations. Resolve acyclic dependencies before inserting
    entries; unresolved dependencies produce errors instead of arbitrary amounts.

    Args:
      entries: A list of directives.
      options_map: A parser options dict.
    Returns:
      A new list of directives and a list of padding errors.
    """
    pad_errors = []
    slots = _padding_slots(entries)
    if not slots:
        return list(entries), [
            PadError(entry.meta, "Unused Pad entry", entry)
            for entry in entries
            if isinstance(entry, data.Pad)
        ]
    dependencies, previous = _padding_dependencies(slots)
    streams = _original_postings(entries, slots)
    pad_indices = {
        id(entry): index
        for index, entry in enumerate(entries)
        if isinstance(entry, data.Pad)
    }
    retained = set(previous.values())
    sorter = graphlib.TopologicalSorter(dependencies)
    try:
        sorter.prepare()
    except graphlib.CycleError:
        # Unrelated acyclic slots can still be resolved.
        pass

    resolved = {}
    states = {}
    while sorter.is_active():
        ready = sorter.get_ready()
        if not ready:
            break
        # Only committed predecessor transactions are visible to this batch.
        batch = {}
        for index in ready:
            slot = slots[index]
            earlier = previous.get(index)
            if earlier is None:
                root, start = realization.RealAccount(""), 0
            else:
                # This state has exactly one same-key successor. Each foreign
                # transfer was delivered to its first strictly later check.
                root, start = states.pop(earlier)
            dates, postings = streams.get(
                (slot.check.account, slot.check.amount.currency), ([], [])
            )
            end = bisect.bisect_left(dates, slot.check.date)
            events = postings[start:end]
            is_child = account.parent_matcher(slot.check.account)
            for predecessor in dependencies[index]:
                if predecessor == earlier:
                    continue
                transaction = resolved[predecessor]
                if transaction is not None:
                    for posting_index, posting in enumerate(transaction.postings):
                        if is_child(posting.account):
                            key = (
                                *data.entry_sortkey(transaction),
                                pad_indices[id(slots[predecessor].pad)],
                                predecessor + 1,
                                posting_index,
                            )
                            events.append((key, posting))
            events.sort(key=lambda pair: pair[0])
            own_key = (
                *data.entry_sortkey(slot.pad),
                pad_indices[id(slot.pad)],
                index + 1,
                0,
            )
            checked, before_pad = _replay_postings(root, slot, events, own_key)
            pad_balance = realization.compute_balance(checked, leaf_only=False)

            check_amount = slot.check.amount
            balance_amount = pad_balance.get_currency_units(check_amount.currency)
            tolerance = balance.get_balance_tolerance(slot.check, options_map)
            if abs(balance_amount.number - check_amount.number) <= tolerance:
                batch[index] = None
            elif account.parent_matcher(slot.check.account)(slot.pad.source_account):
                pad_errors.append(
                    PadError(
                        slot.check.meta,
                        "Cannot pad from a source account inside the checked subtree",
                        slot.pad,
                    )
                )
                batch[index] = None
            else:
                batch[index] = _create_padding(
                    slot.pad, slot.check, inventory.Inventory(pad_balance), pad_errors
                )
                # Preserve the legacy difference calculation, but carry the
                # actual ledger state after inserting at the earlier Pad date.
                checked.balance = before_pad
                checked.balance.add_position(batch[index].postings[0])
                for key, posting in events:
                    if key >= own_key and posting.account == slot.pad.account:
                        checked.balance.add_position(posting)
            if index in retained:
                states[index] = root, end
        resolved.update(batch)
        sorter.done(*ready)

    used = set()
    for index, slot in enumerate(slots):
        if index in resolved:
            transaction = resolved[index]
            if transaction is not None:
                used.add(id(slot.pad))
        else:
            pad_errors.append(
                PadError(
                    slot.check.meta,
                    "Cannot resolve cyclic padding dependencies",
                    slot.pad,
                )
            )

    for entry in entries:
        if isinstance(entry, data.Pad) and id(entry) not in used:
            pad_errors.append(PadError(entry.meta, "Unused Pad entry", entry))
    return _insert_padding(entries, slots, resolved), pad_errors


def _create_padding(active_pad, entry, pad_balance, pad_errors):
    """Create a transfer with the existing padding metadata and cost checks."""
    check_amount = entry.amount
    balance_amount = pad_balance.get_currency_units(check_amount.currency)
    # Note: we decide that it's an error to try to pad
    # positions at cost; we check here that all the existing
    # positions with that currency have no cost.
    positions = [
        pos
        for pos in pad_balance.get_positions()
        if pos.units.currency == check_amount.currency
    ]
    for position_ in positions:
        if position_.cost is not None:
            pad_errors.append(
                PadError(
                    entry.meta,
                    (
                        "Attempt to pad an entry with cost for balance: {}".format(
                            pad_balance
                        )
                    ),
                    active_pad,
                )
            )

    # Thus our padding lot is without cost by default.
    diff_position = position.Position.from_amounts(
        amount.Amount(
            check_amount.number - balance_amount.number,
            check_amount.currency,
        )
    )

    # Synthesize a new transaction entry for the difference.
    narration = ("(Padding inserted for Balance of {} for difference {})").format(
        check_amount, diff_position
    )
    new_entry = data.Transaction(
        active_pad.meta.copy(),
        active_pad.date,
        flags.FLAG_PADDING,
        None,
        narration,
        data.EMPTY_SET,
        data.EMPTY_SET,
        [],
    )

    new_entry.postings.append(
        data.Posting(
            active_pad.account,
            diff_position.units,
            diff_position.cost,
            None,
            None,
            entry.meta,
        )
    )
    neg_diff_position = -diff_position
    new_entry.postings.append(
        data.Posting(
            active_pad.source_account,
            neg_diff_position.units,
            neg_diff_position.cost,
            None,
            None,
            entry.meta,
        )
    )

    # Fixup the running balance.
    pos, _ = pad_balance.add_position(diff_position)
    if pos is not None and pos.is_negative_at_cost():
        raise ValueError("Position held at cost goes negative: {}".format(pos))
    return new_entry

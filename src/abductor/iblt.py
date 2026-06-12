"""Invertible Bloom Lookup Table — set reconciliation from a small sketch.

The gate's job is to compute a *disagreement*: the symmetric difference between
what the candidate fix believes (the cases it accepts) and what is actually true
(the calibrated baseline). The naive way is to materialize both accept-sets and
XOR them. That is exactly what we cannot afford:

  - in-context (the agent reads both full sets into its window) it is too
    expensive — you pay for |A| + |B|, which dwarfs the handful of cases that
    actually disagree;
  - in-CPU a full enumeration-and-diff is O(|A| + |B|) every probe.

The parts-bin fix (Eppstein, Goodrich, Uyeda & Varghese, *What's the
Difference?*, SIGCOMM 2011) is set reconciliation: encode each set into an IBLT
sketch whose size is proportional to the expected *difference* d, not the set
size. Subtract the two sketches and "peel" the result to recover the difference
in O(d). Only the O(d) sketch crosses the boundary — into context, over a wire,
between two agents — never the full sets.

Keys are non-negative integers. Map domain items to keys with a hash and keep a
local id->item table on each side (both sides already know their own items, so a
recovered key is looked up locally).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

_KEY_SALT = 0xFFFF  # salt that derives a cell-independent fingerprint of a key


def _h(value: int, salt: int) -> int:
    """A salted 64-bit hash of a non-negative integer."""
    data = value.to_bytes(16, "big")
    digest = hashlib.blake2b(data, digest_size=8, salt=salt.to_bytes(2, "big")).digest()
    return int.from_bytes(digest, "big")


@dataclass
class _Cell:
    count: int = 0
    key_sum: int = 0
    hash_sum: int = 0

    def is_empty(self) -> bool:
        return self.count == 0 and self.key_sum == 0 and self.hash_sum == 0


@dataclass
class IBLT:
    """An invertible Bloom lookup table over non-negative integer keys.

    ``cells`` is the sketch size — pick a few times the expected difference d.
    ``k`` is the number of distinct cells each key touches (4 is standard).
    """

    cells: int = 64
    k: int = 4
    table: list[_Cell] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.table:
            self.table = [_Cell() for _ in range(self.cells)]

    def _indices(self, key: int) -> list[int]:
        out: list[int] = []
        salt = 0
        while len(out) < self.k:
            j = _h(key, salt) % self.cells
            if j not in out:
                out.append(j)
            salt += 1
        return out

    def _apply(self, key: int, sign: int) -> None:
        kh = _h(key, _KEY_SALT)
        for j in self._indices(key):
            c = self.table[j]
            c.count += sign
            c.key_sum ^= key
            c.hash_sum ^= kh

    def insert(self, key: int) -> None:
        self._apply(key, +1)

    def delete(self, key: int) -> None:
        self._apply(key, -1)

    def to_dict(self) -> dict:
        """Serialize the sketch — this O(d) blob is what crosses a boundary."""
        return {
            "cells": self.cells,
            "k": self.k,
            "table": [[c.count, c.key_sum, c.hash_sum] for c in self.table],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IBLT":
        table = [_Cell(count, key_sum, hash_sum) for count, key_sum, hash_sum in d["table"]]
        return cls(d["cells"], d["k"], table)

    def subtract(self, other: "IBLT") -> "IBLT":
        """Cell-wise difference. Result decodes to (self_only, other_only)."""
        if self.cells != other.cells or self.k != other.k:
            raise ValueError("IBLTs must share cells and k to be subtracted")
        out = IBLT(self.cells, self.k)
        for a, b, r in zip(self.table, other.table, out.table):
            r.count = a.count - b.count
            r.key_sum = a.key_sum ^ b.key_sum
            r.hash_sum = a.hash_sum ^ b.hash_sum
        return out

    def _is_pure(self, c: _Cell) -> bool:
        return abs(c.count) == 1 and c.hash_sum == _h(c.key_sum, _KEY_SALT)

    def decode(self) -> tuple[set[int], set[int], bool]:
        """Peel the sketch into (self_only, other_only, fully_decoded).

        ``self_only`` are keys present in the left set only (count +1),
        ``other_only`` are keys in the right set only (count -1). ``fully_decoded``
        is False when the sketch was too small to peel completely — grow ``cells``
        and retry. A working copy is peeled so the receiver is not consumed.
        """
        work = IBLT(self.cells, self.k, [_Cell(c.count, c.key_sum, c.hash_sum) for c in self.table])
        self_only: set[int] = set()
        other_only: set[int] = set()

        pure = [j for j, c in enumerate(work.table) if work._is_pure(c)]
        while pure:
            j = pure.pop()
            c = work.table[j]
            if not work._is_pure(c):
                continue  # cell changed since it was queued
            key, sign = c.key_sum, c.count
            (self_only if sign == 1 else other_only).add(key)
            work._apply(key, -sign)  # remove the recovered key from all its cells
            for jj in work._indices(key):
                if work._is_pure(work.table[jj]):
                    pure.append(jj)

        fully_decoded = all(c.is_empty() for c in work.table)
        return self_only, other_only, fully_decoded


def reconcile(
    a: set[int], b: set[int], cells: int | None = None, k: int = 4
) -> tuple[set[int], set[int], bool]:
    """Recover (a_only, b_only) via two sketches, auto-sizing on decode failure.

    In a real deployment only the sketches (O(d)) are exchanged; here we build
    both locally to demonstrate the recovery. We never compute ``a ^ b`` directly.
    """
    size = cells if cells is not None else max(16, 4 * (len(a ^ b) or 1))
    for attempt in range(12):
        ta, tb = IBLT(size, k), IBLT(size, k)
        for x in a:
            ta.insert(x)
        for x in b:
            tb.insert(x)
        a_only, b_only, ok = ta.subtract(tb).decode()
        if ok:
            return a_only, b_only, True
        size *= 4  # too small to peel; grow and retry
    return set(), set(), False


def sketch(items: set[int], cells: int, k: int = 4) -> IBLT:
    """Encode a set into a fixed-size sketch (O(cells)), for boundary crossing."""
    t = IBLT(cells, k)
    for x in items:
        t.insert(x)
    return t


def reconcile_sketches(a: IBLT, b: IBLT) -> tuple[set[int], set[int], bool]:
    """Recover (a_only, b_only) from two sketches alone — the full sets never met."""
    return a.subtract(b).decode()

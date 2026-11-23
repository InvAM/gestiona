"""Fractional indexing for manual ordering (backlog / board rank).

Port of the algorithm by David Greenspan / rocicorp `fractional-indexing`.
Keys are strings that sort lexicographically; a key can always be generated
between any two keys without touching other rows.
"""

from __future__ import annotations

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_INT_ZERO = "a0"
_SMALLEST_INT = "A" + "0" * 26


def _midpoint(a: str, b: str | None) -> str:
    if b is not None and a >= b:
        raise ValueError(f"{a!r} >= {b!r}")
    if a.endswith("0") or (b is not None and b.endswith("0")):
        raise ValueError("trailing zero")
    if b:
        n = 0
        while (a[n] if n < len(a) else "0") == b[n]:
            n += 1
        if n > 0:
            return b[:n] + _midpoint(a[n:], b[n:])
    digit_a = DIGITS.index(a[0]) if a else 0
    digit_b = DIGITS.index(b[0]) if b is not None else len(DIGITS)
    if digit_b - digit_a > 1:
        return DIGITS[round(0.5 * (digit_a + digit_b))]
    if b is not None and len(b) > 1:
        return b[:1]
    return DIGITS[digit_a] + _midpoint(a[1:], None)


def _int_length(head: str) -> int:
    if "a" <= head <= "z":
        return ord(head) - ord("a") + 2
    if "A" <= head <= "Z":
        return ord("Z") - ord(head) + 2
    raise ValueError(f"invalid order key head: {head!r}")


def _integer_part(key: str) -> str:
    length = _int_length(key[0])
    if length > len(key):
        raise ValueError(f"invalid order key: {key!r}")
    return key[:length]


def _validate(key: str) -> None:
    if key == _SMALLEST_INT:
        raise ValueError(f"invalid order key: {key!r}")
    i = _integer_part(key)
    f = key[len(i):]
    if f.endswith("0"):
        raise ValueError(f"invalid order key: {key!r}")


def _increment_int(x: str) -> str | None:
    head, digs = x[0], list(x[1:])
    carry = True
    i = len(digs) - 1
    while carry and i >= 0:
        d = DIGITS.index(digs[i]) + 1
        if d == len(DIGITS):
            digs[i] = "0"
        else:
            digs[i] = DIGITS[d]
            carry = False
        i -= 1
    if carry:
        if head == "Z":
            return "a0"
        if head == "z":
            return None
        h = chr(ord(head) + 1)
        if h > "a":
            digs.append("0")
        else:
            digs.pop()
        return h + "".join(digs)
    return head + "".join(digs)


def _decrement_int(x: str) -> str | None:
    head, digs = x[0], list(x[1:])
    borrow = True
    i = len(digs) - 1
    while borrow and i >= 0:
        d = DIGITS.index(digs[i]) - 1
        if d == -1:
            digs[i] = DIGITS[-1]
        else:
            digs[i] = DIGITS[d]
            borrow = False
        i -= 1
    if borrow:
        if head == "a":
            return "Z" + DIGITS[-1]
        if head == "A":
            return None
        h = chr(ord(head) - 1)
        if h < "Z":
            digs.append(DIGITS[-1])
        else:
            digs.pop()
        return h + "".join(digs)
    return head + "".join(digs)


def key_between(a: str | None, b: str | None) -> str:
    """Return a key strictly between a and b (None = open end)."""
    if a is not None:
        _validate(a)
    if b is not None:
        _validate(b)
    if a is not None and b is not None and a >= b:
        raise ValueError(f"{a!r} >= {b!r}")
    if a is None:
        if b is None:
            return _INT_ZERO
        ib = _integer_part(b)
        fb = b[len(ib):]
        if ib == _SMALLEST_INT:
            return ib + _midpoint("", fb)
        if ib < b:
            return ib
        res = _decrement_int(ib)
        if res is None:
            raise ValueError("cannot decrement any more")
        return res
    if b is None:
        ia = _integer_part(a)
        fa = a[len(ia):]
        i = _increment_int(ia)
        return ia + _midpoint(fa, None) if i is None else i
    ia = _integer_part(a)
    fa = a[len(ia):]
    ib = _integer_part(b)
    fb = b[len(ib):]
    if ia == ib:
        return ia + _midpoint(fa, fb)
    i = _increment_int(ia)
    if i is None:
        raise ValueError("cannot increment any more")
    if i < b:
        return i
    return ia + _midpoint(fa, None)


def keys_after(a: str | None, n: int) -> list[str]:
    keys: list[str] = []
    cur = a
    for _ in range(n):
        cur = key_between(cur, None)
        keys.append(cur)
    return keys

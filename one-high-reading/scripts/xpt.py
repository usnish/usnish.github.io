"""Minimal reader for SAS transport (XPORT v5) files, as published by NHANES.

read(path) -> {variable name: [values]}; numeric values become floats (NaN for
missing), character values become stripped strings. Stdlib + numpy only.
"""
import struct

import numpy as np


def _ibm(b):
    """IBM System/360 floating point (big-endian, base 16) -> float."""
    if b[0] in (0x2E, 0x5F) or (0x41 <= b[0] <= 0x5A and not any(b[1:])):  # SAS missing (., ._, .A-.Z)
        return np.nan
    b = b + b"\x00" * (8 - len(b))
    v = struct.unpack(">Q", b)[0]
    if v == 0:
        return 0.0
    sign = -1 if v >> 63 else 1
    exp = (v >> 56) & 0x7F
    mant = v & 0x00FFFFFFFFFFFFFF
    return sign * mant / float(1 << 56) * 16.0 ** (exp - 64)


def read(path):
    d = open(path, "rb").read()
    i = d.find(b"NAMESTR HEADER RECORD") - 20
    nvar = int(d[i + 54:i + 58])
    p = i + 80
    variables = []
    for _ in range(nvar):
        ns = d[p:p + 140]
        p += 140
        ntype, _, nlen, _ = struct.unpack(">hhhh", ns[:8])
        name = ns[8:16].decode().strip()
        npos = struct.unpack(">i", ns[84:88])[0]
        variables.append((name, ntype, nlen, npos))
    p = d.find(b"OBS     HEADER RECORD", p) - 20 + 80
    rl = sum(v[2] for v in variables)
    out = {v[0]: [] for v in variables}
    while p + rl <= len(d):
        rec = d[p:p + rl]
        p += rl
        if rec.strip(b" ") == b"":  # padding at the end of the last 80-byte record
            break
        for name, t, l, pos in variables:
            out[name].append(_ibm(rec[pos:pos + l]) if t == 1 else rec[pos:pos + l].decode("latin-1").strip())
    return out

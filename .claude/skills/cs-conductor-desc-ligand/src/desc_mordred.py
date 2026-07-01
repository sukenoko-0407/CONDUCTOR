from __future__ import annotations

import math
import re


_CALCULATORS: dict[str, object] = {}


def _safe_name(name: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_]+", "_", str(name)).strip("_")
    return safe or "unnamed"


def _to_float_or_none(value):
    if value is None:
        return None
    if isinstance(value, complex):
        if abs(value.imag) > 1.0e-12:
            return None
        value = value.real
    try:
        number = float(value)
    except Exception:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _calculator(mode: str):
    try:
        from mordred import Calculator, descriptors
    except ImportError as exc:
        raise RuntimeError("mordredcommunity is required for Mordred descriptor sets L17/L18.") from exc

    if mode in _CALCULATORS:
        return _CALCULATORS[mode]

    if mode == "2d":
        calc = Calculator(descriptors, ignore_3D=True)
    elif mode == "3d":
        all_calc = Calculator(descriptors, ignore_3D=False)
        calc = Calculator([desc for desc in all_calc.descriptors if getattr(desc, "require_3D", False)])
    else:
        raise ValueError(f"Unsupported Mordred mode: {mode}")
    _CALCULATORS[mode] = calc
    return calc


def calc_mordred_2d(mol) -> dict:
    calc = _calculator("2d")
    result = calc(mol).asdict()
    return {f"mordred2d__{_safe_name(name)}": _to_float_or_none(value) for name, value in result.items()}


def calc_mordred_3d(mol3d) -> dict:
    calc = _calculator("3d")
    result = calc(mol3d).asdict()
    return {f"mordred3d__{_safe_name(name)}": _to_float_or_none(value) for name, value in result.items()}

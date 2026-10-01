"""Small explicit SI registry; no unit parser eval or implicit arbitrary definitions."""

import ast
from decimal import Decimal, localcontext, InvalidOperation
from fractions import Fraction
from bac.science.expressions import tree, identifier

ZERO = (Fraction(0),) * 7
# mass, length, time, current, temperature, amount, luminous intensity
DIMS = [
    "mass",
    "length",
    "time",
    "current",
    "temperature",
    "amount",
    "luminous_intensity",
]


def dim(*v):
    return tuple(Fraction(x) for x in v)


REGISTRY = {}


def add(names, scale, d):
    for name in names.split():
        REGISTRY[name] = (Decimal(scale), d)


add("kg", "1", dim(1, 0, 0, 0, 0, 0, 0))
add("g", ".001", REGISTRY["kg"][1])
add("mg", ".000001", REGISTRY["kg"][1])
add("m", "1", dim(0, 1, 0, 0, 0, 0, 0))
add("cm", ".01", REGISTRY["m"][1])
add("mm", ".001", REGISTRY["m"][1])
add("km", "1000", REGISTRY["m"][1])
add("s", "1", dim(0, 0, 1, 0, 0, 0, 0))
add("min", "60", REGISTRY["s"][1])
add("h", "3600", REGISTRY["s"][1])
add("A", "1", dim(0, 0, 0, 1, 0, 0, 0))
add("K delta_degC", "1", dim(0, 0, 0, 0, 1, 0, 0))
add("mol", "1", dim(0, 0, 0, 0, 0, 1, 0))
add("cd", "1", dim(0, 0, 0, 0, 0, 0, 1))
add("rad dimensionless", "1", ZERO)
add("N", "1", dim(1, 1, -2, 0, 0, 0, 0))
add("J", "1", dim(1, 2, -2, 0, 0, 0, 0))
add("W", "1", dim(1, 2, -3, 0, 0, 0, 0))
add("Pa", "1", dim(1, -1, -2, 0, 0, 0, 0))
add("kPa", "1000", REGISTRY["Pa"][1])
add("MPa", "1000000", REGISTRY["Pa"][1])
add("bar", "100000", REGISTRY["Pa"][1])
add("atm", "101325", REGISTRY["Pa"][1])
add("L", ".001", dim(0, 3, 0, 0, 0, 0, 0))
add("mL", ".000001", REGISTRY["L"][1])
add("Hz", "1", dim(0, 0, -1, 0, 0, 0, 0))
add("C", "1", dim(0, 0, 1, 1, 0, 0, 0))
add("V", "1", dim(1, 2, -3, -1, 0, 0, 0))
add("ohm", "1", dim(1, 2, -3, -2, 0, 0, 0))
add("eV", "1.602176634e-19", REGISTRY["J"][1])


def combine(a, b, sign=1):
    return tuple(x + sign * y for x, y in zip(a, b))


def unit(text):
    text = text.strip().replace("^", "**").replace("°C", "degC")
    if text == "degC":
        return Decimal(1), REGISTRY["K"][1], Decimal("273.15")

    def visit(n):
        if isinstance(n, ast.Name) and n.id in REGISTRY:
            return REGISTRY[n.id]
        if isinstance(n, ast.Constant) and n.value == 1 and type(n.value) is int:
            return Decimal(1), ZERO
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Mult, ast.Div)):
            a, d = visit(n.left)
            b, e = visit(n.right)
            return (
                (a * b, combine(d, e))
                if isinstance(n.op, ast.Mult)
                else (a / b, combine(d, e, -1))
            )
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Pow):
            p = n.right
            sign = (
                -1 if isinstance(p, ast.UnaryOp) and isinstance(p.op, ast.USub) else 1
            )
            c = p.operand if isinstance(p, ast.UnaryOp) else p
            if (
                not isinstance(c, ast.Constant)
                or type(c.value) is not int
                or abs(c.value) > 8
            ):
                raise ValueError("Unit powers must be integers from -8 to 8")
            exponent = sign * c.value
            a, d = visit(n.left)
            return a**exponent, tuple(x * exponent for x in d)
        raise ValueError(
            "Unknown/unsupported unit; Celsius offsets only as standalone degC, differences use delta_degC"
        )

    scale, dims = visit(tree(text, 60))
    return scale, dims, Decimal(0)


def convert(p):
    with localcontext() as c:
        c.prec = 50
        try:
            v = Decimal(p["value"])
        except InvalidOperation:
            raise ValueError("value must be a decimal string") from None
        if not v.is_finite() or abs(v) > Decimal("1e100"):
            raise ValueError("value out of range")
        a, d, offset_a = unit(p["from_unit"])
        b, e, offset_b = unit(p["to_unit"])
        compatible = d == e
        if not compatible:
            return {
                "status": "failed",
                "compatible": False,
                "reason": "DIMENSION_MISMATCH",
                "from_dimensions": dims_json(d),
                "to_dimensions": dims_json(e),
            }
        value = (v * a + offset_a - offset_b) / b
        return {
            "status": "computed",
            "value": str(value),
            "unit": p["to_unit"],
            "dimensions": dims_json(d),
            "precision_digits": 50,
            "scope": "SI conversion only; standalone degC is absolute temperature, delta_degC is a difference",
        }


def dims_json(d):
    return {k: str(v) for k, v in zip(DIMS, d) if v}


def verify(p):
    known = {}
    for name, text in p["units"].items():
        identifier(name)
        _, d, offset = unit(text)
        if offset:
            raise ValueError(
                "Use K for absolute temperature in equations, delta_degC for differences"
            )
        known[name] = d

    def visit(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            return ZERO
        if isinstance(n, ast.Name):
            if n.id in ("pi", "E"):
                return ZERO
            if n.id not in known:
                raise ValueError("Missing unit for " + n.id)
            return known[n.id]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            return visit(n.operand)
        if isinstance(n, ast.BinOp):
            a, b = visit(n.left), visit(n.right)
            if isinstance(n.op, (ast.Add, ast.Sub)):
                if a != b:
                    raise ValueError(
                        "Cannot add/subtract quantities with different dimensions"
                    )
                return a
            if isinstance(n.op, ast.Mult):
                return combine(a, b)
            if isinstance(n.op, ast.Div):
                return combine(a, b, -1)
            if isinstance(n.op, ast.Pow):
                if b != ZERO:
                    raise ValueError("Exponent must be dimensionless")
                try:
                    v = ast.literal_eval(n.right)
                except (ValueError, TypeError):
                    if a == ZERO:
                        return ZERO
                    raise ValueError(
                        "Dimensionful base requires a numeric exponent"
                    ) from None
                if type(v) not in (int, float) or abs(v) > 8:
                    raise ValueError("Power out of range")
                return tuple(x * Fraction(str(v)) for x in a)
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and not n.keywords
            and len(n.args) == 1
        ):
            d = visit(n.args[0])
            if n.func.id in ("sqrt", "abs"):
                return tuple(x / 2 for x in d) if n.func.id == "sqrt" else d
            if n.func.id in ("sin", "cos", "tan", "exp", "log") and d == ZERO:
                return ZERO
        raise ValueError("Unsupported dimensional syntax/function")

    try:
        a, b = visit(tree(p["lhs"])), visit(tree(p["rhs"]))
    except ValueError as e:
        return {
            "status": "inconclusive",
            "reason": str(e),
            "scope": "Dimensional consistency only, not numerical or physical correctness",
        }
    return {
        "status": "passed" if a == b else "failed",
        "compatible": a == b,
        "lhs_dimensions": dims_json(a),
        "rhs_dimensions": dims_json(b),
        "scope": "Dimensional consistency only, not numerical or physical correctness",
    }

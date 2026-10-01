import ast
import re
import sympy as sp

FUNCTIONS = {
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "asin": sp.asin,
    "acos": sp.acos,
    "atan": sp.atan,
    "exp": sp.exp,
    "log": sp.log,
    "sqrt": sp.sqrt,
    "abs": sp.Abs,
}
CONSTANTS = {"pi": sp.pi, "E": sp.E}


def identifier(s):
    if not isinstance(s, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", s):
        raise ValueError("Only simple ASCII variable names are allowed")
    if s in FUNCTIONS or s in CONSTANTS:
        raise ValueError("Reserved variable name")
    return s


def tree(text, limit=180):
    if not isinstance(text, str) or len(text) > 6000:
        raise ValueError("Input too long")
    t = ast.parse(text, mode="eval")
    if len(list(ast.walk(t))) > limit:
        raise ValueError("Expression too complex")
    return t.body


class Parser:
    def __init__(self, positive=()):
        self.positive = {identifier(x) for x in positive}
        self.symbols = {}

    def parse(self, text):
        self.text = text
        return self.visit(tree(text))

    def visit(self, n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            raw = ast.get_source_segment(self.text, n) or str(n.value)
            if len(raw) > 60 or not re.fullmatch(
                r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", raw
            ):
                raise ValueError("Unsupported numeric literal")
            value = sp.Rational(raw)
            if abs(value) > sp.Integer(10) ** 100:
                raise ValueError("Numeric literal out of range")
            return value
        if isinstance(n, ast.Name):
            if n.id in CONSTANTS:
                return CONSTANTS[n.id]
            identifier(n.id)
            if len(self.symbols) >= 20 and n.id not in self.symbols:
                raise ValueError("Too many variables")
            return self.symbols.setdefault(
                n.id,
                sp.Symbol(n.id, positive=True)
                if n.id in self.positive
                else sp.Symbol(n.id, real=True),
            )
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            v = self.visit(n.operand)
            return v if isinstance(n.op, ast.UAdd) else sp.Mul(-1, v, evaluate=False)
        if isinstance(n, ast.BinOp):
            a, b = self.visit(n.left), self.visit(n.right)
            if isinstance(n.op, ast.Add):
                return sp.Add(a, b, evaluate=False)
            if isinstance(n.op, ast.Sub):
                return sp.Add(a, sp.Mul(-1, b, evaluate=False), evaluate=False)
            if isinstance(n.op, ast.Mult):
                return sp.Mul(a, b, evaluate=False)
            if isinstance(n.op, ast.Div):
                return sp.Mul(a, sp.Pow(b, -1, evaluate=False), evaluate=False)
            if isinstance(n.op, ast.Pow):
                if b.is_number and (not b.is_real or abs(b) > 100):
                    raise ValueError("Exponent exceeds limit")
                return sp.Pow(a, b, evaluate=False)
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in FUNCTIONS
            and not n.keywords
        ):
            if not 1 <= len(n.args) <= (2 if n.func.id == "log" else 1):
                raise ValueError("Invalid function arity")
            return FUNCTIONS[n.func.id](
                *[self.visit(a) for a in n.args], evaluate=False
            )
        raise ValueError(
            "Forbidden expression syntax; no attributes, imports, strings or eval"
        )


def values_map(parser, values):
    result = {}
    for name, text in values.items():
        identifier(name)
        if not isinstance(text, str) or len(text) > 100:
            raise ValueError("Values must be short numeric expressions in strings")
        value = Parser().parse(text)
        if value.free_symbols:
            raise ValueError("Variable values must be constant")
        finite(value)
        symbol = parser.symbols.get(name, sp.Symbol(name, real=True))
        if symbol.is_positive and value.is_positive is not True:
            raise ValueError("Positive-symbol assumption contradicted")
        result[symbol] = value
    return result


def substituted(expr, values):
    missing = sorted(str(s) for s in expr.free_symbols - values.keys())
    if missing:
        raise ValueError("Missing values: " + ", ".join(missing))
    # Preserve denominator conditions before symbolic cancellation (x/x at x=0).
    for p in expr.atoms(sp.Pow):
        if (
            p.exp.is_number
            and p.exp.is_negative
            and sp.simplify(p.base.subs(values)) == 0
        ):
            raise ValueError(
                "Expression undefined at supplied values (zero denominator)"
            )
    out = expr.subs(values)
    finite(out)
    return out


def finite(expr):
    n = sp.N(expr, 50)
    if n.is_real is not True or n.is_finite is not True:
        raise ValueError("Undefined, non-real or non-finite result")
    if abs(n) > sp.Float("1e100"):
        raise ValueError("Result magnitude exceeds limit")
    return n


def numeric(expr):
    n = finite(expr)
    return {"exact": str(sp.simplify(expr)), "decimal": str(n), "precision_digits": 50}


def bounded(text, limit=6000):
    s = str(text)
    if len(s) > limit:
        raise ValueError("Symbolic result exceeds output limit")
    return s

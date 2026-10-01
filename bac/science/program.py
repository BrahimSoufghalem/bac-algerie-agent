"""Interpreted Python-shaped numeric subset; NEVER compile/exec user code."""

import ast
import math
from bac.science.expressions import identifier


class Program:
    def __init__(self, inputs, max_steps=12000):
        self.env = {}
        self.outputs = {}
        self.steps = 0
        self.iterations = 0
        self.max_steps = max_steps
        for key, value in inputs.items():
            self.name(key)
            self.env[key] = self.safe(value)

    def tick(self):
        self.steps += 1
        if self.steps > self.max_steps:
            raise ValueError("PROGRAM_STEP_LIMIT")

    def name(self, name):
        identifier(name)
        if name in (
            "emit",
            "range",
            "linspace",
            "sum",
            "min",
            "max",
            "len",
            "round",
            "pow",
        ):
            raise ValueError("Reserved program name")

    def safe(self, v):
        if isinstance(v, list):
            if len(v) > 401:
                raise ValueError("ARRAY_LIMIT")
            return [self.scalar(x) for x in v]
        return self.scalar(v)

    def scalar(self, v):
        if type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e100:
            raise ValueError("Expected a bounded finite real number")
        return v

    def expr(self, n):
        self.tick()
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            return self.scalar(n.value)
        if isinstance(n, ast.Name):
            if n.id == "pi":
                return math.pi
            if n.id == "E":
                return math.e
            if n.id not in self.env:
                raise ValueError("Undefined program variable")
            return self.env[n.id]
        if isinstance(n, ast.List):
            return self.safe([self.expr(x) for x in n.elts])
        if isinstance(n, ast.Subscript) and not isinstance(n.slice, ast.Slice):
            a, i = self.expr(n.value), self.expr(n.slice)
            if not isinstance(a, list) or type(i) is not int:
                raise ValueError("Only bounded list indexing")
            return a[i]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            a = self.scalar(self.expr(n.operand))
            return -a if isinstance(n.op, ast.USub) else a
        if isinstance(n, ast.BinOp):
            a, b = self.expr(n.left), self.expr(n.right)
            if isinstance(a, list) or isinstance(b, list):
                if (
                    isinstance(n.op, ast.Add)
                    and isinstance(a, list)
                    and isinstance(b, list)
                ):
                    return self.safe(a + b)
                raise ValueError("Lists support concatenation only")
            a, b = self.scalar(a), self.scalar(b)
            if isinstance(n.op, ast.Add):
                return self.scalar(a + b)
            if isinstance(n.op, ast.Sub):
                return self.scalar(a - b)
            if isinstance(n.op, ast.Mult):
                return self.scalar(a * b)
            if isinstance(n.op, ast.Div):
                return self.scalar(a / b)
            if isinstance(n.op, ast.Mod):
                return self.scalar(a % b)
            if isinstance(n.op, ast.Pow) and abs(b) <= 100:
                return self.scalar(a**b)
            raise ValueError("Unsupported/oversized operator")
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and not n.keywords:
            args = [self.expr(x) for x in n.args]
            name = n.func.id
            if (
                name == "range"
                and 1 <= len(args) <= 3
                and all(type(x) is int and abs(x) <= 10000 for x in args)
            ):
                r = range(*args)
                if len(r) > 401:
                    raise ValueError("ARRAY_LIMIT")
                return list(r)
            if (
                name == "linspace"
                and len(args) == 3
                and type(args[2]) is int
                and 2 <= args[2] <= 401
            ):
                a, b, c = args
                return self.safe([a + (b - a) * i / (c - 1) for i in range(c)])
            if (
                name in ("sum", "min", "max", "len")
                and len(args) == 1
                and isinstance(args[0], list)
            ):
                functions = {"sum": sum, "min": min, "max": max, "len": len}
                return self.scalar(functions[name](args[0]))
            f = {
                "sqrt": math.sqrt,
                "sin": math.sin,
                "cos": math.cos,
                "tan": math.tan,
                "exp": math.exp,
                "log": math.log,
                "abs": abs,
                "round": round,
            }
            if name in f and len(args) == 1:
                return self.scalar(f[name](self.scalar(args[0])))
            raise ValueError("Forbidden program function")
        raise ValueError("Forbidden program syntax")

    def condition(self, n):
        self.tick()
        if not isinstance(n, ast.Compare) or len(n.ops) != 1:
            raise ValueError("Only single numeric comparisons")
        a, b = self.scalar(self.expr(n.left)), self.scalar(self.expr(n.comparators[0]))
        op = n.ops[0]
        if isinstance(op, ast.Lt):
            return a < b
        if isinstance(op, ast.LtE):
            return a <= b
        if isinstance(op, ast.Gt):
            return a > b
        if isinstance(op, ast.GtE):
            return a >= b
        if isinstance(op, ast.Eq):
            return a == b
        if isinstance(op, ast.NotEq):
            return a != b
        raise ValueError("Forbidden comparison")

    def statements(self, body):
        for n in body:
            self.tick()
            if (
                isinstance(n, ast.Assign)
                and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
            ):
                key = n.targets[0].id
                self.name(key)
                if len(self.env) >= 32 and key not in self.env:
                    raise ValueError("VARIABLE_LIMIT")
                self.env[key] = self.safe(self.expr(n.value))
            elif (
                isinstance(n, ast.For)
                and isinstance(n.target, ast.Name)
                and not n.orelse
            ):
                self.name(n.target.id)
                items = self.expr(n.iter)
                if not isinstance(items, list):
                    raise ValueError("for requires a finite numeric list")
                for item in items:
                    self.iterations += 1
                    if self.iterations > 2000:
                        raise ValueError("LOOP_LIMIT")
                    self.env[n.target.id] = item
                    self.statements(n.body)
            elif isinstance(n, ast.If):
                self.statements(n.body if self.condition(n.test) else n.orelse)
            elif (
                isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Name)
                and n.value.func.id == "emit"
                and len(n.value.args) == 2
                and not n.value.keywords
            ):
                label = n.value.args[0]
                if (
                    not isinstance(label, ast.Constant)
                    or not isinstance(label.value, str)
                    or not 1 <= len(label.value) <= 64
                ):
                    raise ValueError("emit requires a short literal label")
                if label.value in self.outputs:
                    raise ValueError("Duplicate output label")
                if len(self.outputs) >= 12:
                    raise ValueError("OUTPUT_LIMIT")
                self.outputs[label.value] = self.safe(self.expr(n.value.args[1]))
            else:
                raise ValueError(
                    "Forbidden statement: imports/attributes/while/definitions/comprehensions/exec/files/network are unavailable"
                )

    def run(self, code):
        t = ast.parse(code, mode="exec")
        if len(list(ast.walk(t))) > 500:
            raise ValueError("PROGRAM_AST_LIMIT")
        # Validate all branches, including unreachable malicious statements.
        allowed = (
            ast.Module,
            ast.Assign,
            ast.Name,
            ast.Load,
            ast.Store,
            ast.Constant,
            ast.List,
            ast.Subscript,
            ast.UnaryOp,
            ast.UAdd,
            ast.USub,
            ast.BinOp,
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.Div,
            ast.Mod,
            ast.Pow,
            ast.For,
            ast.If,
            ast.Compare,
            ast.Lt,
            ast.LtE,
            ast.Gt,
            ast.GtE,
            ast.Eq,
            ast.NotEq,
            ast.Expr,
            ast.Call,
        )
        if any(not isinstance(n, allowed) for n in ast.walk(t)):
            raise ValueError("Forbidden program AST")
        functions = {
            "emit",
            "range",
            "linspace",
            "sum",
            "min",
            "max",
            "len",
            "sqrt",
            "sin",
            "cos",
            "tan",
            "exp",
            "log",
            "abs",
            "round",
        }
        for node in ast.walk(t):
            if isinstance(node, ast.Call) and (
                not isinstance(node.func, ast.Name)
                or node.func.id not in functions
                or node.keywords
            ):
                raise ValueError(
                    "Forbidden program call, including unreachable branches"
                )
        self.statements(t.body)
        if not self.outputs:
            raise ValueError('Use emit("label", value) to return results')
        return {
            "status": "computed",
            "outputs": self.outputs,
            "steps": self.steps,
            "iterations": self.iterations,
            "scope": "Binary64 numeric subset, not arbitrary Python; execution does not verify the model or physical assumptions",
        }

"""Trusted child entry point. All untrusted text is interpreted via allowlisted ASTs."""

import json
import math
import sys
import sympy as sp
from sympy.calculus.util import continuous_domain
from bac.science.expressions import (
    Parser,
    identifier,
    values_map,
    substituted,
    numeric,
    finite,
    bounded,
)
from bac.science.program import Program
from bac.science import units

from bac.science.registry import CONTRACTS


def comparison(a, b, absolute, relative):
    # Subtract symbolically before rounding so (1e99 + 1) vs 1e99 cannot fake zero.
    difference = sp.N(sp.Abs(sp.simplify(a - b)), 50)
    tolerance = sp.Float(str(absolute), 50) + sp.Float(str(relative), 50) * max(
        abs(finite(a)), abs(finite(b))
    )
    passed = bool(difference <= tolerance)
    return {
        "status": "passed" if passed else "failed",
        "actual": numeric(a),
        "expected": numeric(b),
        "absolute_error": str(difference),
        "effective_tolerance": str(tolerance),
        "comparison": "absolute + relative * max(|actual|,|expected|)",
    }


def equation(p):
    parser = Parser()
    lhs = parser.parse(p["lhs"])
    rhs = parser.parse(p["rhs"])
    conditions = [
        (x, parser.parse(x["lhs"]), parser.parse(x["rhs"])) for x in p["conditions"]
    ]
    values = values_map(parser, p["values"])
    missing = sorted(
        {
            str(x)
            for e in [lhs, rhs] + [e for _, a, b in conditions for e in (a, b)]
            for x in e.free_symbols - values.keys()
        }
    )
    if missing:
        return {
            "status": "inconclusive",
            "missing_values": missing,
            "scope": "Only supplied equation and constraints, not whether the original problem has sufficient data",
        }
    a, b = substituted(lhs, values), substituted(rhs, values)
    out = comparison(a, b, p["absolute_tolerance"], p["relative_tolerance"])
    checks = []
    for condition, x, y in conditions:
        left, right = substituted(x, values), substituted(y, values)
        difference = sp.N(sp.simplify(left - right), 50)
        x, y = finite(left), finite(right)
        r = condition["relation"]
        passed = {
            "eq": difference == 0,
            "ne": difference != 0,
            "lt": difference < 0,
            "le": difference <= 0,
            "gt": difference > 0,
            "ge": difference >= 0,
        }[r]
        checks.append(
            {
                "condition": condition,
                "passed": bool(passed),
                "lhs_value": str(x),
                "rhs_value": str(y),
            }
        )
    out["conditions"] = checks
    if any(not x["passed"] for x in checks):
        out["status"] = "failed"
    out["scope"] = (
        "Only the supplied equation and explicit constraints; does not certify interpretation, completeness or officialness"
    )
    return out


def domains(expr, var):
    domain = continuous_domain(expr, var, sp.S.Reals)
    return domain.intersect(sp.Interval.open(0, sp.oo)) if var.is_positive else domain


def symbolic(p):
    parser = Parser(p["positive_symbols"])
    expr = parser.parse(p["expression"])
    other = parser.parse(p["other"])
    identifier(p["variable"])
    var = parser.symbols.get(p["variable"], sp.Symbol(p["variable"], real=True))
    original = {
        "expression": p["expression"],
        "assumptions": {"symbols": "real", "positive": p["positive_symbols"]},
    }
    op = p["operation"]
    status = "computed"
    if op == "simplify":
        value = sp.simplify(expr)
    elif op == "differentiate":
        value = sp.diff(expr, var)
    elif op == "integrate":
        value = sp.integrate(expr, var)
    elif op == "compare":
        if (expr.free_symbols | other.free_symbols) - {var}:
            return original | {
                "status": "inconclusive",
                "reason": "Multivariate original domains are not certified; compare one explicit variable at a time",
            }
        diff = sp.simplify(expr - other)
        try:
            same_domain = domains(expr, var) == domains(other, var)
        except (NotImplementedError, ValueError, TypeError):
            same_domain = False
        status = "passed" if diff == 0 and same_domain else "inconclusive"
        return original | {
            "status": status,
            "difference": bounded(diff),
            "same_real_domain": same_domain,
            "scope": "Algebraic comparison under stated assumptions; different/unknown original domains do not pass",
        }
    else:
        if (expr - other).free_symbols - {var}:
            return original | {
                "status": "inconclusive",
                "reason": "Supply a univariate equation; no guessed parameter values",
            }
        solution = sp.solveset(expr - other, var, domain=sp.S.Reals)
        try:
            solution = solution.intersect(domains(expr, var)).intersect(
                domains(other, var)
            )
        except (NotImplementedError, ValueError, TypeError):
            return original | {
                "status": "inconclusive",
                "candidate_set": bounded(solution),
                "reason": "Original domain could not be confirmed",
            }
        status = (
            "inconclusive" if solution.has(sp.ConditionSet, sp.Integral) else "computed"
        )
        if isinstance(solution, sp.FiniteSet):
            if len(solution) > 30:
                raise ValueError("Too many solutions")
            verified = []
            for x in solution:
                try:
                    a, b = substituted(expr, {var: x}), substituted(other, {var: x})
                    verified.append(
                        {
                            "value": bounded(x),
                            "substitution_passed": sp.simplify(a - b) == 0,
                        }
                    )
                except ValueError:
                    verified.append({"value": bounded(x), "substitution_passed": False})
            return original | {
                "status": status,
                "solution_set": bounded(solution),
                "solutions": verified,
                "scope": "Real solutions of supplied equation with original domain checks; not original problem interpretation",
            }
        return original | {
            "status": status,
            "solution_set": bounded(solution),
            "scope": "Real supplied equation, not completeness of original problem conditions",
        }
    if value.has(sp.Integral):
        status = "inconclusive"
    try:
        domain = bounded(domains(expr, var))
    except (NotImplementedError, ValueError, TypeError):
        domain = "unknown; preserve original expression restrictions"
    return original | {
        "status": status,
        "result": bounded(value),
        "latex": bounded(sp.latex(value)),
        "original_real_domain": domain,
        "scope": "Symbolic transformation under stated assumptions; indefinite integrals omit +C, not a proof of the whole answer",
    }


def validate_plot(p):
    series = p["series"]
    count = 0
    for s in series:
        if any(not math.isfinite(x) or abs(x) > 1e100 for x in s["x"]):
            raise ValueError("Non-finite/out-of-range x")
        if any(
            y is not None and (not math.isfinite(y) or abs(y) > 1e100) for y in s["y"]
        ):
            raise ValueError("Non-finite/out-of-range y")
        if not any(y is not None for y in s["y"]):
            raise ValueError("No real plot points")
        if p["kind"] != "scatter" and any(a >= b for a, b in zip(s["x"], s["x"][1:])):
            raise ValueError("Line/bar x coordinates must be strictly increasing")
        count += len(s["x"])
    if count > 804:
        raise ValueError("Total chart point limit 804")
    return {
        "status": "computed",
        "chart": p,
        "validation": {"finite_values": True, "point_count": count},
        "origin": "model_supplied_data",
        "scope": "Data shape/finite-value validation only; no verification of physical assumptions or source transcription",
    }


def plot_function(p):
    parser = Parser()
    expr = parser.parse(p["expression"])
    identifier(p["variable"])
    var = parser.symbols.get(p["variable"], sp.Symbol(p["variable"], real=True))
    parameters = values_map(parser, p.get("values", {}))
    if var in parameters:
        raise ValueError("Do not bind the plotting variable in values")
    denominators = [
        factor.base.subs(parameters)
        for factor in expr.atoms(sp.Pow)
        if factor.exp.is_number and factor.exp.is_negative
    ]
    if parameters:
        expr = expr.subs(parameters)
    if expr.free_symbols - {var}:
        raise ValueError(
            "Function plot needs one variable; supply each other constant in values as a numeric expression string"
        )
    domain = domains(expr, var).intersect(sp.Interval(p["lower"], p["upper"]))
    # Substitution must not erase a zero-denominator exclusion by simplification.
    for denominator in denominators:
        domain -= sp.solveset(denominator, var, domain=sp.S.Reals)
    intervals = list(domain.args) if isinstance(domain, sp.Union) else [domain]
    if (
        not intervals
        or len(intervals) > 4
        or any(not isinstance(i, sp.Interval) for i in intervals)
    ):
        raise ValueError("Unsupported or empty plot domain; provide explicit data")
    series = []
    for i, interval in enumerate(sorted(intervals, key=lambda x: float(x.start))):
        a, b = float(interval.start), float(interval.end)
        if interval.left_open:
            a = math.nextafter(a, b) + (b - a) * 1e-6
        if interval.right_open:
            b = math.nextafter(b, a) - (b - a) * 1e-6
        xs = [a + (b - a) * j / (p["samples"] - 1) for j in range(p["samples"])]
        ys = []
        for x in xs:
            try:
                y = float(finite(substituted(expr, {var: sp.Float(x, 50)})))
                ys.append(y if math.isfinite(y) else None)
            except ValueError:
                ys.append(None)
        series.append(
            {
                "label": p["expression"]
                + (f" · domain {i + 1}" if len(intervals) > 1 else ""),
                "x": xs,
                "y": ys,
            }
        )
    chart = {
        "title": p["title"],
        "x_label": p["x_label"],
        "y_label": p["y_label"],
        "kind": "line",
        "series": series,
    }
    result = validate_plot(chart)
    return result | {
        "origin": "sampled_function",
        "expression": p["expression"],
        "real_domain": bounded(domain),
        "scope": "Sampled curve; disjoint real domains are separated. Sampling is not a proof of continuity, extrema or physical validity",
    }


def execute(name, p):
    p = CONTRACTS[name].model_validate(p).model_dump()
    if name == "calculate" or name == "verify_calculation":
        parser = Parser()
        expr = parser.parse(p["expression"])
        other = parser.parse(p["expected"]) if name == "verify_calculation" else None
        values = values_map(parser, p["values"])
        actual = substituted(expr, values)
        if other is not None:
            return comparison(
                actual,
                substituted(other, values),
                p["absolute_tolerance"],
                p["relative_tolerance"],
            ) | {
                "scope": "Only the supplied calculation and expected value, not the complete explanation"
            }
        return {
            "status": "computed",
            **numeric(actual),
            "scope": "50-digit numerical evaluation of supplied expression; decimal literals are exact rationals",
        }
    if name == "verify_equation":
        return equation(p)
    if name == "symbolic_math":
        return symbolic(p)
    if name == "convert_units":
        return units.convert(p)
    if name == "verify_dimensions":
        return units.verify(p)
    if name == "run_scientific_code":
        return Program(p["inputs"]).run(p["code"])
    if name == "plot_function":
        return plot_function(p)
    if name == "plot_data":
        return validate_plot(p)
    if name == "draw_diagram":
        return {
            "status": "computed",
            "diagram": p,
            "origin": "provided_geometry",
            "scope": "Only finite bounded geometry validated; vectors/circles are a schematic, not a source image or verified physical model",
        }
    raise ValueError("Unknown science tool")


def main():
    request = json.loads(sys.stdin.read(18000))
    try:
        result = execute(request["name"], request["arguments"])
        text = json.dumps(
            result, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        if len(text) > request["max_output"]:
            raise ValueError("SCIENTIFIC_OUTPUT_LIMIT")
    except Exception as e:
        text = json.dumps(
            {"error": "SCIENTIFIC_INPUT_OR_COMPUTATION_ERROR", "message": str(e)[:250]},
            ensure_ascii=False,
        )
    sys.stdout.write(text)

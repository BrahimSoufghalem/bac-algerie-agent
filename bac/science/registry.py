from bac.science import contracts as c

CONTRACTS = {
    "calculate": c.Calculate,
    "verify_calculation": c.VerifyCalculation,
    "verify_equation": c.VerifyEquation,
    "symbolic_math": c.Symbolic,
    "convert_units": c.ConvertUnit,
    "verify_dimensions": c.VerifyDimensions,
    "run_scientific_code": c.ScientificCode,
    "plot_function": c.PlotFunction,
    "plot_data": c.Plot,
    "draw_diagram": c.Diagram,
}
DESCRIPTIONS = {
    "draw_diagram": "Create bounded 2D geometry (vectors, segments, circles, points) from explicit coordinates. Equal axis scale. Geometry validation only, no physics proof; no SVG/HTML input.",
    "calculate": "Evaluate a real numeric expression at 50 digits; decimal strings preserve exact values. AST syntax only, use ** for powers.",
    "verify_calculation": "Independently compare a supplied calculation with expected value under explicit tolerances; not verification of the entire explanation.",
    "verify_equation": "Check substitution into lhs/rhs and explicit constraints at supplied values; incomplete values return inconclusive. No guessed conditions.",
    "symbolic_math": "Simplify/differentiate/integrate/solve/compare real expressions with SymPy; preserve domain restrictions. Operation results are not automatically verification.",
    "convert_units": "Convert explicit SI units, e.g. MPa to Pa, degC to K. delta_degC for temperature differences. No guessed unit definitions.",
    "verify_dimensions": "Verify dimensional consistency of lhs/rhs using explicit variable units; this does not verify numerical/physical correctness.",
    "run_scientific_code": 'Restricted numeric AST, not normal Python. Use ts=linspace(0,2,21), ys=[], for t in ts: ys=ys+[v0y-g*t], then emit("time",ts), emit("velocity",ys), with finite numeric inputs. No imports/math.attribute, list comprehensions, numpy, while, filesystem/network. Use linspace for decimal steps; range uses integers. Outputs feed plot_from_result. Numerical examples need explicit assumptions.',
    "plot_function": 'One real function. Required: expression, lower, upper, title. variable is a simple ASCII name; constants go in values as numeric strings. Example: expression="v0y-g*t", variable="t", values={"v0y":"10","g":"9.8"}, lower=0, upper=2, samples=41, title="Illustrative velocity", x_label="time (s)", y_label="velocity (m/s)". Use **, not ^ or LaTeX. samples=21..201; lower<upper. Constant functions are valid. Label invented example values, never treat them as source data. Returned chart is sampled, not physics proof.',
    "plot_data": 'Numeric line/scatter/bar chart. Required title,x_label,y_label,series. series=[{"label":"v","x":[0,1,2],"y":[10,0.2,-9.6]}]; each x/y list has the same length >=2, finite numbers (y may be null). No expression-based series or SVG. Only shape/finiteness validated, not factual origin. Prefer plot_function or plot_from_result for computed data.',
}

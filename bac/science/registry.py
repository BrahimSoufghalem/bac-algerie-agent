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
    "run_scientific_code": 'Execute interpreted restricted numeric Python-shaped AST. Assignments, bounded for/if, numeric lists, range/linspace, math functions, emit("name", value). No imports, attributes, while, filesystem, network, shell or arbitrary Python.',
    "plot_function": "Sample a univariate real function into safe chart JSON; separate disjoint real domains. Chart is sampled, not proof of continuity or physics.",
    "plot_data": "Build a bounded 2D line/scatter/bar chart from supplied numeric data; only shape and finiteness verified, not factual origin.",
}

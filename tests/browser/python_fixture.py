"""Offline browser transport: ONLY fixed trusted programs, not a sandbox fallback.

Production never imports this test module. Real hostile-code/container tests live
in test_python_sandbox.py and its Docker-enabled CI job.
"""

from bac.science.python_child import compute
from bac.science.python_contract import validate_output

CHART_CODES = {
    kind: """v, a = 3, 2
xs = [i/10 for i in range(21)]
ys = [v*t + a*t*t/2 for t in xs]
check("proposed addition", 2+2 == 5, "exact integer claim; intentionally fails")
def multiply_dimensions(first, second):
    keys = first.keys() | second.keys()
    return {k: first.get(k,0)+second.get(k,0) for k in keys if first.get(k,0)+second.get(k,0)}
length = {"m":1}
time = {"s":1}
velocity = {"m":1,"s":-1}
acceleration = {"m":1,"s":-2}
check("both distance terms have length dimension", multiply_dimensions(velocity,time)==length and multiply_dimensions(multiply_dimensions(acceleration,time),time)==length)
emit("chart", {"title":"الحركة تحت تسارع ثابت — بيانات اختبار","x_label":"time (s)","y_label":"distance (m)","kind":KIND,"series":[{"label":"distance","x":xs,"y":ys}]})""".replace(
        "KIND", repr(kind)
    )
    for kind in ("line", "bar", "scatter")
}
DIAGRAM_CODE = """emit("diagram", {"title":"مخطط متجه تعليمي — مثال مقيّد","x_min":-2,"x_max":2,"y_min":-2,"y_max":2,"elements":[{"kind":"circle","x":0,"y":0,"radius":0.4},{"kind":"vector","x":0,"y":0,"x2":1,"y2":1,"label":"F = ma"}]})"""
VELOCITY_CODE = """ts = [i/10 for i in range(21)]
ys = [10-9.8*t for t in ts]
emit("chart", {"title":"مثال توضيحي","x_label":"t (s)","y_label":"vy (m/s)","kind":"line","series":[{"label":"vy","x":ts,"y":ys}]})"""
PROGRAMS = {code: code for code in [*CHART_CODES.values(), DIAGRAM_CODE, VELOCITY_CODE]}


def fixed_python_result(self, args):
    canonical = PROGRAMS.get(args.get("code"))
    if canonical is None or args.get("inputs"):
        raise ValueError("Only fixed trusted offline browser fixtures are allowed")
    result = validate_output(
        compute({"code": canonical, "inputs": {}, "limits": {"output_chars": 16000}})
    )
    result["scope"] = (
        "Executed fixed trusted offline fixture, not a real provider or a container-isolation test"
    )
    return result

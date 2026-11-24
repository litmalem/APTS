import ast
import inspect
import textwrap

from mission_orchestrator.service import CanonicalMissionService

MISSION_ID = "mission-gmo-e672e544-c49e-4ece-a08c-f3a9f8c972d7"

svc = CanonicalMissionService()
repo = svc.repository

source = textwrap.dedent(
    inspect.getsource(CanonicalMissionService._build_repository_persistence_view)
)
tree = ast.parse(source)
func = tree.body[0]

def repo_method_from_call(expr):
    if not isinstance(expr, ast.Call):
        return None

    f = expr.func
    if (
        isinstance(f, ast.Attribute)
        and isinstance(f.value, ast.Attribute)
        and f.value.attr == "repository"
        and isinstance(f.value.value, ast.Name)
        and f.value.value.id == "self"
    ):
        return f.attr

    for arg in expr.args:
        found = repo_method_from_call(arg)
        if found:
            return found

    return None

assignments = {}

for node in ast.walk(func):
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name):
            method = repo_method_from_call(node.value)
            if method:
                assignments[target.id] = method

def flatten_and(expr):
    if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.And):
        out = []
        for value in expr.values:
            out.extend(flatten_and(value))
        return out
    return [expr]

def record_table(expr):
    if (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "get"
        and isinstance(expr.func.value, ast.Name)
        and expr.func.value.id == "record_counts"
        and expr.args
        and isinstance(expr.args[0], ast.Constant)
    ):
        return expr.args[0].value
    return None

def expected_expr(expr):
    if (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id == "len"
        and expr.args
        and isinstance(expr.args[0], ast.Name)
    ):
        return ("len", expr.args[0].id)

    if isinstance(expr, ast.IfExp):
        if (
            isinstance(expr.body, ast.Constant)
            and expr.body.value == 1
            and isinstance(expr.orelse, ast.Constant)
            and expr.orelse.value == 0
            and isinstance(expr.test, ast.Name)
        ):
            return ("presence", expr.test.id)

    if isinstance(expr, ast.Constant) and isinstance(expr.value, int):
        return ("constant", expr.value)

    return ("unknown", ast.unparse(expr) if hasattr(ast, "unparse") else type(expr).__name__)

checks = []

for node in ast.walk(func):
    if isinstance(node, ast.Assign):
        if any(isinstance(t, ast.Name) and t.id == "counts_ok" for t in node.targets):
            for item in flatten_and(node.value):
                if isinstance(item, ast.Compare) and len(item.ops) == 1:
                    left_table = record_table(item.left)
                    right = item.comparators[0]

                    if left_table:
                        checks.append((left_table, expected_expr(right)))

record_counts = repo.get_repository_record_counts(MISSION_ID)

cache = {}

def invoke(var_name):
    if var_name in cache:
        return cache[var_name]

    method_name = assignments.get(var_name)
    if not method_name:
        cache[var_name] = ("METHOD_UNRESOLVED", None)
        return cache[var_name]

    fn = getattr(repo, method_name, None)
    if not callable(fn):
        cache[var_name] = (f"METHOD_NOT_FOUND:{method_name}", None)
        return cache[var_name]

    try:
        value = fn(MISSION_ID)
        cache[var_name] = (method_name, value)
    except Exception as exc:
        cache[var_name] = (f"ERROR:{method_name}:{exc}", None)

    return cache[var_name]

print("REPOSITORY RECORD COUNT AUDIT")
print("mission_id:", MISSION_ID)
print("driver:", repo.driver)
print("sqlite_path:", getattr(repo, "sqlite_path", None))
print()

print(f"{'Table':55} {'DB':>6} {'Reconstructed':>14} Status  Source")
print("-" * 105)

mismatches = []
unknowns = []

for table, spec in checks:
    mode = spec[0]
    db_count = record_counts.get(table)

    if mode == "constant":
        reconstructed = spec[1]
        source = "constant"
    elif mode in ("len", "presence"):
        var_name = spec[1]
        source, value = invoke(var_name)

        if source.startswith("METHOD_") or source.startswith("ERROR:"):
            reconstructed = "?"
            unknowns.append((table, source))
        elif mode == "len":
            reconstructed = len(value or [])
        else:
            reconstructed = 1 if value else 0
    else:
        reconstructed = "?"
        source = "unknown_expr:" + str(spec[1])
        unknowns.append((table, source))

    status = "PASS" if db_count == reconstructed else "FAIL"
    if status == "FAIL":
        mismatches.append((table, db_count, reconstructed, source))

    print(f"{table:55} {str(db_count):>6} {str(reconstructed):>14} {status:6} {source}")

print()
print("MISMATCH COUNT:", len(mismatches))
if mismatches:
    print("MISMATCHES:")
    for table, db_count, reconstructed, source in mismatches:
        print(f"- {table}: db={db_count}, reconstructed={reconstructed}, source={source}")

if unknowns:
    print()
    print("UNRESOLVED ITEMS:")
    for table, source in unknowns:
        print(f"- {table}: {source}")

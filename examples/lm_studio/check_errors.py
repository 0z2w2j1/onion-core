import ast, os, sys

root = r"C:\Users\ZWJ\Desktop\a\Onion Core"
results = []

for r, dirs, files in os.walk(root):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git')]
    for f in files:
        if f.endswith('.py'):
            fp = os.path.join(r, f)
            try:
                with open(fp, encoding='utf-8') as fh:
                    ast.parse(fh.read())
                results.append(f"OK: {fp}")
            except SyntaxError as e:
                results.append(f"SYNTAX ERROR: {fp}:{e.lineno}: {e.msg}")

with open(r"C:\Users\ZWJ\Desktop\a\Onion Core\check_result.txt", "w", encoding="utf-8") as out:
    out.write("\n".join(results))

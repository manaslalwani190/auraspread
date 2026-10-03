import re

with open("web/js/app.js", "r", encoding="utf-8") as f:
    js_code = f.read()

with open("web/index.html", "r", encoding="utf-8") as f:
    html_code = f.read()

js_ids = set(re.findall(r"document\.getElementById\(['\"]([^'\"]+)['\"]\)", js_code))
html_ids = set(re.findall(r'id=["\']([^"\']+)["\']', html_code))

# Also check dynamic IDs like normPrice-${sym}
static_js_ids = {i for i in js_ids if "${" not in i}
missing = static_js_ids - html_ids
print(f"Total JS getElementById references: {len(js_ids)}")
print(f"Total HTML id attributes: {len(html_ids)}")
print(f"Missing IDs: {missing}")

selectors = re.findall(r"document\.querySelector(?:All)?\(['\"]([^'\"]+)['\"]\)", js_code)
print(f"\nTotal querySelector(All) calls: {len(selectors)}")
for sel in sorted(set(selectors)):
    if sel.startswith("."):
        cls = sel[1:]
        found = cls in html_code or cls in js_code
        print(f"  Class {sel}: {'FOUND' if found else 'MISSING'}")
    elif sel.startswith("#"):
        eid = sel[1:]
        found = eid in html_ids
        print(f"  ID {sel}: {'FOUND' if found else 'MISSING'}")
    else:
        print(f"  Selector {sel}: CHECKED")

# Pre-Push Checklist

Run through these steps before pushing any changes to the main branch.

## 1. Syntax Check
```bash
python -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('app.py OK')"
python -c "
import ast, pathlib
for f in pathlib.Path('modules').glob('*.py'):
    ast.parse(f.read_text(encoding='utf-8'))
    print(f'OK: {f}')
"
```

## 2. Import Check
```bash
python -c "import app" 2>&1 | head -5
```

## 3. Security Checks
- [ ] No API keys or secrets in code or committed files
- [ ] `.streamlit/api_keys.json` is in `.gitignore`
- [ ] No hardcoded URLs pointing to internal services
- [ ] `verify=False` not added to any new requests calls
- [ ] User-supplied URLs go through `validate_audit_url()` SSRF guard

## 4. Functional Checks
- [ ] Run a single-URL audit — score renders, no Python exceptions
- [ ] Bulk CSV upload works (test with a small file, ≤10 URLs)
- [ ] Sitemap XML upload works
- [ ] Issues tab shows issues with `impact_score` and `effort` fields populated
- [ ] Dark mode and light mode both readable

## 5. Dependency Changes
- [ ] If you added a new package, it's in `requirements.txt` with a `>=x.y,<z.0` range
- [ ] Run `pip install -r requirements.txt` to confirm no conflicts

## 6. Git Hygiene
```bash
git status          # no unintended files staged
git diff --cached   # review every line before committing
```

## 7. Push
```bash
git push origin main
```

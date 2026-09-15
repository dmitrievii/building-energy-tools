from pathlib import Path

path = Path(__file__).resolve().parents[1] / "tests" / "test_public_ux_contract.py"
text = path.read_text(encoding="utf-8")
old = "self.assertEqual(len(NAVIGATION_PAGES), 11)"
new = "self.assertEqual(len(NAVIGATION_PAGES), 12)"
if text.count(old) != 1:
    raise RuntimeError(f"Expected one navigation cardinality assertion, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Navigation cardinality contract updated to 12 pages")

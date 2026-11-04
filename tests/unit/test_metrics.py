import textwrap
from pathlib import Path

import pytest

from app.exceptions import EmptyRepositoryError, UnsupportedLanguageError
from app.metrics.halstead import c_family_halstead
from app.metrics.languages import detect_language, is_ignored
from app.metrics.lizard_metrics import analyse_with_lizard
from app.metrics.metric_extractor import MetricExtractor
from app.metrics.oo_metrics import compute_oo_metrics
from app.metrics.python_metrics import analyse_python
from app.ml.features import CLASS_FEATURES, FUNCTION_FEATURES

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "samples" / "sample_project"


def src(s):
    return textwrap.dedent(s).lstrip("\n")


def write(tmp, rel, text):
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src(text), encoding="utf-8")
    return p


# ------------------------------------------------------------------ python functions
def test_python_halstead_counts_all_tokens():
    a = analyse_python("def f(a):\n    return a + 1\n", "m.py")
    m = a.functions[0].metrics
    # operators: def ( : return +   (closing bracket not counted)   operands: f a a 1
    assert (m["halstead_n1"], m["halstead_N1"]) == (5, 5)
    assert (m["halstead_n2"], m["halstead_N2"]) == (3, 4)


def test_python_loc_classes_and_complexity():
    code = src('''
        def g(x):
            """Docstring."""
            # a comment

            if x and x > 2:  # inline
                return 1
            return 0
        ''')
    m = analyse_python(code, "m.py").functions[0].metrics
    assert m["loc_total"] == 7
    assert m["loc_blank"] == 1
    assert m["loc_comments"] == 2           # docstring + comment-only line
    assert m["loc_code_and_comment"] == 1
    assert m["loc_executable"] == 3
    assert m["cyclomatic_complexity"] == 3   # if + and
    assert m["branch_count"] == 2 * 3 - 1


def test_every_function_unit_has_exact_feature_set():
    a = analyse_python((SAMPLE / "inventory" / "pricing.py").read_text(), "pricing.py")
    for u in a.functions:
        assert list(u.metrics) == FUNCTION_FEATURES


def test_script_without_functions_becomes_module_unit():
    a = analyse_python("import sys\nfor a in sys.argv:\n    print(a)\n", "s.py")
    assert [u.name for u in a.functions] == ["<module>"]
    assert a.functions[0].metrics["cyclomatic_complexity"] == 2


def test_nested_function_belongs_to_parent_unit():
    a = analyse_python(src('''
        def outer():
            def inner():
                return 1
            return inner()
        '''), "n.py")
    assert [u.qualname for u in a.functions] == ["outer"]


def test_syntax_error_raises():
    with pytest.raises(SyntaxError):
        analyse_python("def broken(:\n  pass\n", "b.py")


# ------------------------------------------------------------------ OO metrics
OO_CODE = '''
    import json

    class Base:
        def __init__(self):
            self.a = 1
            self.b = 2

        def get_a(self):
            return self.a

        def get_b(self):
            return self.b

        def _helper(self):
            return json.dumps(self.a)

    class Child(Base):
        def run(self):
            return self.get_a()

    class GrandChild(Child):
        pass
    '''


def _oo(code):
    a = analyse_python(src(code), "oo.py")
    return {q: m for (_, q), m in compute_oo_metrics(a.classes).items()}


def test_ck_metrics_follow_ckjm_conventions():
    m = _oo(OO_CODE)
    base, child, grand = m["Base"], m["Child"], m["GrandChild"]
    assert list(base) == CLASS_FEATURES
    assert (base["dit"], child["dit"], grand["dit"]) == (1, 2, 3)
    assert (base["noc"], child["noc"], grand["noc"]) == (1, 1, 0)
    assert base["wmc"] == 4 and base["npm"] == 3          # __init__ public, _helper private
    # pairs: (init,get_a) (init,get_b) (init,_helper) share; (get_a,get_b) (get_b,_helper) don't;
    # (get_a,_helper) share  -> P=2, Q=4 -> LCOM=max(P-Q,0)=0
    assert base["lcom"] == 0
    # LCOM3: m=4, attrs {a,b}: mu(a)=3, mu(b)=2 -> (4 - 2.5)/3 = 0.5
    assert base["lcom3"] == pytest.approx(0.5)
    assert child["lcom3"] == 2.0 and grand["lcom3"] == 2.0  # degenerate -> ckjm's 2
    assert base["ce"] == 1                                   # json
    assert base["rfc"] == 5                                  # 4 methods + dumps
    assert base["loc"] > 0 and base["amc"] == pytest.approx(base["loc"] / 4)
    assert grand["wmc"] == 0 and grand["amc"] == 0


def test_decorated_methods_get_bytecode_size():
    m = _oo('''
        class A:
            @property
            def x(self):
                return [i * 2 for i in range(10)]
        ''')
    assert m["A"]["loc"] > 5


# ------------------------------------------------------------------ other languages
def test_java_function_complexity_and_comment_lines():
    code = src('''
        class A {
            // comment only
            int f(int x) {
                if (x > 0 && x < 10) { return 1; } // trailing
                return 0;
            }
        }
        ''')
    units, totals = analyse_with_lizard(code, "A.java")
    f = next(u for u in units if u.name == "f")
    assert f.metrics["cyclomatic_complexity"] == 3
    assert f.metrics["loc_code_and_comment"] == 1
    assert totals["loc_comments"] == 1
    assert list(f.metrics) == FUNCTION_FEATURES


def test_c_family_halstead_ignores_comments():
    a = c_family_halstead("x = y + 1; /* z + w */")
    b = c_family_halstead("x = y + 1;")
    assert a == b and b["halstead_N2"] == 3


def test_language_detection_and_ignores():
    assert detect_language("a/b.PY") == "python"
    assert detect_language("app.min.js") is None
    assert detect_language("README.md") is None
    assert is_ignored("node_modules/x/y.js") and is_ignored(".git/hooks/a.py")
    assert not is_ignored("src/app.py")


# ------------------------------------------------------------------ extractor
def test_extractor_on_sample_project():
    res = MetricExtractor().extract(SAMPLE)
    assert res.languages == {"python": 4, "java": 1, "c": 1, "javascript": 1}
    paths = {f.path for f in res.files}
    assert "inventory/pricing.py" in paths
    pricing = next(f for f in res.files if f.path == "inventory/pricing.py")
    assert pricing.summary["max_cc"] >= 20
    assert {r["unit"] for r in res.class_rows()} >= {"Product", "PerishableProduct", "Order"}
    assert all(f.partial for f in res.files if f.language != "python")


def test_extractor_skips_broken_and_ignored_but_continues(tmp_path):
    write(tmp_path, "ok.py", "def f():\n    return 1\n")
    write(tmp_path, "bad.py", "def f(:\n")
    write(tmp_path, "node_modules/lib.js", "function z(){}")
    write(tmp_path, "notes.txt", "hello")
    res = MetricExtractor().extract(tmp_path)
    assert [f.path for f in res.files] == ["ok.py"]
    reasons = {s["path"]: s["reason"] for s in res.skipped}
    assert reasons["bad.py"].startswith("parse error")
    assert reasons["notes.txt"] == "unsupported language"
    assert "node_modules/lib.js" not in reasons


def test_extractor_error_cases(tmp_path):
    with pytest.raises(EmptyRepositoryError):
        MetricExtractor().extract(tmp_path)
    write(tmp_path, "a.md", "# hi")
    with pytest.raises(UnsupportedLanguageError):
        MetricExtractor().extract(tmp_path)
    write(tmp_path, "b.py", "def f(:\n")
    with pytest.raises(EmptyRepositoryError, match="b.py"):
        MetricExtractor().extract(tmp_path)


def test_extractor_file_limit_warns(tmp_path):
    for i in range(5):
        write(tmp_path, f"m{i}.py", f"def f{i}():\n    return {i}\n")
    res = MetricExtractor(max_files=3).extract(tmp_path)
    assert len(res.files) == 3 and "only the first 3" in res.warnings[0]

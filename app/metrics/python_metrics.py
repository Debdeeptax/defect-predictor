"""Python analysis: function-level (NASA-style) metrics + raw class facts for OO metrics.

Uses `ast` for structure, `tokenize` for line classes and Halstead tokens, radon for
McCabe complexity and the maintainability index. Source is parsed/compiled, never executed.
"""
from __future__ import annotations

import ast
import builtins
import dis
import io
import tokenize
from dataclasses import dataclass, field
from types import CodeType

from radon.complexity import cc_visit
from radon.metrics import mi_visit
from radon.visitors import ComplexityVisitor

from app.metrics.halstead import PY_KEYWORDS, PY_LITERAL_KEYWORDS, HalsteadCounter
from app.ml.features import complete_function_features

SKIP_TOKENS = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
               tokenize.DEDENT, tokenize.ENDMARKER, tokenize.ENCODING}
BUILTIN_NAMES = set(dir(builtins))


@dataclass
class LineInfo:
    code: bool = False
    comment: bool = False
    doc: bool = False


@dataclass
class FunctionUnit:
    name: str
    qualname: str
    start: int
    end: int
    metrics: dict[str, float]


@dataclass
class MethodFacts:
    name: str
    cc: int
    bytecode: int
    fields: set[str] = field(default_factory=set)
    calls: set[str] = field(default_factory=set)

    @property
    def is_public(self) -> bool:
        n = self.name
        return not n.startswith("_") or (n.startswith("__") and n.endswith("__"))


@dataclass
class ClassFacts:
    name: str
    qualname: str
    file: str
    start: int
    end: int
    bases: list[str]
    methods: list[MethodFacts]
    class_attrs: set[str]
    referenced: set[str]  # type-like names this class uses (for Ce / CBO)


@dataclass
class PythonFileAnalysis:
    functions: list[FunctionUnit]
    classes: list[ClassFacts]
    totals: dict[str, float]


# ---------------------------------------------------------------- helpers
def _tokens(source: str):
    return list(tokenize.generate_tokens(io.StringIO(source).readline))


def _line_info(tokens, n_lines: int) -> dict[int, LineInfo]:
    info = {i: LineInfo() for i in range(1, n_lines + 1)}
    logical: list[tokenize.TokenInfo] = []
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            info.setdefault(tok.start[0], LineInfo()).comment = True
            continue
        if tok.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
            _flush_logical(logical, info)
            logical = []
            continue
        if tok.type in SKIP_TOKENS:
            continue
        logical.append(tok)
    _flush_logical(logical, info)
    return info


def _flush_logical(toks, info):
    if not toks:
        return
    only_strings = all(t.type == tokenize.STRING for t in toks)
    for t in toks:
        for ln in range(t.start[0], t.end[0] + 1):
            li = info.setdefault(ln, LineInfo())
            if only_strings:
                li.doc = True
            else:
                li.code = True


def _loc_metrics(info: dict[int, LineInfo], start: int, end: int) -> dict[str, float]:
    exe = comments = blank = both = 0
    for ln in range(start, end + 1):
        li = info.get(ln, LineInfo())
        if li.code and li.comment:
            both += 1
        elif li.code:
            exe += 1
        elif li.comment or li.doc:
            comments += 1
        else:
            blank += 1
    return {"loc_total": float(end - start + 1), "loc_executable": float(exe),
            "loc_comments": float(comments), "loc_blank": float(blank),
            "loc_code_and_comment": float(both)}


def _halstead(tokens, start: int, end: int) -> dict[str, float]:
    c = HalsteadCounter()
    for tok in tokens:
        if tok.type in SKIP_TOKENS or not (start <= tok.start[0] <= end):
            continue
        if tok.type == tokenize.NAME:
            if tok.string in PY_LITERAL_KEYWORDS:
                c.add_operand(tok.string)
            elif tok.string in PY_KEYWORDS:
                c.add_operator(tok.string)
            else:
                c.add_operand(tok.string)
        elif tok.type in (tokenize.NUMBER, tokenize.STRING):
            c.add_operand(tok.string)
        elif tok.type == tokenize.OP:
            c.add_operator(tok.string)
        elif tok.type == getattr(tokenize, "FSTRING_START", -1):
            c.add_operand(tok.string)
    return c.base()


def _function_nodes(tree: ast.Module):
    """Module-level functions and methods (any class nesting depth); nested functions
    inside functions belong to their parent unit."""
    out = []

    def walk(body, prefix, in_class):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((node, f"{prefix}{node.name}", in_class))
            elif isinstance(node, ast.ClassDef):
                walk(node.body, f"{prefix}{node.name}.", True)
            elif isinstance(node, (ast.If, ast.Try, ast.With)):  # conditional defs
                for attr in ("body", "orelse", "finalbody", "handlers"):
                    sub = getattr(node, attr, None) or []
                    walk([n for h in sub for n in (h.body if isinstance(h, ast.ExceptHandler)
                                                   else [h])], prefix, in_class)
    walk(tree.body, "", False)
    return out


def _cc_by_line(source: str) -> dict[int, int]:
    result: dict[int, int] = {}

    def add(blocks):
        for b in blocks:
            if hasattr(b, "methods"):  # radon Class
                add(b.methods)
            else:
                result.setdefault(b.lineno, b.complexity)
    add(cc_visit(source))
    return result


def _code_objects(code: CodeType):
    yield code
    for const in code.co_consts:
        if isinstance(const, CodeType):
            yield from _code_objects(const)


def _bytecode_sizes(tree: ast.Module, filename: str) -> dict[tuple[str, int], int]:
    """(function name, first line) -> instruction count incl. nested code (comprehensions,
    lambdas). Python analogue of ckjm's bytecode-based LOC."""
    try:
        module_code = compile(tree, filename, "exec", dont_inherit=True)
    except (SyntaxError, ValueError):
        return {}
    sizes: dict[tuple[str, int], int] = {}
    for co in _code_objects(module_code):
        if co is module_code:
            continue
        total = sum(sum(1 for i in dis.get_instructions(c) if i.opname not in ("RESUME", "CACHE"))
                    for c in _code_objects(co))
        sizes.setdefault((co.co_name, co.co_firstlineno), total)
    return sizes


def _imported_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names if a.name != "*")
    return names


def _base_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    if isinstance(expr, ast.Subscript):  # Generic[T]
        return _base_name(expr.value)
    return None


def _call_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


# ---------------------------------------------------------------- main entry
def analyse_python(source: str, rel_path: str) -> PythonFileAnalysis:
    """Raises SyntaxError / tokenize.TokenError / ValueError for unparseable files."""
    tree = ast.parse(source, filename=rel_path)
    tokens = _tokens(source)
    lines = source.splitlines()
    info = _line_info(tokens, len(lines))
    cc_map = _cc_by_line(source)
    bc_sizes = _bytecode_sizes(tree, rel_path)
    imported = _imported_names(tree)

    functions: list[FunctionUnit] = []
    for node, qual, _ in _function_nodes(tree):
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        end = node.end_lineno or node.lineno
        cc = cc_map.get(node.lineno) or ComplexityVisitor.from_ast(node).complexity or 1
        base = {**_loc_metrics(info, start, end), **_halstead(tokens, start, end),
                "cyclomatic_complexity": float(cc), "branch_count": float(2 * cc - 1)}
        functions.append(FunctionUnit(node.name, qual, start, end,
                                      complete_function_features(base)))

    if not functions and lines:
        # Script-style module: score the whole file as one unit so it still gets a risk.
        cc = max(1, ComplexityVisitor.from_code(source).complexity)
        base = {**_loc_metrics(info, 1, len(lines)), **_halstead(tokens, 1, len(lines)),
                "cyclomatic_complexity": float(cc), "branch_count": float(2 * cc - 1)}
        functions.append(FunctionUnit("<module>", "<module>", 1, len(lines),
                                      complete_function_features(base)))

    classes = [_class_facts(node, qual, rel_path, cc_map, bc_sizes, imported)
               for node, qual in _class_nodes(tree)]

    try:
        mi = float(mi_visit(source, multi=True))
    except Exception:
        mi = 0.0
    totals = {**_loc_metrics(info, 1, max(1, len(lines))), "maintainability_index": round(mi, 2)}
    return PythonFileAnalysis(functions, classes, totals)


def _class_nodes(tree: ast.Module):
    out = []

    def walk(body, prefix):
        for node in body:
            if isinstance(node, ast.ClassDef):
                out.append((node, f"{prefix}{node.name}"))
                walk(node.body, f"{prefix}{node.name}.")
    walk(tree.body, "")
    return out


def _class_facts(node: ast.ClassDef, qual: str, rel_path: str, cc_map, bc_sizes,
                 imported: set[str]) -> ClassFacts:
    method_nodes = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    method_names = {m.name for m in method_nodes}
    methods: list[MethodFacts] = []
    for m in method_nodes:
        self_name = m.args.args[0].arg if m.args.args else "self"
        fields, calls = set(), set()
        for sub in ast.walk(m):
            if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                    and sub.value.id in (self_name, "cls")):
                fields.add(sub.attr)
            elif isinstance(sub, ast.Call):
                name = _call_name(sub)
                if name:
                    calls.add(name)
        cc = cc_map.get(m.lineno) or ComplexityVisitor.from_ast(m).complexity or 1
        size = bc_sizes.get((m.name, m.lineno))
        if size is None:  # decorated defs report the first decorator line as co_firstlineno
            first = min([m.lineno] + [d.lineno for d in m.decorator_list])
            size = next((v for (n, ln), v in bc_sizes.items()
                         if n == m.name and first <= ln <= m.lineno), None)
        if size is None:  # compile failed: rough estimate from source lines
            size = 3 * max(1, (m.end_lineno or m.lineno) - m.lineno)
        methods.append(MethodFacts(m.name, int(cc), int(size), fields - method_names, calls))

    class_attrs = set()
    for n in node.body:
        if isinstance(n, ast.Assign):
            class_attrs.update(t.id for t in n.targets if isinstance(t, ast.Name))
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            class_attrs.add(n.target.id)

    referenced = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            referenced.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            root = sub
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                referenced.add(root.id)
    referenced -= BUILTIN_NAMES | {node.name, "self", "cls"}
    # Keep only names that can denote other types: imports or capitalised identifiers.
    referenced = {r for r in referenced if r in imported or r[:1].isupper()}

    bases = [b for b in (_base_name(e) for e in node.bases) if b and b != "object"]
    return ClassFacts(node.name, qual, rel_path, node.lineno, node.end_lineno or node.lineno,
                      bases, methods, class_attrs, referenced)

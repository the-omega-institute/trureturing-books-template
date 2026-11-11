"""Formulas in the PDF are set the way TeX sets them (and KaTeX, in the HTML edition).

Pandoc's Typst writer and Typst itself lose spaces, classes, sizes and groups on the way from TeX;
tools/filters/typst-compat.lua restores them. These tests send TeX through the real chain (macros, reader, Lua
filters) and measure what Typst lays out, with the theme imported the way the generated main.typ imports it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from tbook import mathrender
from tbook import pandoc as tp
from tbook.model import load_edition
from test_pandoc import fixture_site, have_pandoc, have_typst, make_book

MU = 1 / 18  # em


def typst_code(formulas: list[str], display: bool = False) -> list[str]:
    """The Typst code the PDF chain writes for each TeX formula (given without the dollar signs)."""
    d = "$$" if display else "$"
    md = mathrender.newcommands() + "\n\n" + "\n\n".join(f"FORMULA{i:04d} {d}{f}{d}" for i, f in enumerate(formulas))
    args = [tp.pandoc_path(), "-f", tp.READER, "-t", "typst", "--wrap", "none", *tp._filter_meta("en"), *tp._filters()]
    out = subprocess.run(args, input=md + "\n", capture_output=True, text=True, check=True).stdout
    parts = re.split(r"FORMULA(\d{4})", out)
    codes = {int(parts[k]): parts[k + 1].strip() for k in range(1, len(parts), 2)}
    return [codes[i] for i in range(len(formulas))]


@unittest.skipUnless(have_pandoc() and have_typst(), "pandoc and typst are required")
class PdfMathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tbook-pdf-math-"))
        book = make_book(cls.tmp)
        ed = book.edition("en")
        cls.stage = tp.typst_source(fixture_site(), book, ed, load_edition(ed), None,
                                    stage_dir=cls.tmp / "stage").dir

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def query(self, source: str) -> list:
        import typst

        (self.stage / "main.typ").write_text(source, encoding="utf-8")
        return json.loads(typst.query(
            str(self.stage / "main.typ"), "metadata", field="value", root=str(self.stage),
            font_paths=[str(p) for p in tp.font_dirs()], sys_inputs={"tr-variant": "print"},
        ))

    def widths(self, formulas: dict[str, str], display: bool = False, typst: dict[str, str] | None = None
               ) -> dict[str, float]:
        """Widths in em of TeX formulas as the PDF sets them (and of reference Typst code, given as is)."""
        names = list(formulas)
        codes = dict(zip(names, typst_code([formulas[n] for n in names], display)))
        for name, code in codes.items():
            self.assertTrue(code.startswith("$"), f"{formulas[name]!r} was not converted: {code!r}")
        codes.update(typst or {})
        rows = "\n".join(
            f"#context [#metadata((name: {json.dumps(name)}, w: measure({code}).width / 1em.to-absolute()))]"
            for name, code in codes.items())
        values = self.query('#import "/_theme/typst/book.typ": *\n#show: tr-book\n' + rows + "\n")
        return {v["name"]: v["w"] for v in values if isinstance(v, dict) and "name" in v}

    def test_utf8_formulas_do_not_depend_on_ctype_locale(self):
        # macOS classifies some UTF-8 bytes as letters in en_US.UTF-8; Linux's C.UTF-8 does not.
        # Fractions and bars introduce private-use markers, which must remain whole code points too.
        formulas = [r"\frac{x}{2}", r"\lvert x\rvert", r"\bigl\langle x\bigr\rangle",
                    r"\text{café 中文}", r"\frac{α}{β}"]
        with patch.dict(os.environ, {"LC_ALL": "C"}):
            expected = typst_code(formulas)
        for locale in ("C.UTF-8", "en_US.UTF-8"):
            with self.subTest(locale=locale), patch.dict(os.environ, {"LC_ALL": locale}):
                self.assertEqual(typst_code(formulas), expected)

    def test_explicit_spaces_have_their_tex_width(self):
        spaces = {r"\,": 3, r"\:": 4, r"\;": 5, r"\!": -3, r"\quad": 18, r"\qquad": 36, r"\enspace": 9,
                  r"\thinspace": 3, r"\medspace": 4, r"\thickspace": 5, r"\negthinspace": -3,
                  r"\hspace{0.5em}": 9, r"\mkern-3mu": -3, r"\mskip 6mu": 6, r"\kern1em": 18}
        w = self.widths({"none": "x x", **{tex: f"x {tex} x" for tex in spaces}})
        for tex, mu in spaces.items():
            with self.subTest(space=tex):
                self.assertAlmostEqual(w[tex] - w["none"], mu * MU, delta=0.01)

    def test_explicit_space_adds_to_the_automatic_space(self):
        # In Typst h() replaces the space of a relation, an operator or a comma next to it.
        pairs = {
            r"a \;=\; b": ("a = b", 10), r"a,\; b": ("a, b", 5), r"a \,\cdot\, b": (r"a \cdot b", 6),
            r"a, \quad b": ("a, b", 18), r"\sum\, x": (r"\sum x", 3),
            # a sign after a space is unary or binary as it is without the space
            r"a =\; -x": ("a = -x", 5), r"a,\ -x": ("a, -x", 4), r"M \;- N": ("M - N", 5),
            r"(\, -x)": ("(-x)", 3),
            # nothing is set between an operator and its bracket
            r"\Tr\,(\rho)": (r"\Tr(\rho)", 3),
        }
        formulas = {}
        for spaced, (plain, _) in pairs.items():
            formulas[spaced], formulas[plain] = spaced, plain
        w = self.widths(formulas)
        for spaced, (plain, mu) in pairs.items():
            with self.subTest(formula=spaced):
                self.assertAlmostEqual(w[spaced] - w[plain], mu * MU, delta=0.01)
        # \! before \left( only cancels the thin space TeX puts there; Typst has none.
        w = self.widths({"a": r"\exp\!\left(\frac{x}{2}\right)", "b": r"\exp\left(\frac{x}{2}\right)"})
        self.assertAlmostEqual(w["a"], w["b"], delta=0.01)

    def test_blanks_in_the_source_set_nothing(self):
        # TeX ignores blanks in math. Typst keeps them next to bars, text and boxes.
        pairs = [
            (r"\lvert \psi \rangle \langle \psi \rvert", r"\lvert\psi\rangle\langle\psi\rvert"),
            (r"\lvert x \rvert ^2 + | y |", r"\lvert x\rvert^2+|y|"),
            (r"\Tr ( \rho A )", r"\Tr(\rho A)"),
            (r"\operatorname{rank} A", r"\operatorname{rank}A"),
            (r"f \bigl( x \bigr) + \Bigl\{ y \Bigr\}", r"f\bigl(x\bigr)+\Bigl\{y\Bigr\}"),
            (r"a \text{b} c", r"a\text{b}c"),
            (r"\langle a \mid b \rangle \| c \|", r"\langle a\mid b\rangle\|c\|"),
            (r"u' ^2 + \boxed{x} y", r"u'^2+\boxed{x}y"),
        ]
        formulas = {}
        for k, (blanks, tight) in enumerate(pairs):
            formulas[f"blanks{k}"], formulas[f"tight{k}"] = blanks, tight
        w = self.widths(formulas, typst={"bar": "$bar.v$", "x": "$x$", "Tr": '$upright("Tr")$', "arg": "$(rho)$"})
        for k, (blanks, _) in enumerate(pairs):
            with self.subTest(formula=blanks):
                self.assertAlmostEqual(w[f"blanks{k}"], w[f"tight{k}"], delta=0.005)
        w.update(self.widths({"abs": r"\lvert x\rvert", "trace": r"\Tr(\rho)"}))
        self.assertAlmostEqual(w["abs"], w["x"] + 2 * w["bar"], delta=0.02)
        self.assertAlmostEqual(w["trace"], w["Tr"] + w["arg"], delta=0.02)   # "Tr(ρ)", not "Tr (ρ)"

    def test_double_bars_are_delimiters(self):
        w = self.widths({
            "norm": r"\norm{u}", "bars": r"\|u\|", "sized": r"\left\| u \right\|", "squared": r"\norm{u}^2",
            "equation": r"\norm{u} = 1", "x": "x", "x-equation": "x = 1", "u": "u",
            "lone": r"P(a \| b)", "apart": "P(a b)",
        }, typst={"bar": "$bar.v.double$"})
        self.assertAlmostEqual(w["norm"], w["u"] + 2 * w["bar"], delta=0.05)   # no relation space inside
        self.assertAlmostEqual(w["bars"], w["norm"], delta=0.005)
        self.assertAlmostEqual(w["sized"], w["norm"], delta=0.005)
        self.assertGreater(w["squared"], w["norm"] + 0.3)                      # the exponent stands beside the bar
        self.assertAlmostEqual(w["equation"] - w["norm"], w["x-equation"] - w["x"], delta=0.01)
        self.assertAlmostEqual(w["lone"] - w["apart"], w["bar"], delta=0.05)   # a bar without a partner is ordinary

    def test_sized_delimiters_take_room_and_know_their_side(self):
        codes = typst_code([r"\bigl( x \bigr)", r"a \bigm| b", r"\Bigl\langle x \Bigr\rangle", r"\big\| u \big\|"])
        for code in codes:
            self.assertTrue(code.startswith("$"), code)
            self.assertNotIn("#scale", code)
        self.assertIn('class("opening", stretch(paren.l, size: #120%))', codes[0])
        self.assertIn('class("relation", stretch(bar.v, size: #120%))', codes[1])
        self.assertIn('class("closing", stretch(chevron.r, size: #180%))', codes[2])
        self.assertIn('class("normal", stretch(bar.v.double, size: #120%))', codes[3])
        w = self.widths({"rel": r"a \bigm| b", "ord": r"a \big| b", "open": r"f\bigl(x\bigr)", "plain": "f(x)"})
        self.assertAlmostEqual(w["rel"] - w["ord"], 10 * MU, delta=0.01)
        self.assertLess(w["open"] - w["plain"], 0.4)                            # bigger brackets, no word spaces

    def test_groups_keep_their_size_class_and_extent(self):
        w = self.widths({
            "frac": r"\frac{abc}{def}", "tfrac": r"\tfrac{abc}{def}", "binom": r"\binom{abc}{def}",
            "tbinom": r"\tbinom{abc}{def}",
        }, display=True)
        self.assertLess(w["tfrac"], 0.85 * w["frac"])
        self.assertLess(w["tbinom"], 0.9 * w["binom"])
        w = self.widths({
            "dfrac": r"\dfrac{abc}{def}", "frac": r"\frac{abc}{def}",
            "binary": r"a \mathbin{\text{++}} b", "text": r"a \text{++} b",
            "relation": r"a \mathrel{R} b", "letters": r"a R b",
            "long": r"a \xrightarrow{abcdefgh} b", "short": r"a \xrightarrow{a} b",
            "iff": r"a \iff b", "arrow": r"a \Longleftrightarrow b", "short-arrow": r"a \Leftrightarrow b",
            "pmod": r"a \pmod{n}", "bmod": r"a \bmod n", "mod": r"a \mathrm{mod} n", "paren": r"a (\mathrm{mod} n)",
            "middle": r"\left\langle a \middle| b \right\rangle", "bra-ket": r"\langle a | b \rangle",
        })
        self.assertGreater(w["dfrac"], 1.15 * w["frac"])
        self.assertAlmostEqual(w["binary"] - w["text"], 8 * MU, delta=0.01)
        self.assertAlmostEqual(w["relation"] - w["letters"], 10 * MU, delta=0.01)
        self.assertGreater(w["long"], w["short"] + 1.5)                          # the arrow grows with its label
        self.assertAlmostEqual(w["iff"] - w["arrow"], 10 * MU, delta=0.01)       # \iff brings its thick spaces
        self.assertGreater(w["arrow"], w["short-arrow"] + 0.3)                   # and is the long arrow
        self.assertAlmostEqual(w["pmod"] - w["paren"], 14 * MU, delta=0.01)      # 8mu before "(", 6mu after "mod"
        self.assertAlmostEqual(w["bmod"] - w["mod"], 10 * MU, delta=0.01)
        self.assertAlmostEqual(w["middle"], w["bra-ket"], delta=0.05)            # no space around \middle|
        codes = typst_code([r"\left. \frac{df}{dt} \right|_{t=0}", r"\left\{ \frac{a}{b} \right.",
                            r"a \overset{x}{B} c", r"\{ \frac{a}{b} \}"])
        self.assertIn("lr(frac(d f, d t) bar.v)_(t = 0)", codes[0])
        self.assertIn("lr(brace.l frac(a , b))", codes[1])
        self.assertIn("limits(B)^x", codes[2])
        self.assertIn("brace.l frac(a , b) brace.r", codes[3])                   # not sized like \left\{…\right\}
        self.widths({str(k): tex for k, tex in enumerate(
            [r"\left. \frac{df}{dt} \right|_{t=0}", r"\left\{ \frac{a}{b} \right.", r"a \overset{x}{B} c"])})

    def test_fractions_keep_their_structure(self):
        # The writer's "a / b" is read from the left by Typst: 1 / 1 / 2 would be (1/1)/2, a / b^2 a/(b²).
        codes = typst_code([r"\frac{1}{\frac{1}{2}}", r"\frac{\frac{a}{b}}{c}", r"\frac{a}{b}^2",
                            r"\frac{\left(a+b\right)}{2}", r"\tfrac{1}{2}", r"\frac{a+b}{c+d}", "x/y"])
        self.assertIn("frac(1, frac(1 , 2))", codes[0])
        self.assertIn("frac(frac(a , b), c)", codes[1])
        self.assertIn("frac(a , b)^2", codes[2])
        self.assertIn("frac((a + b) , 2)", codes[3])   # the parentheses the author wrote are kept
        self.assertIn("inline(frac(1 , 2))", codes[4])
        self.assertIn("frac(a + b, c + d)", codes[5])
        self.assertNotIn("frac", codes[6])             # a slash the author wrote stays a slash
        w = self.widths({"over": r"\frac{aaaa}{\frac{b}{c}}", "under": r"\frac{\frac{aaaa}{b}}{c}"}, display=True)
        self.assertGreater(w["over"], w["under"] + 0.1)   # the numerator aaaa one size larger than in the other

    def test_scripts_of_relations_stand_beside_them(self):
        # Typst sets a script on a relation above or below it, as for a limit: E →_L E with L under the arrow.
        codes = typst_code([r"a \to_L b", r"a =_x b", r"a \simeq_{k} b", r"\lim_{x \to 0} f",
                            r"\sum\nolimits_{k} a", r"\int\limits_0^1 f", r"a \stackrel{f}{\to} b",
                            r"a \xrightarrow{f} b", r"a \Longrightarrow_k b"])
        for code, expected in zip(codes, ("scripts(arrow.r)_L", "scripts(=)_x", "scripts(tilde.eq)_k",
                                          "lim_(x arrow.r 0)", "scripts(sum)_k", "limits(integral)_0^1",
                                          "limits(arrow.r)^f", "stretch(arrow.r)^f",
                                          "scripts(arrow.r.double.long)_k")):
            self.assertIn(expected, code)
        w = self.widths({"beside": r"E \to_{LLLL} E", "plain": r"E \to E"})
        self.assertGreater(w["beside"], w["plain"] + 1.0)

    def test_symbols_the_writer_gets_wrong(self):
        codes = typst_code([r"(a \gg i)\,\&\,1", r"G \succeq 0 \preceq H", r"a \succcurlyeq b",
                            r"E_a \backslash E_b", r"a \longrightarrow b \longmapsto c"])
        self.assertIn("amp", codes[0])                 # a bare & would be an alignment point: nothing printed
        self.assertIn("succ.eq", codes[1])
        self.assertIn("prec.eq", codes[1])
        self.assertIn("succ.curly.eq", codes[2])
        self.assertIn('class("normal", backslash)', codes[3])
        self.assertIn("arrow.r.long", codes[4])
        self.assertIn("arrow.r.long.bar", codes[4])
        self.assertIn("square.stroked", typst_code([r"U_\square"])[0])
        self.assertNotIn("tiny", typst_code([r"U_\square"])[0])
        self.widths({str(k): tex for k, tex in enumerate(
            [r"(a \gg i)\,\&\,1", r"G \succeq 0 \preceq H", r"E_a \backslash E_b", r"a \longmapsto c"])})

    def test_operators_without_an_operand_are_ordinary_symbols(self):
        # TeX sets a binary operator as an ordinary symbol when an operand is missing on either side.
        w = self.widths({
            "ket": r"|+\rangle", "ket-ref": r"\lvert{+}\rangle", "script": r"\rho_{|+}", "script-ref": r"\rho_{|{+}}",
            "prefix": r"= \star I", "none": "= I", "star": r"\star", "binary": r"x \star y", "operands": "x y",
            "slot": r"\langle \cdot, \cdot \rangle", "slot-ref": r"\langle {\cdot}, {\cdot} \rangle",
            "minus": "a = - b", "minus-ref": "a = {-} b", "sum": "a - b", "sum-none": "a b", "sign": "-",
        })
        self.assertAlmostEqual(w["ket"], w["ket-ref"], delta=0.01)
        self.assertAlmostEqual(w["script"], w["script-ref"], delta=0.01)
        self.assertAlmostEqual(w["prefix"] - w["none"], w["star"], delta=0.01)             # = ⋆I, not = ⋆ I
        self.assertAlmostEqual(w["binary"] - w["operands"], w["star"] + 8 * MU, delta=0.01)
        self.assertAlmostEqual(w["slot"], w["slot-ref"], delta=0.01)
        self.assertAlmostEqual(w["minus"], w["minus-ref"], delta=0.01)
        self.assertAlmostEqual(w["sum"] - w["sum-none"], w["sign"] + 8 * MU, delta=0.01)   # a − b stays binary

    def test_dots_and_aligned_columns_are_spaced(self):
        w = self.widths({"dots": r"P \cdots P", "none": "P P", "glyph": r"\cdots", "sum": r"a + \cdots + b",
                         "sum-ref": r"a + {\cdots} + b"})
        self.assertAlmostEqual(w["dots"] - w["none"], w["glyph"] + 6 * MU, delta=0.01)     # a thin space each side
        self.assertAlmostEqual(w["sum"], w["sum-ref"], delta=0.01)                         # none next to an operator
        two, one = typst_code([r"\begin{aligned} a &= b, & c &= d, \\ aaa &= bbb, & ccc &= ddd. \end{aligned}",
                               r"\begin{aligned} a &= b \\ c &= d \end{aligned}"], display=True)
        self.assertEqual(two.count("#box(width: 1em)/**/&"), 2)                            # between the column pairs
        self.assertNotIn("#box(width: 1em)", one)
        self.widths({"two": r"\begin{aligned} a &= b, & c &= d, \\ aaa &= bbb, & ccc &= ddd. \end{aligned}"},
                    display=True)

    def test_matrices_outside_left_right(self):
        environments = ["smallmatrix", "matrix", "vmatrix", "Vmatrix"]
        formulas = [rf"\begin{{{e}}} 1 & -1 \\ -1 & 1 \end{{{e}}}" for e in environments]
        formulas += [r"\begin{array}{cc} 1 & -1 \\ -1 & 1 \end{array}",
                     r"\bigl(\begin{smallmatrix} 1 & -1 \\ -1 & 1 \end{smallmatrix}\bigr)"]
        codes = typst_code(formulas)
        for code in codes:
            self.assertIn("mat(", code)
            self.assertIn("delim: ", code)
            self.assertNotIn("\\\n", code)        # rows inside mat(…), not line breaks of the formula
        self.assertIn("script(mat(", codes[0])
        self.assertIn("delim: #none", codes[0])
        self.assertIn("mat(delim: #none", codes[1])
        self.assertIn("mat(delim: bar.v,", codes[2])
        self.assertIn("mat(delim: bar.v.double,", codes[3])
        self.assertIn("mat(delim: #none", codes[4])
        w = self.widths({"small": formulas[0], "matrix": formulas[1], "bars": formulas[2], "double": formulas[3]})
        self.assertLess(w["small"], 0.85 * w["matrix"])
        self.assertGreater(w["double"], w["bars"])
        w = self.widths({"row": r"\begin{pmatrix} a & b \end{pmatrix}", "cell": r"\begin{pmatrix} a \end{pmatrix}",
                         "b": "b"})
        self.assertAlmostEqual(w["row"] - w["cell"] - w["b"], 1.0, delta=0.15)             # 1em between columns, not 0.5em

    def test_text_keeps_escaped_characters(self):
        codes = typst_code([r"\text{a \& b}", r"\text{100\% sure}", r"\texttt{left \^{} right}", r"\text{a\;b}"])
        self.assertIn('"a & b"', codes[0])
        self.assertIn('"100% sure"', codes[1])
        self.assertIn('"left ^ right"', codes[2])
        self.assertRegex(codes[3], r'"a".*0\.2778em.*"b"')

    def test_fonts_and_accents_survive_the_theme(self):
        # The theme is imported whole into the document: a name it defines replaces Typst's math function of
        # that name (accent, mono), and the formula prints the theme's value.
        w = self.widths({
            "mono": r"\mathtt{mmmm}", "m": r"\mathtt{m}", "wide": r"\widetilde{AB}", "base": "AB",
            "sans": r"\mathsf{T}", "dots": r"\hat{a_i} + \vv{j}", "arrow": r"\overrightarrow{AB}",
        }, typst={"upright-sans": "$upright(sans(T))$"})
        self.assertAlmostEqual(w["mono"], 4 * w["m"], delta=0.02)
        self.assertGreater(w["m"], 0.45)
        self.assertAlmostEqual(w["wide"], w["base"], delta=0.15)
        self.assertAlmostEqual(w["arrow"], w["base"], delta=0.25)
        self.assertAlmostEqual(w["sans"], w["upright-sans"], delta=0.001)       # \mathsf is upright
        values = self.query(
            '#import "/_theme/typst/book.typ" as theme\n'
            '#let taken = dictionary(math).keys() + dictionary(sym).keys() + ("h", "box", "scale", "hide", "text", '
            '"sym", "math", "std", "none")\n'
            '#metadata(dictionary(theme).keys().filter(name => name in taken))\n')
        self.assertEqual(values, [[]], "theme/typst/book.typ defines names that Typst's math uses")

    def test_nothing_internal_reaches_the_page(self):
        # Facts the writer loses travel through it as private-use characters and coded widths. Whatever the
        # construct around them, none may be left in the result, and the result must compile.
        formulas = [
            r"\boxed{\frac{a}{b}}", r"\boxed{a \;=\; b}", r"\boxed{A \cap B}", r"\boxed{\lvert x\rvert}",
            r"a \phantom{\frac{a}{b}} b", r"\begin{aligned} a &= b \\ \phantom{a} &\;\le c \end{aligned}",
            r"a \not\preceq b \not\succeq c", r"a \not\Longrightarrow b", r"a \not\implies b \;\|\; c",
            r"x^\frac{1}{2} + 2^\tfrac{n}{2} + \sqrt\frac{a}{b} + \sqrt[3]\frac{a}{b}",
            r"\operatorname{arg\;max}_x f(x) + \operatorname*{lim\;sup}_x a + \operatorname{a\&b}",
            r"\int f(x) \mathop{}\!\mathrm{d}x", r"f\mathopen{}\left(x\right)\mathclose{}", r"a \mathrel{} b",
            r"\underset{x}{}", r"\frac{a}{} + \frac{}{b} + \binom{n}{}",
            r"f * \text{g} + a * \quad b + (f * \, g)(x) + \text{width} * \text{height}", r"a / \text{b}",
            r"\begin{matrix} a \\ b \end{matrix} + \bigl(\begin{smallmatrix} a \\ b \end{smallmatrix}\bigr)",
            r"\begin{vmatrix} a \\ b \end{vmatrix} + \left(\begin{array}{c} a \\ b \end{array}\right)",
            r"\left\{ \begin{array}{l} x = 1 \\ y = 22 \end{array} \right.",
            r"\left\{\begin{aligned} x &= 1 \\ y &= 2\end{aligned}\right.",
            r"\underset{n}{A}^2 + \overset{\leftrightarrow}{T}_{ij}", r"\sum\nolimits_k a + \limits x",
        ]
        for display in (False, True):
            codes = typst_code(formulas, display)
            for tex, code in zip(formulas, codes):
                with self.subTest(formula=tex, display=display):
                    self.assertTrue(code.startswith("$"), code)
                    self.assertNotRegex(code, "[-]")
                    self.assertNotRegex(code, r"#h\([3-6]\d\d\dem\)")
                    self.assertNotIn("overline(", code)
            self.widths({str(k): tex for k, tex in enumerate(formulas)}, display)

    def test_review_regressions(self):
        codes = dict(zip("abcdefghij", typst_code([
            r"x^\frac{1}{2}", r"\begin{matrix} a \\ b \end{matrix}", r"\operatorname{arg\;max}_x",
            r"P(A \| B) \cdot \frac{P(B)}{P(A)} = P(B \| A)", r"B : \operatorname{Space}(d)",
            r"\underset{n}{A}^2", r"x>0 \iff -x<0", r"P^\perp \;+\; Q", r"\sum_i \; -a_i",
            r"\left\{ \begin{array}{l} x = 1 \\ y = 22 \end{array} \right.",
        ])))
        self.assertIn("x^(frac(1 , 2))", codes["a"])                  # the fraction is the exponent
        self.assertIn("vec(delim: #none, a, b)", codes["b"])          # one column: no parentheses
        self.assertRegex(codes["c"], r'op\("arg.max"\)')            # the name as written, one space
        self.assertNotIn("lr(", codes["d"])                           # two unrelated bars are not a pair
        self.assertIn('op("Space")', codes["e"])                      # a typeset colon is not "delim:"
        self.assertIn("scripts(limits(A)_n)^2", codes["f"])
        self.assertIn('class("unary", -) x', codes["g"])              # a sign after \iff
        self.assertNotIn("unary", codes["h"])                         # binary after a scripted operand
        self.assertIn('class("unary", -) a_i', codes["i"])            # unary after a scripted operator
        self.assertIn("lr(brace.l vec(delim: #none, align: #left, x = 1, y = 22))", codes["j"])
        w = self.widths({"idiom": r"\int f(x) \mathop{}\!\mathrm{d}x", "thin": r"\int f(x)\,\mathrm{d}x",
                         "bars": r"P(A \| B) \frac{P(B)}{P(A)}", "no-bars": r"P(A B) \frac{P(B)}{P(A)}"},
                        typst={"bar": "$bar.v.double$"})
        self.assertAlmostEqual(w["idiom"], w["thin"], delta=0.01)     # the differential keeps its thin space
        self.assertAlmostEqual(w["bars"] - w["no-bars"], w["bar"], delta=0.02)

    def test_malformed_tex_is_left_to_the_writer(self):
        # The filter must not repair what the author did not write: the writer prints the source, as before.
        for tex in (r"\frac{a}{b", r"\frac{a}", r"x \text{abc", r"x^{\frac{a}}", r"\frac1\sqrt{2} \;+\; 1"):
            with self.subTest(formula=tex):
                code = typst_code([tex])[0]
                self.assertNotIn("#box", code)
                self.assertNotIn("frac(", code)
        self.assertIn("frac(pi , 2)", typst_code([r"\frac\pi{2}"])[0])   # valid: a command without arguments

    def test_an_unconvertible_formula_is_left_as_written(self):
        code, fine = typst_code([r"\undefinedcommand{x} \;=\; \lvert y\rvert", r"a \;=\; b"])
        self.assertFalse(code.startswith("$"))
        self.assertIn(r"\\undefinedcommand", code)
        self.assertIn(r"\\;", code)               # the author's source, not the rewritten one
        self.assertNotIn("#box", code)
        self.assertTrue(fine.startswith("$"))


if __name__ == "__main__":
    unittest.main()

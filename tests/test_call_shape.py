"""`call_shape`: Python's argument-binding rules over `ast`, and the calls a test writes to fail."""

from __future__ import annotations

import ast
import unittest

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import call_shape  # noqa: E402


def _shape(signature: str) -> call_shape.Shape:
    return call_shape.shape(ast.parse(f"def f{signature}: pass").body[0].args)


def _call(text: str) -> ast.Call:
    return ast.parse(text, mode="eval").body


class BindTest(unittest.TestCase):
    def test_binding_follows_python(self):
        cases = {
            ("(a, b=1)", "f(1)"): "",
            ("(a, b=1)", "f(1, 2, 3)"): "takes 2 positional arguments but 3 were given",
            ("(a, *rest)", "f(1, 2, 3)"): "",
            ("(a, b)", "f(1, a=2)"): "got multiple values for argument 'a'",
            ("(a, /, b=1)", "f(a=1)"): "got a positional-only argument passed as keyword: 'a'",
            ("(a, /, **kw)", "f(1, a=1)"): "",
            ("(a)", "f(1, c=2)"): "got an unexpected keyword argument 'c'",
            ("(a, **kw)", "f(1, c=2)"): "",
            ("(a, b)", "f(1)"): "missing required positional argument 'b'",
            ("(a, *, t)", "f(1)"): "missing required keyword-only argument 't'",
            ("(a, *, t=1)", "f(1, t=2)"): "",
        }
        for (signature, call), expected in cases.items():
            with self.subTest(signature=signature, call=call):
                self.assertEqual(call_shape.bind(_shape(signature), _call(call)), expected)

    def test_star_arguments_at_the_call_are_unprovable(self):
        for call in ("f(*args)", "f(1, **options)"):
            with self.subTest(call):
                self.assertIsNone(call_shape.bind(_shape("(a, b=1)"), _call(call)))


class ExpectedToFailTest(unittest.TestCase):
    def guarded(self, source: str) -> set[str]:
        tree = ast.parse(source)
        ids = call_shape.expected_to_fail(tree)
        return {ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Call) and id(node) in ids}

    def test_calls_written_to_fail_are_found(self):
        source = (
            "with pytest.raises(TypeError):\n    f(1)\n"
            "self.assertRaises(TypeError, g, h(2))\n"
            "try:\n    k(3)\nexcept (ValueError, TypeError):\n    pass\n"
            "try:\n    m(4)\nexcept:\n    pass\n"
        )
        self.assertEqual(self.guarded(source), {"f(1)", "h(2)", "k(3)", "m(4)"})

    def test_ordinary_calls_are_not(self):
        source = "f(1)\ntry:\n    k(3)\nexcept ValueError:\n    pass\nwith open('x') as handle:\n    g(2)\n"
        self.assertEqual(self.guarded(source), set())


if __name__ == "__main__":
    unittest.main()

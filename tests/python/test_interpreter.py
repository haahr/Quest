"""Unit tests for Quest Runtime Environment and Core Interpreter (bootstrap/python/quest/interpreter.py)."""

import unittest

from quest.interpreter import (
    DIVIDE_BY_ZERO_EXC,
    QuestException,
    QuestRuntimeError,
    RuntimeEnvironment,
    eval_expr,
    eval_program,
)
from quest.pipeline import CompilerOptions, default_pipeline
from quest.runtime import (
    FALSE_VALUE,
    OK_VALUE,
    TRUE_VALUE,
    QBool,
    QChar,
    QInt,
    QReal,
    QString,
    QTuple,
    qvalue_is,
)


def run_quest_code(source: str, env: RuntimeEnvironment | None = None):
    """Helper to parse, typecheck, and evaluate Quest source code."""
    pipeline = default_pipeline()
    opts = CompilerOptions(stop_after="typecheck")
    res = pipeline.execute(source, "<test>", options=opts)
    if not res.success or res.final_artifact is None:
        diags = "\n".join(d.message for d in res.diagnostics)
        raise RuntimeError(f"Compilation failed:\n{diags}")
    return eval_program(res.final_artifact, env)


class TestLiteralEvaluation(unittest.TestCase):
    """Tests for evaluating literal expressions."""

    def test_primitives(self):
        self.assertEqual(run_quest_code("42;"), QInt(42))
        self.assertEqual(run_quest_code("3.14;"), QReal(3.14))
        self.assertEqual(run_quest_code("true;"), TRUE_VALUE)
        self.assertEqual(run_quest_code("false;"), FALSE_VALUE)
        self.assertEqual(run_quest_code("'z';"), QChar("z"))
        self.assertEqual(run_quest_code('"hello";'), QString("hello"))
        self.assertEqual(run_quest_code("ok;"), OK_VALUE)


class TestArithmetic(unittest.TestCase):
    """Tests for integer and real arithmetic, truncation toward zero, and DivideByZero."""

    def test_int_arithmetic(self):
        self.assertEqual(run_quest_code("10 + 20;"), QInt(30))
        self.assertEqual(run_quest_code("50 - 15;"), QInt(35))
        self.assertEqual(run_quest_code("6 * 7;"), QInt(42))

    def test_integer_division_truncation(self):
        # Positive operands
        self.assertEqual(run_quest_code("7 / 2;"), QInt(3))
        self.assertEqual(run_quest_code("7 % 2;"), QInt(1))

        # Negative operands: Cardelli C-style truncation toward zero
        self.assertEqual(run_quest_code("{0 - 7} / 2;"), QInt(-3))
        self.assertEqual(run_quest_code("{0 - 7} % 2;"), QInt(-1))
        self.assertEqual(run_quest_code("7 / {0 - 2};"), QInt(-3))
        self.assertEqual(run_quest_code("7 % {0 - 2};"), QInt(1))

    def test_divide_by_zero_exception(self):
        with self.assertRaises(QuestException) as ctx1:
            run_quest_code("10 / 0;")
        self.assertEqual(ctx1.exception.exc_val.name, "DivideByZero")

        with self.assertRaises(QuestException) as ctx2:
            run_quest_code("10 % 0;")
        self.assertEqual(ctx2.exception.exc_val.name, "DivideByZero")

    def test_real_arithmetic(self):
        self.assertEqual(run_quest_code("1.5 + 2.5;"), QReal(4.0))
        self.assertEqual(run_quest_code("5.0 - 1.25;"), QReal(3.75))
        self.assertEqual(run_quest_code("2.5 * 4.0;"), QReal(10.0))
        self.assertEqual(run_quest_code("9.0 / 2.0;"), QReal(4.5))

        with self.assertRaises(QuestException):
            run_quest_code("1.0 / 0.0;")


class TestRelationalAndEquality(unittest.TestCase):
    """Tests for relational operators and equality predicates."""

    def test_relational(self):
        self.assertEqual(run_quest_code("1 < 2;"), TRUE_VALUE)
        self.assertEqual(run_quest_code("2 <= 2;"), TRUE_VALUE)
        self.assertEqual(run_quest_code("3 > 5;"), FALSE_VALUE)
        self.assertEqual(run_quest_code("5 >= 5;"), TRUE_VALUE)

        # Reals
        self.assertEqual(run_quest_code("1.5 < 2.5;"), TRUE_VALUE)
        # Chars
        self.assertEqual(run_quest_code("'a' < 'b';"), TRUE_VALUE)
        # Strings
        self.assertEqual(run_quest_code('"abc" < "abd";'), TRUE_VALUE)

    def test_equality(self):
        self.assertEqual(run_quest_code("10 is 10;"), TRUE_VALUE)
        self.assertEqual(run_quest_code("10 isnot 20;"), TRUE_VALUE)
        self.assertEqual(run_quest_code("10 is 20;"), FALSE_VALUE)
        self.assertEqual(run_quest_code("10 <> 20;"), TRUE_VALUE)


class TestVariablesAndMutability(unittest.TestCase):
    """Tests for variable bindings, mutation, and scoping."""

    def test_immutable_let(self):
        code = """
        let x = 10;
        let y = 20;
        x + y;
        """
        self.assertEqual(run_quest_code(code), QInt(30))

    def test_mutable_var(self):
        code = """
        let var count = 0;
        count := count + 5;
        count := count * 2;
        count;
        """
        self.assertEqual(run_quest_code(code), QInt(10))

    def test_scoped_blocks(self):
        code = """
        let x = 100;
        let res = begin
            let x = 50;
            x + 5
        end;
        res + x;
        """
        self.assertEqual(run_quest_code(code), QInt(155))


class TestConditionalsAndLogic(unittest.TestCase):
    """Tests for conditionals and short-circuit boolean logic."""

    def test_if_then_else(self):
        self.assertEqual(run_quest_code("if 1 < 2 then 10 else 20 end;"), QInt(10))
        self.assertEqual(run_quest_code("if 2 < 1 then 10 else 20 end;"), QInt(20))

    def test_short_circuit_andif_orif(self):
        # andif should not evaluate right side if left is false
        code_andif = """
        let var evaluated = false;
        let res = {1 > 2} andif {begin evaluated := true; true end};
        evaluated;
        """
        self.assertEqual(run_quest_code(code_andif), FALSE_VALUE)

        # orif should not evaluate right side if left is true
        code_orif = """
        let var evaluated = false;
        let res = {1 < 2} orif {begin evaluated := true; false end};
        evaluated;
        """
        self.assertEqual(run_quest_code(code_orif), FALSE_VALUE)


class TestLoopsAndControlFlow(unittest.TestCase):
    """Tests for while loops, infinite loops with exit, and for loops."""

    def test_while_loop(self):
        code = """
        let var i = 0;
        while i < 5 do
            i := i + 1
        end;
        i;
        """
        self.assertEqual(run_quest_code(code), QInt(5))

    def test_loop_with_exit(self):
        code = """
        let var i = 0;
        loop
            if i is 7 then
                exit
            else
                i := i + 1
            end
        end;
        i;
        """
        self.assertEqual(run_quest_code(code), QInt(7))

    def test_for_upto_inclusive(self):
        code = """
        let var sum = 0;
        for k = 1 upto 5 do
            sum := sum + k
        end;
        sum;
        """
        # 1 + 2 + 3 + 4 + 5 = 15
        self.assertEqual(run_quest_code(code), QInt(15))

    def test_for_downto_inclusive(self):
        code = """
        let var prod = 1;
        for k = 4 downto 1 do
            prod := prod * k
        end;
        prod;
        """
        # 4 * 3 * 2 * 1 = 24
        self.assertEqual(run_quest_code(code), QInt(24))

    def test_for_zero_iterations(self):
        code = """
        let var count = 0;
        for k = 10 upto 5 do
            count := count + 1
        end;
        count;
        """
        self.assertEqual(run_quest_code(code), QInt(0))


class TestExpressionsControlFlowSource(unittest.TestCase):
    """Verifies evaluation of expressions and control flow structures."""

    def test_02_expressions_evaluation(self):
        code = """
        let x = 10;
        let y = 20;
        let sum = x + y * 2;
        let boolVal = {x < y} andif {{x <> 0} orif {y is 20}};
        boolVal;
        """
        self.assertEqual(run_quest_code(code), TRUE_VALUE)

    def test_02_expressions_control_flow_file(self):
        with open("tests/source/02_expressions_control_flow.quest") as f:
            source = f.read()

        source_with_calls = source + "\n" + """
        let r1 = testIf({0 - 5});
        let r2 = testIf(0);
        let r3 = testIf(42);
        """

        env = RuntimeEnvironment.create_root_env()
        run_quest_code(source_with_calls, env)

        self.assertEqual(env.lookup("x"), QInt(10))
        self.assertEqual(env.lookup("y"), QInt(20))
        self.assertEqual(env.lookup("sum"), QInt(50))
        self.assertEqual(env.lookup("boolVal"), TRUE_VALUE)

        # Call results
        self.assertEqual(env.lookup("r1"), QInt(5))
        self.assertEqual(env.lookup("r2"), QInt(0))
        self.assertEqual(env.lookup("r3"), QInt(42))
        self.assertEqual(env.lookup("testLoop"), OK_VALUE)

    def test_recursive_function(self):
        code = """
        let rec fact(n: Int): Int =
            if n <= 1 then
                1
            else
                n * fact(n - 1)
            end;
        fact(5);
        """
        self.assertEqual(run_quest_code(code), QInt(120))


class TestCompoundStructuresAndMutation(unittest.TestCase):
    """Tests for records, tuples, arrays, variants, options, and case expressions."""

    def test_record_creation_and_selection(self):
        code = """
        let p = record x = 10 y = 20 end;
        p.x + p.y;
        """
        self.assertEqual(run_quest_code(code), QInt(30))

    def test_mutable_record_field(self):
        code = """
        let r = record var count = 0 end;
        r.count := r.count + 5;
        r.count := r.count * 3;
        r.count;
        """
        self.assertEqual(run_quest_code(code), QInt(15))

    def test_labeled_tuple_selection(self):
        code = """
        let t = tuple let count = 10 let name = "quest" end;
        t.count;
        """
        self.assertEqual(run_quest_code(code), QInt(10))

    def test_array_indexing_and_mutation(self):
        code = """
        let a = array of 10 20 30 end;
        let v1 = a[1];
        a[1] := 99;
        v1 + a[1];
        """
        self.assertEqual(run_quest_code(code), QInt(119))

    def test_array_repetition(self):
        code = """
        let a = array of(5 42);
        a[0] + a[4];
        """
        self.assertEqual(run_quest_code(code), QInt(84))

    def test_array_out_of_bounds_exception(self):
        code_idx = """
        let a = array of 1 2 end;
        a[5];
        """
        with self.assertRaises(QuestException) as ctx1:
            run_quest_code(code_idx)
        self.assertEqual(ctx1.exception.exc_val.name, "arrayOp.error")

        code_assign = """
        let a = array of 1 2 end;
        a[5] := 10;
        """
        with self.assertRaises(QuestException) as ctx2:
            run_quest_code(code_assign)
        self.assertEqual(ctx2.exception.exc_val.name, "arrayOp.error")

        code_rep_neg = """
        array of({0 - 1} 0);
        """
        with self.assertRaises(QuestException) as ctx3:
            run_quest_code(code_rep_neg)
        self.assertEqual(ctx3.exception.exc_val.name, "arrayOp.error")

    def test_option_and_case(self):
        code = """
        Let Color = Option
            red
            green
            blue with intensity: Int end
        end;

        let c1 = option red of Color end;
        let r1 = case c1
            when red then 1
            when green then 2
            when blue with b: Tuple intensity: Int end then b.intensity
            else 0
        end;

        let c2 = option blue of Color with tuple let intensity = 100 end end;
        let r2 = case c2
            when red then 1
            when green then 2
            when blue with b: Tuple intensity: Int end then b.intensity
            else 0
        end;

        r1 + r2;
        """
        self.assertEqual(run_quest_code(code), QInt(101))

    def test_03_functions_closures_file(self):
        with open("tests/source/03_functions_closures.quest") as f:
            source = f.read()

        env = RuntimeEnvironment.create_root_env()
        run_quest_code(source, env)
        self.assertEqual(env.lookup("res"), QInt(42))

    def test_04_records_variants_options_file(self):
        with open("tests/source/04_records_variants_options.quest") as f:
            source = f.read()

        source_with_call = source + "\n" + """
        let codeRed = colorCode(c);
        """

        env = RuntimeEnvironment.create_root_env()
        run_quest_code(source_with_call, env)

        self.assertEqual(env.lookup("px"), QInt(10))
        self.assertEqual(env.lookup("first"), QInt(1))
        self.assertEqual(env.lookup("codeRed"), QInt(1))


class TestExceptions(unittest.TestCase):
    """Tests for Phase 3.4 Exception definitions, raising, and try-when handling."""

    def test_basic_raise_and_catch(self):
        code = """
        exception E: Ok end;
        let var x = 0;
        try
            raise E end
        when E then
            x := 42;
        end;
        x;
        """
        self.assertEqual(run_quest_code(code), QInt(42))

    def test_raise_with_payload(self):
        code = """
        exception ValExc: Int end;
        let f(dummy: Int): Int = raise ValExc with 50 end;
        let res = try
            f(0)
        when ValExc with p then
            p + 25
        else
            0
        end;
        res;
        """
        self.assertEqual(run_quest_code(code), QInt(75))

    def test_try_else_fallback(self):
        code = """
        exception E1: Ok end;
        exception E2: Ok end;
        let f(dummy: Int): Int = raise E1 end;
        let res = try
            f(0)
        when E2 then
            10
        else
            20
        end;
        res;
        """
        self.assertEqual(run_quest_code(code), QInt(20))

    def test_catch_builtin_divide_by_zero(self):
        code = """
        let res = try
            10 / 0
        when DivideByZero then
            999
        else
            0
        end;
        res;
        """
        self.assertEqual(run_quest_code(code), QInt(999))

    def test_07_exceptions_dynamic_file(self):
        with open("tests/source/07_exceptions_dynamic.quest") as f:
            source = f.read()

        source_with_call = source + "\n" + """
        let r1 = compute(10 2);
        let r2 = compute(10 0);
        """
        env = RuntimeEnvironment.create_root_env()
        run_quest_code(source_with_call, env)

        self.assertEqual(env.lookup("r1"), QInt(5))
        self.assertEqual(env.lookup("r2"), QInt(0))


class TestDynamicAndInspect(unittest.TestCase):
    """Tests for Phase 3.4 Dynamic type boxing and inspect expressions."""

    def test_dynamic_packaging_and_inspect(self):
        code = """
        let d = dynamic(42);
        let res = inspect d
            when Int with n then n + 1
            else 0
        end;
        res;
        """
        self.assertEqual(run_quest_code(code), QInt(43))

    def test_inspect_multiple_branches(self):
        code = """
        let d = dynamic("hello");
        let res = inspect d
            when Int with n then 1
            when String with s then 2
            else 3
        end;
        res;
        """
        self.assertEqual(run_quest_code(code), QInt(2))

    def test_inspect_unmatched_raises_dynamic_error(self):
        code = """
        let d = dynamic(42);
        inspect d
            when String with s then 1
        end;
        """
        with self.assertRaises(QuestException) as cm:
            run_quest_code(code)
        self.assertEqual(cm.exception.exc_val.name, "dynamic.error")


class TestStandardLibraryModules(unittest.TestCase):
    """Verifies Cardelli standard library modules (Phase 3.5)."""

    def test_import_conv_and_tilde(self):
        code = """
        import conv: Conv;
        let pos = conv.int(42);
        let neg = conv.int(0 - 42);
        let posR = conv.real(3.14);
        let negR = conv.real(0.0 - 2.5);
        let b = conv.bool(true);
        let okS = conv.okay();
        tuple pos neg posR negR b okS end;
        """
        val = run_quest_code(code)
        self.assertIsInstance(val, QTuple)
        self.assertEqual(val.elements[0], QString("42"))
        self.assertEqual(val.elements[1], QString("~42"))
        self.assertEqual(val.elements[2], QString("3.14"))
        self.assertEqual(val.elements[3], QString("~2.5"))
        self.assertEqual(val.elements[4], QString("true"))
        self.assertEqual(val.elements[5], QString("ok"))

    def test_import_ascii(self):
        code = """
        import ascii: Ascii;
        let c = ascii.char(65);
        let v = ascii.val(c);
        let bad = try ascii.char(999) when ascii.error then '?' end;
        tuple c v bad end;
        """
        val = run_quest_code(code)
        self.assertIsInstance(val, QTuple)
        self.assertEqual(val.elements[0], QChar("A"))
        self.assertEqual(val.elements[1], QInt(65))
        self.assertEqual(val.elements[2], QChar("?"))

    def test_import_int_op(self):
        code = """
        import int: IntOp;
        let a = int.abs(0 - 100);
        let mn = int.min(5 10);
        let mx = int.max(5 10);
        tuple a mn mx end;
        """
        val = run_quest_code(code)
        self.assertIsInstance(val, QTuple)
        self.assertEqual(val.elements[0], QInt(100))
        self.assertEqual(val.elements[1], QInt(5))
        self.assertEqual(val.elements[2], QInt(10))

    def test_import_real_op(self):
        code = """
        import real: RealOp;
        let fl = real.floor(3.9);
        let rd = real.round(3.2);
        let ab = real.abs(0.0 - 5.5);
        let lt = real.smaller(1.0 2.0);
        tuple fl rd ab lt end;
        """
        val = run_quest_code(code)
        self.assertIsInstance(val, QTuple)
        self.assertEqual(val.elements[0], QInt(3))
        self.assertEqual(val.elements[1], QInt(3))
        self.assertEqual(val.elements[2], QReal(5.5))
        self.assertEqual(val.elements[3], TRUE_VALUE)

    def test_import_string_op(self):
        code = """
        import string: StringOp;
        let s = "hello";
        let l = string.length(s);
        let c = string.getChar(s 1);
        string.setChar(s 0 'H');
        let sub = string.getSub(s 0 2);
        let catStr = string.cat(s " world");
        tuple l c s sub catStr end;
        """
        val = run_quest_code(code)
        self.assertIsInstance(val, QTuple)
        self.assertEqual(val.elements[0], QInt(5))
        self.assertEqual(val.elements[1], QChar("e"))
        self.assertEqual(val.elements[2], QString("Hello"))
        self.assertEqual(val.elements[3], QString("He"))
        self.assertEqual(val.elements[4], QString("Hello world"))

    def test_import_array_op(self):
        code = """
        import arrayOp: ArrayOp;
        let a = arrayOp.new(4 10);
        let sz = arrayOp.size(a);
        arrayOp.set(a 2 99);
        let item = arrayOp.get(a 2);
        let errHandled = try
            arrayOp.get(a 10)
        when arrayOp.error then
            0 - 1
        end;
        tuple sz item errHandled end;
        """
        val = run_quest_code(code)
        self.assertIsInstance(val, QTuple)
        self.assertEqual(val.elements[0], QInt(4))
        self.assertEqual(val.elements[1], QInt(99))
        self.assertEqual(val.elements[2], QInt(-1))

    def test_import_dynamic_module(self):
        code = """
        import dynamic: Dynamic;
        let d = dynamic.new(123);
        let copied = dynamic.copy(d);
        let extracted = dynamic.be(copied);
        extracted;
        """
        self.assertEqual(run_quest_code(code), QInt(123))

    def test_import_writer_and_reader_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            temp_name = f.name

        try:
            code = f"""
            import writer: Writer reader: Reader;
            let w = writer.file("{temp_name}");
            writer.putString(w "Quest I/O\n");
            writer.close(w);

            let r = reader.file("{temp_name}");
            let s = reader.getString(r 9);
            reader.close(r);
            s;
            """
            self.assertEqual(run_quest_code(code), QString("Quest I/O"))
        finally:
            import os
            if os.path.exists(temp_name):
                os.remove(temp_name)

    def test_direct_interface_import(self):
        code = """
        import : Ascii;
        let x: Int = 10;
        x;
        """
        self.assertEqual(run_quest_code(code), QInt(10))

    def test_multi_import_phrase(self):
        code = """
        import ascii: Ascii int: IntOp;
        let c = ascii.val('Z');
        let m = int.max(c 100);
        m;
        """
        # ord('Z') = 90; max(90, 100) = 100
        self.assertEqual(run_quest_code(code), QInt(100))


if __name__ == "__main__":
    unittest.main()

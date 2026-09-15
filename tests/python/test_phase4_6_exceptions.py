"""Unit and integration tests for Phase 4.6: Exceptions in C Codegen & Runtime."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from quest.codegen import compile_c_source, run_binary
from quest.pipeline import compile_pipeline


class TestPhase46Exceptions(unittest.TestCase):
    """Tests C code generation and runtime handling for Quest exceptions."""

    def compile_quest(self, code: str, nogc: bool = False) -> subprocess.CompletedProcess[str]:
        """Helper to compile Quest code snippet to binary and run it."""
        pipeline = compile_pipeline()
        res = pipeline.execute(code, "<test>")
        self.assertTrue(res.success, f"Pipeline failed: {res.diagnostics}")
        c_code = res.artifacts.get("codegen_c")
        self.assertIsNotNone(c_code)

        with tempfile.NamedTemporaryFile(suffix="", delete=False) as f:
            bin_path = Path(f.name)

        try:
            compile_c_source(c_code, output_path=bin_path, nogc=nogc)
            proc = run_binary(bin_path)
            return proc
        finally:
            if bin_path.exists():
                bin_path.unlink()

    def test_user_exception_try_when(self):
        """Tests user-defined exception without payload caught by when."""
        code = """
        exception MyExc: Ok end;

        let compute(x: Int): Int =
            try
                if x < 0 then
                    raise MyExc end
                else
                    x * 2
                end
            when MyExc then
                ~1
            end;

        let a = compute(5);
        let b = compute(~3);
        a + b
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("9 : Int", proc.stdout)

    def test_user_exception_with_payload(self):
        """Tests user-defined exception carrying a String payload."""
        code = """
        exception Fail: String end;

        let tryWork(flag: Bool): String =
            try
                if flag then
                    raise Fail with "failed operation" end
                else
                    "ok operation"
                end
            when Fail with msg then
                msg
            end;

        let res = tryWork(true);
        res
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn('"failed operation" : String', proc.stdout)

    def test_catch_builtin_divide_by_zero(self):
        """Tests catching built-in DivideByZero exception in C code."""
        code = """
        let safeDiv(a: Int b: Int): Int =
            try
                a / b
            when DivideByZero then
                999
            end;

        let r1 = safeDiv(10 2);
        let r2 = safeDiv(10 0);
        r1 + r2
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("1004 : Int", proc.stdout)

    def test_catch_with_else_branch(self):
        """Tests try...when with an else branch."""
        code = """
        exception E1: Ok end;
        exception E2: Ok end;

        let handle(n: Int): Int =
            try
                if n is 1 then
                    raise E1 end
                else
                    raise E2 end
                end
            when E1 then
                100
            else
                200
            end;

        let a = handle(1);
        let b = handle(2);
        a + b
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("300 : Int", proc.stdout)

    def test_nested_try_reraise(self):
        """Tests unhandled exception propagating to outer try handler."""
        code = """
        exception OuterExc: Ok end;
        exception InnerExc: Ok end;

        let nested(dummy: Int): Int =
            try
                try
                    raise OuterExc end
                when InnerExc then
                    1
                end
            when OuterExc then
                2
            end;

        nested(0)
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("2 : Int", proc.stdout)

    def test_uncaught_exception_exits(self):
        """Tests that uncaught exception prints message to stderr and exits with non-zero."""
        code = """
        exception Panic: Ok end;
        raise Panic end;
        """
        proc = self.compile_quest(code)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Exception: Panic", proc.stderr)

    def test_exception_generativity(self):
        """Tests that two exception declarations produce distinct generative identities."""
        code = """
        Let ExcRec = Record e: Exception end;

        let makeExc(dummy: Int): ExcRec =
            begin
                exception LocalExc: Ok end;
                record e = LocalExc end
            end;

        let e1 = makeExc(0).e;
        let e2 = makeExc(0).e;

        let testMatch(dummy: Int): Int =
            try
                raise e1 end
            when e2 then
                1
            else
                2
            end;

        testMatch(0)
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("2 : Int", proc.stdout)

    def test_catch_array_error(self):
        """Tests catching arrayOp.error on out-of-bounds indexing."""
        code = """
        import arrayOp: ArrayOp;
        let arr = array of 10 20 30 end;
        let val =
            try
                arr[10]
            when arrayOp.error then
                ~99
            end;
        val
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("-99 : Int", proc.stdout)

    def test_golden_07_exceptions(self):
        """Tests the exceptions part of 07_exceptions_dynamic.quest."""
        code = """
        exception DivByZero: Ok end;

        let safeDiv(a: Int b: Int): Int =
            if b is 0 then
                raise DivByZero end
            else
                a / b
            end;

        let compute(a: Int b: Int): Int =
            try
                safeDiv(a b)
            when DivByZero then
                0
            else
                0 - 1
            end;

        let res1 = compute(10 2);
        let res2 = compute(10 0);
        res1 * 10 + res2
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("50 : Int", proc.stdout)

    def test_parameterized_exception_type_annotation(self):
        """Tests let-binding an exception with explicit Exception(Tuple ...) type annotation."""
        code = """
        let mismatchedExc: Exception(Tuple guessLength:Int answerLength:Int end) =
          exception
            mismatchedException: Tuple guessLength: Int answerLength: Int end
          end;

        try
            raise mismatchedExc with tuple let guessLength = 4 let answerLength = 5 end as Int end
        when mismatchedExc with t then
            t.guessLength + t.answerLength
        end
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("9 : Int", proc.stdout)

    def test_parameterized_exception_primitive_payload(self):
        """Tests let-binding an exception with explicit Exception(String) type annotation."""
        code = """
        let errExc: Exception(String) = exception CustomErr: String end;
        try
            raise errExc with "payload message" as String end
        when errExc with msg then
            msg
        end
        """
        proc = self.compile_quest(code)
        self.assertEqual(proc.returncode, 0)
        self.assertIn('"payload message" : String', proc.stdout)

    def test_parameterized_exception_invalid_arity(self):
        """Tests that applying Exception with invalid arity fails at compile-time."""
        code = """
        let badExc: Exception(Int String) = exception Bad: Int end;
        """
        pipeline = compile_pipeline()
        res = pipeline.execute(code, "<test>")
        self.assertFalse(res.success)
        self.assertTrue(
            any("Exception type constructor expects 1 argument" in str(d) for d in res.diagnostics)
        )


"""Unit tests for Stage 4 Cardelli Standard Library Alignment & Top-Level Pre-Linking.

Tests:
1. Top-level pre-linking of standard library modules (arrayOp, ascii, conv, dynamic,
   int, list, reader, real, string, writer)
2. Module isolation: modules must explicitly import standard library modules
3. dynamic: Dynamic module (new, be type validation/narrowing, copy, extern, intern)
4. list: List module (nil, cons, null, head, tail, length, enum)
5. StringOp.precedesSub substring lexicographical comparison
"""

import io
import unittest

from tests.python.helpers import assert_pipeline_failure, assert_pipeline_success
from quest.interpreter import QuestException
from quest.runtime import (
    FALSE_VALUE,
    TRUE_VALUE,
    QArray,
    QBool,
    QDynamicVal,
    QInt,
    QList,
    QReader,
    QRecord,
    QString,
    QTuple,
    QVariant,
    QWriter,
    qvalue_to_str,
)


class TestStage4Cardelli(unittest.TestCase):
    """Verifies Cardelli Typeful Programming §7.1, §9.1, §11.3 Stage 4 alignment."""

    def test_top_level_prelinking_standard_modules(self):
        """Standard library modules are accessible at top level without explicit import."""
        code = """
        let s1: String = conv.int(42);
        let n1: Int = int.abs(~100);
        let c1: Char = ascii.char(65);
        let str1: String = string.new(3 'x');
        let arr1 = arrayOp.new(:Int 2 7);
        let d1 = dynamic.new(:Int 99);
        let l0 = list.nil(:Int);
        let rReady: Int = reader.ready(reader.input);
        let fl: Int = real.floor(3.7);

        tuple s1 n1 c1 str1 arr1 d1 l0 rReady fl end;
        """
        ctx = assert_pipeline_success(code)
        env = ctx.runtime_env

        self.assertEqual(env.lookup("s1"), QString("42"))
        self.assertEqual(env.lookup("n1"), QInt(100))
        self.assertEqual(env.lookup("c1").value, "A")
        self.assertEqual(env.lookup("str1"), QString("xxx"))
        self.assertEqual(env.lookup("rReady"), QInt(0))
        self.assertEqual(env.lookup("fl"), QInt(3))

    def test_module_isolation_requires_explicit_import(self):
        """Modules cannot access pre-linked standard modules without explicit import."""
        # 1. Without import: fails typechecking with undefined identifier
        bad_code = """
        interface Counter export get: Int end;
        module counter: Counter export
            let get: Int = int.abs(~5);
        end;
        """
        assert_pipeline_failure(bad_code, "Undefined identifier 'int'")

        # 2. With explicit import: succeeds
        good_code = """
        interface Counter export get: Int end;
        module counter: Counter
            import int: IntOp
        export
            let get: Int = int.abs(~5);
        end;
        let res: Int = counter.get;
        """
        ctx = assert_pipeline_success(good_code)
        self.assertEqual(ctx.runtime_env.lookup("res"), QInt(5))

    def test_dynamic_new_and_be_type_validation(self):
        """dynamic.new and dynamic.be support type validation and narrowing."""
        code = """
        let d = dynamic.new(:Int 42);
        let extracted: Int = dynamic.be(:Int d);
        let dInferred = dynamic.new("hello");
        let extractedS: String = dynamic.be(:String dInferred);
        """
        ctx = assert_pipeline_success(code)
        self.assertEqual(ctx.runtime_env.lookup("extracted"), QInt(42))
        self.assertEqual(ctx.runtime_env.lookup("extractedS"), QString("hello"))

        # dynamic.be with incompatible type raises dynamic.error
        mismatch_code = """
        let d = dynamic.new(:Int 42);
        let bad = try dynamic.be(:Bool d)
            when dynamic.error then false
        end;
        """
        ctx2 = assert_pipeline_success(mismatch_code)
        self.assertEqual(ctx2.runtime_env.lookup("bad"), FALSE_VALUE)

        # Legacy bare dynamic(42) function is not defined
        legacy_code = "let d = dynamic(42);"
        assert_pipeline_failure(legacy_code)

    def test_dynamic_intern_and_extern(self):
        """dynamic.extern writes JSON/JSOG representation and dynamic.intern reads it."""
        from quest.builtins import BuiltinModuleRegistry
        from quest.interpreter import DYNAMIC_ERROR_EXC, QuestException

        dyn_mod = BuiltinModuleRegistry.get_runtime_module("dynamic")
        new_fn = dyn_mod.fields["new"].fn
        extern_fn = dyn_mod.fields["extern"].fn
        intern_fn = dyn_mod.fields["intern"].fn

        # 1. Primitive dynamic value
        d = new_fn(QInt(42))
        str_out = io.StringIO()
        wr = QWriter(stream=str_out, is_file=False)
        extern_fn(wr, d)
        self.assertEqual(str_out.getvalue(), '{"@type":"Int","@value":42}')

        str_in = io.StringIO(str_out.getvalue())
        rd = QReader(stream=str_in, is_file=False)
        d_interned = intern_fn(rd)
        self.assertIsInstance(d_interned, QDynamicVal)
        self.assertEqual(d_interned.value, QInt(42))

        # 2. Cyclic record
        cyc_rec = QRecord({"name": QString("loop")})
        cyc_rec.fields["next"] = cyc_rec
        d_cyc = QDynamicVal(cyc_rec, "Record name: String next: Any end")
        s_out = io.StringIO()
        extern_fn(QWriter(stream=s_out, is_file=False), d_cyc)
        json_cyc = s_out.getvalue()
        self.assertIn('"@id":"1"', json_cyc)
        self.assertIn('"@ref":"1"', json_cyc)

        d_cyc_in = intern_fn(QReader(stream=io.StringIO(json_cyc), is_file=False))
        self.assertIsInstance(d_cyc_in.value, QRecord)
        self.assertEqual(d_cyc_in.value.fields["name"], QString("loop"))
        self.assertIs(d_cyc_in.value.fields["next"], d_cyc_in.value)

        # 3. Cyclic array
        cyc_arr = QArray([QInt(100)])
        cyc_arr.elements.append(cyc_arr)
        d_arr = QDynamicVal(cyc_arr, "Array(Any)")
        s_arr_out = io.StringIO()
        extern_fn(QWriter(stream=s_arr_out, is_file=False), d_arr)
        json_arr = s_arr_out.getvalue()
        self.assertIn('"@array"', json_arr)
        self.assertIn('"@ref":"1"', json_arr)

        d_arr_in = intern_fn(QReader(stream=io.StringIO(json_arr), is_file=False))
        self.assertIsInstance(d_arr_in.value, QArray)
        self.assertEqual(d_arr_in.value.elements[0], QInt(100))
        self.assertIs(d_arr_in.value.elements[1], d_arr_in.value)

        # 4. Serde-style variant
        v = QVariant("red", QInt(255))
        d_var = QDynamicVal(v, "Variant red: Int green: Ok end")
        s_var_out = io.StringIO()
        extern_fn(QWriter(stream=s_var_out, is_file=False), d_var)
        self.assertEqual(
            s_var_out.getvalue(),
            '{"@type":"Variant red: Int green: Ok end","@value":{"red":255}}',
        )
        d_var_in = intern_fn(QReader(stream=io.StringIO(s_var_out.getvalue()), is_file=False))
        self.assertIsInstance(d_var_in.value, QVariant)
        self.assertEqual(d_var_in.value.tag, "red")
        self.assertEqual(d_var_in.value.payload, QInt(255))

        # 5. Non-externable type raises error
        with self.assertRaises(QuestException) as cm:
            extern_fn(wr, QDynamicVal(wr, "Writer.T"))
        self.assertEqual(cm.exception.exc_val, DYNAMIC_ERROR_EXC)

        # 6. Malformed JSON raises error on intern
        with self.assertRaises(QuestException) as cm2:
            intern_fn(QReader(stream=io.StringIO("{not valid json"), is_file=False))
        self.assertEqual(cm2.exception.exc_val, DYNAMIC_ERROR_EXC)

    def test_dynamic_extern_intern_in_quest(self):
        """Quest program can extern and intern a dynamic value through a file."""
        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp_path = f.name
        try:
            code = f"""
            import dynamic: Dynamic;
            import writer: Writer;
            import reader: Reader;
            import conv: Conv;

            let w = writer.file("{tmp_path}");
            let dOut = dynamic.new(:Int 12345);
            dynamic.extern(w dOut);
            writer.close(w);

            let r = reader.file("{tmp_path}");
            let dIn = dynamic.intern(r);
            reader.close(r);

            let val: Int = dynamic.be(:Int dIn);
            let s: String = conv.int(val);
            """
            ctx = assert_pipeline_success(code)
            self.assertEqual(ctx.runtime_env.lookup("s"), QString("12345"))
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_dynamic_extern_intern_cyclic_record_in_quest(self):
        """Quest program can extern and intern a cyclic record through a file."""
        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp_path = f.name
        try:
            code = f"""
            import dynamic: Dynamic;
            import writer: Writer;
            import reader: Reader;

            Let Node = Record
                name: String
                var next: Dynamic.T
            end;

            let node = record
                name = "cycle"
                var next = dynamic.new(:Ok ok)
            end;
            node.next := dynamic.new(:Node node);

            let w = writer.file("{tmp_path}");
            dynamic.extern(w dynamic.new(:Node node));
            writer.close(w);

            let r = reader.file("{tmp_path}");
            let dIn = dynamic.intern(r);
            reader.close(r);

            let n: Node = dynamic.be(:Node dIn);
            let nNext: Node = dynamic.be(:Node n.next);
            let s: String = nNext.name;
            """
            ctx = assert_pipeline_success(code)
            self.assertEqual(ctx.runtime_env.lookup("s"), QString("cycle"))
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_list_operations(self):
        """list module provides nil, cons, null, head, tail, length, enum."""
        code = """
        let l0 = list.nil(:Int);
        let null0: Bool = list.null(:Int l0);
        let len0: Int = list.length(:Int l0);

        let l1 = list.cons(:Int 10 l0);
        let null1: Bool = list.null(:Int l1);
        let h1: Int = list.head(:Int l1);
        let len1: Int = list.length(:Int l1);

        let l2 = list.cons(:Int 20 l1);
        let h2: Int = list.head(:Int l2);
        let t2 = list.tail(:Int l2);
        let ht2: Int = list.head(:Int t2);
        let len2: Int = list.length(:Int l2);

        let lEnum = list.enum of 1 2 3 end;
        let lenEnum: Int = list.length(:Int lEnum);
        let hEnum: Int = list.head(:Int lEnum);
        """
        ctx = assert_pipeline_success(code)
        env = ctx.runtime_env

        self.assertEqual(env.lookup("null0"), TRUE_VALUE)
        self.assertEqual(env.lookup("len0"), QInt(0))
        self.assertEqual(env.lookup("null1"), FALSE_VALUE)
        self.assertEqual(env.lookup("h1"), QInt(10))
        self.assertEqual(env.lookup("len1"), QInt(1))
        self.assertEqual(env.lookup("h2"), QInt(20))
        self.assertEqual(env.lookup("ht2"), QInt(10))
        self.assertEqual(env.lookup("len2"), QInt(2))
        self.assertEqual(env.lookup("lenEnum"), QInt(3))
        self.assertEqual(env.lookup("hEnum"), QInt(1))

        # Check formatting: list of 1 2 3 end
        l_enum_val = env.lookup("lEnum")
        self.assertEqual(qvalue_to_str(l_enum_val), "list of 1 2 3 end")
        self.assertEqual(qvalue_to_str(env.lookup("l0")), "list of end")

    def test_list_head_tail_empty_raises_error(self):
        """list.head and list.tail raise list.error when invoked on empty list."""
        code = """
        let l0 = list.nil(:Int);
        let headErr = try
            list.head(:Int l0)
        when list.error then
            ~1
        end;
        let tailErr = try
            let ignored = list.tail(:Int l0);
            0
        when list.error then
            ~2
        end;
        """
        ctx = assert_pipeline_success(code)
        env = ctx.runtime_env
        self.assertEqual(env.lookup("headErr"), QInt(-1))
        self.assertEqual(env.lookup("tailErr"), QInt(-2))

    def test_string_precedes_sub(self):
        """string.precedesSub compares substrings lexicographically."""
        code = """
        let s1 = "abcdef";
        let s2 = "bcxyz";
        let s3 = "abxyz";

        (* "bcd" <= "bcx" -> true *)
        let r1: Bool = string.precedesSub(s1 1 3 s2 0 3);
        (* "bcd" <= "abx" -> false *)
        let r2: Bool = string.precedesSub(s1 1 3 s3 0 3);
        (* "bcd" <= "bcd" -> true *)
        let r3: Bool = string.precedesSub(s1 1 3 s1 1 3);

        (* Out of bounds raises string.error *)
        let rErr = try
            string.precedesSub(s1 0 100 s2 0 3)
        when string.error then
            false
        end;
        """
        ctx = assert_pipeline_success(code)
        env = ctx.runtime_env
        self.assertEqual(env.lookup("r1"), TRUE_VALUE)
        self.assertEqual(env.lookup("r2"), FALSE_VALUE)
        self.assertEqual(env.lookup("r3"), TRUE_VALUE)
        self.assertEqual(env.lookup("rErr"), FALSE_VALUE)


if __name__ == '__main__':
    unittest.main()

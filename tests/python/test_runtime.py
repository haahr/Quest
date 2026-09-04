"""Unit tests for Quest Runtime Values and Memory Model (bootstrap/python/quest/runtime.py)."""

import unittest

from quest.runtime import (
    FALSE_VALUE,
    OK_VALUE,
    TRUE_VALUE,
    QArray,
    QBool,
    QBuiltinFun,
    QChar,
    QClosure,
    QDynamicVal,
    QExceptionVal,
    QInt,
    QOk,
    QOption,
    QReal,
    QRecord,
    QRef,
    QString,
    QTuple,
    QVariant,
    qvalue_is,
    qvalue_structural_eq,
    qvalue_to_str,
)


class TestRuntimePrimitives(unittest.TestCase):
    """Tests for primitive values and their string representations."""

    def test_ok(self):
        v1 = QOk()
        v2 = OK_VALUE
        self.assertIs(v1, v2)
        self.assertEqual(v1.type_name, "Ok")
        self.assertEqual(qvalue_to_str(v1), "ok")

    def test_bool(self):
        t1 = QBool(True)
        t2 = TRUE_VALUE
        f1 = QBool(False)
        f2 = FALSE_VALUE
        self.assertIs(t1, t2)
        self.assertIs(f1, f2)
        self.assertEqual(qvalue_to_str(t1), "true")
        self.assertEqual(qvalue_to_str(f1), "false")

    def test_int(self):
        i1 = QInt(42)
        i2 = QInt(-10)
        self.assertEqual(i1.type_name, "Int")
        self.assertEqual(qvalue_to_str(i1), "42")
        self.assertEqual(qvalue_to_str(i2), "-10")

    def test_real(self):
        r1 = QReal(3.14)
        r2 = QReal(2.0)
        self.assertEqual(r1.type_name, "Real")
        self.assertEqual(qvalue_to_str(r1), "3.14")
        self.assertEqual(qvalue_to_str(r2), "2.0")

    def test_char(self):
        c1 = QChar("a")
        c2 = QChar("\n")
        c3 = QChar("'")
        self.assertEqual(c1.type_name, "Char")
        self.assertEqual(qvalue_to_str(c1), "'a'")
        self.assertEqual(qvalue_to_str(c2), r"'\n'")
        self.assertEqual(qvalue_to_str(c3), r"'\''")

        with self.assertRaises(ValueError):
            QChar("too_long")

    def test_string(self):
        s1 = QString("hello")
        s2 = QString("line1\nline2\t\"quoted\"")
        self.assertEqual(s1.type_name, "String")
        self.assertEqual(qvalue_to_str(s1), '"hello"')
        self.assertEqual(qvalue_to_str(s2), r'"line1\nline2\t\"quoted\""')


class TestRuntimeAggregates(unittest.TestCase):
    """Tests for records, tuples, and arrays."""

    def test_record_basic_and_sorted_formatting(self):
        # Fields inserted out of alphabetical order
        r = QRecord({"z": QInt(26), "a": QInt(1), "m": QString("mid")})
        self.assertEqual(r.type_name, "Record")
        self.assertEqual(r.get("z"), QInt(26))
        self.assertEqual(r.get("a"), QInt(1))
        # Formats with keys sorted alphabetically
        self.assertEqual(qvalue_to_str(r), 'record a=1 m="mid" z=26 end')

        empty_r = QRecord()
        self.assertEqual(qvalue_to_str(empty_r), "record end")

        with self.assertRaises(KeyError):
            r.get("nonexistent")

    def test_tuple_positional_and_labeled(self):
        # Pure positional
        t_pos = QTuple((QInt(10), QReal(2.5), QString("test")))
        self.assertEqual(t_pos.type_name, "Tuple")
        self.assertEqual(t_pos.get_by_index(0), QInt(10))
        self.assertEqual(t_pos.get_by_index(1), QReal(2.5))
        self.assertEqual(qvalue_to_str(t_pos), 'tuple 10 2.5 "test" end')

        # Labeled components
        t_named = QTuple(
            (QInt(10), QString("ten")),
            labels=("count", "name"),
        )
        self.assertEqual(t_named.get_by_name("count"), QInt(10))
        self.assertEqual(t_named.get_by_name("name"), QString("ten"))
        self.assertEqual(t_named.get_by_index(0), QInt(10))
        self.assertEqual(qvalue_to_str(t_named), 'tuple count=10 name="ten" end')

        # Empty tuple
        self.assertEqual(qvalue_to_str(QTuple(())), "tuple end")

        with self.assertRaises(IndexError):
            t_pos.get_by_index(99)
        with self.assertRaises(KeyError):
            t_named.get_by_name("missing")

    def test_array_mutation_and_formatting(self):
        arr = QArray([QInt(1), QInt(2), QInt(3)])
        self.assertEqual(arr.type_name, "Array")
        self.assertEqual(arr.size(), 3)
        self.assertEqual(arr.get(1), QInt(2))

        # Mutation
        arr.set(1, QInt(99))
        self.assertEqual(arr.get(1), QInt(99))
        self.assertEqual(qvalue_to_str(arr), "array of 1 99 3 end")

        empty_arr = QArray([])
        self.assertEqual(qvalue_to_str(empty_arr), "array of end")

        with self.assertRaises(IndexError):
            arr.get(10)
        with self.assertRaises(IndexError):
            arr.set(-1, QInt(0))


class TestRuntimeSumTypes(unittest.TestCase):
    """Tests for Variant and Option values."""

    def test_variant(self):
        v1 = QVariant("nil")
        v2 = QVariant("cons", QInt(42))
        self.assertEqual(v1.type_name, "Variant")
        self.assertEqual(qvalue_to_str(v1), "variant nil end")
        self.assertEqual(qvalue_to_str(v2), "variant cons with 42 end")

    def test_option(self):
        opt1 = QOption("none")
        opt2 = QOption("some", QString("data"))
        self.assertEqual(opt1.type_name, "Option")
        self.assertEqual(qvalue_to_str(opt1), "option none end")
        self.assertEqual(qvalue_to_str(opt2), 'option some with "data" end')


class TestRuntimeFunctionsAndClosures(unittest.TestCase):
    """Tests for functions and closures."""

    def test_closure(self):
        c_anon = QClosure(params=("x",), body=None, env=None)
        c_named = QClosure(params=("x",), body=None, env=None, name="addOne")
        self.assertEqual(c_anon.type_name, "Function")
        self.assertEqual(qvalue_to_str(c_anon), "<fun>")
        self.assertEqual(qvalue_to_str(c_named), "<fun:addOne>")

    def test_builtin_fun(self):
        b_fn = QBuiltinFun(name="writeLine", fn=lambda x: OK_VALUE)
        self.assertEqual(b_fn.type_name, "BuiltinFunction")
        self.assertEqual(qvalue_to_str(b_fn), "<builtin:writeLine>")


class TestRuntimeRef(unittest.TestCase):
    """Tests for mutable reference cells."""

    def test_ref_deref_and_assign(self):
        cell = QRef(QInt(10))
        self.assertEqual(cell.type_name, "Ref(Int)")
        self.assertEqual(cell.deref(), QInt(10))
        self.assertEqual(qvalue_to_str(cell), "ref(10)")

        cell.assign(QInt(25))
        self.assertEqual(cell.deref(), QInt(25))
        self.assertEqual(qvalue_to_str(cell), "ref(25)")


class TestRuntimeDynamicAndException(unittest.TestCase):
    """Tests for Dynamic envelopes and Exception values."""

    def test_dynamic(self):
        dyn = QDynamicVal(QInt(42), "Int")
        self.assertEqual(dyn.type_name, "Dynamic")
        self.assertEqual(qvalue_to_str(dyn), "dynamic(42 : Int)")

    def test_exception(self):
        exc_bare = QExceptionVal("NotFound")
        exc_payload = QExceptionVal("IOError", QString("disk full"))
        self.assertEqual(exc_bare.type_name, "Exception")
        self.assertEqual(qvalue_to_str(exc_bare), "exception NotFound")
        self.assertEqual(qvalue_to_str(exc_payload), 'exception IOError with "disk full"')


class TestIdentityAndStructuralEquality(unittest.TestCase):
    """Tests for Cardelli 'is' (qvalue_is) and deep structural equality (qvalue_structural_eq)."""

    def test_qvalue_is_primitives(self):
        # Ok, Bool, Int, Real, Char compare by value
        self.assertTrue(qvalue_is(QOk(), OK_VALUE))
        self.assertTrue(qvalue_is(QBool(True), TRUE_VALUE))
        self.assertTrue(qvalue_is(QInt(100), QInt(100)))
        self.assertTrue(qvalue_is(QReal(3.14), QReal(3.14)))
        self.assertTrue(qvalue_is(QChar("z"), QChar("z")))

        self.assertFalse(qvalue_is(QInt(1), QInt(2)))
        self.assertFalse(qvalue_is(QInt(1), QReal(1.0)))

    def test_qvalue_is_objects_use_identity(self):
        # Distinct QStrings compare as False by pointer identity
        s1 = QString("same_content")
        s2 = QString("same_content")
        self.assertTrue(qvalue_is(s1, s1))
        self.assertFalse(qvalue_is(s1, s2))

        # Distinct QRecords compare as False by pointer identity
        r1 = QRecord({"a": QInt(1)})
        r2 = QRecord({"a": QInt(1)})
        self.assertTrue(qvalue_is(r1, r1))
        self.assertFalse(qvalue_is(r1, r2))

        # Distinct QArrays
        a1 = QArray([QInt(1)])
        a2 = QArray([QInt(1)])
        self.assertTrue(qvalue_is(a1, a1))
        self.assertFalse(qvalue_is(a1, a2))

    def test_structural_equality_deep(self):
        # Strings compare by content
        self.assertTrue(qvalue_structural_eq(QString("hello"), QString("hello")))
        self.assertFalse(qvalue_structural_eq(QString("hello"), QString("world")))

        # Records compare by content independent of key insertion order
        r1 = QRecord({"x": QInt(1), "y": QArray([QInt(2), QInt(3)])})
        r2 = QRecord({"y": QArray([QInt(2), QInt(3)]), "x": QInt(1)})
        r3 = QRecord({"x": QInt(1), "y": QArray([QInt(2), QInt(4)])})
        self.assertTrue(qvalue_structural_eq(r1, r2))
        self.assertFalse(qvalue_structural_eq(r1, r3))

        # Tuples
        t1 = QTuple((QInt(1), QString("a")), labels=("x", "y"))
        t2 = QTuple((QInt(1), QString("a")), labels=("x", "y"))
        t3 = QTuple((QInt(1), QString("a")), labels=("a", "b"))
        self.assertTrue(qvalue_structural_eq(t1, t2))
        self.assertFalse(qvalue_structural_eq(t1, t3))

    def test_cycle_handling(self):
        # Self-referential record: r.self = r
        r = QRecord({"name": QString("cycle")})
        ref_cell = QRef(r)
        r.fields["self"] = ref_cell

        # Cycle detection in string formatting
        dump = qvalue_to_str(r)
        self.assertIn("record ... end", dump)

        # Cycle detection in structural equality
        r2 = QRecord({"name": QString("cycle")})
        ref_cell2 = QRef(r2)
        r2.fields["self"] = ref_cell2

        self.assertTrue(qvalue_structural_eq(r, r2))


if __name__ == "__main__":
    unittest.main()

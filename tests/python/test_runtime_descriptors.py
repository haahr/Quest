"""Unit tests for Phase 4.8a: C Runtime Type Descriptors, Interning, and Dynamic Operations."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure bootstrap/python is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

from quest.codegen.compiler_runner import compile_c_source, run_binary


class TestRuntimeDescriptors(unittest.TestCase):
    """Tests QTypeDescriptor static allocation, interning table, and dynamic operations."""

    def compile_and_run_c(self, c_code: str, nogc: bool = False) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile(suffix="", delete=False) as f:
            bin_path = Path(f.name)

        try:
            compile_c_source(c_code, output_path=bin_path, nogc=nogc)
            proc = run_binary(bin_path)
            return proc
        finally:
            if bin_path.exists():
                bin_path.unlink()

    def test_base_type_descriptors(self):
        """Tests that base type descriptors exist, have correct names/sizes, and can be interned."""
        c_code = """
        #include "quest_runtime.h"
        #include <assert.h>
        #include <stdio.h>

        int main(void) {
            quest_gc_init();

            /* Check pre-allocated static descriptors */
            assert(quest_type_Int.kind == QTYPE_KIND_INT);
            assert(strcmp(quest_type_Int.name, "Int") == 0);
            assert(quest_type_Int.size == sizeof(QInt));

            assert(quest_type_Real.kind == QTYPE_KIND_REAL);
            assert(strcmp(quest_type_Real.name, "Real") == 0);

            assert(quest_type_Bool.kind == QTYPE_KIND_BOOL);
            assert(strcmp(quest_type_Bool.name, "Bool") == 0);

            assert(quest_type_Char.kind == QTYPE_KIND_CHAR);
            assert(strcmp(quest_type_Char.name, "Char") == 0);

            assert(quest_type_String.kind == QTYPE_KIND_STRING);
            assert(strcmp(quest_type_String.name, "String") == 0);

            assert(quest_type_Ok.kind == QTYPE_KIND_OK);
            assert(strcmp(quest_type_Ok.name, "Ok") == 0);

            assert(quest_type_Dynamic.kind == QTYPE_KIND_DYNAMIC);
            assert(strcmp(quest_type_Dynamic.name, "Dynamic") == 0);

            assert(quest_type_EmptyTuple.kind == QTYPE_KIND_TUPLE);
            assert(strcmp(quest_type_EmptyTuple.name, "Tuple end") == 0);

            /* Check interning of base descriptors returns the same static pointer */
            const QTypeDescriptor *d_int = quest_intern_type_descriptor(&quest_type_Int);
            assert(d_int == &quest_type_Int);

            /* Subtyping: Int <: Int and Int <: Tuple end */
            assert(quest_type_Int.is_subtype(&quest_type_Int, &quest_type_Int));
            assert(quest_type_Int.is_subtype(&quest_type_Int, &quest_type_EmptyTuple));
            assert(!quest_type_Int.is_subtype(&quest_type_Int, &quest_type_Real));

            printf("BASE_DESCRIPTORS_OK\\n");
            return 0;
        }
        """
        proc = self.compile_and_run_c(c_code)
        self.assertEqual(proc.returncode, 0, f"Failed: {proc.stderr}")
        self.assertIn("BASE_DESCRIPTORS_OK", proc.stdout)

    def test_array_descriptor_interning(self):
        """Tests that array descriptors are memoized such that Array(Int) == Array(Int)."""
        c_code = """
        #include "quest_runtime.h"
        #include <assert.h>
        #include <stdio.h>

        int main(void) {
            quest_gc_init();

            const QTypeDescriptor *arr1 = quest_make_array_descriptor(&quest_type_Int);
            const QTypeDescriptor *arr2 = quest_make_array_descriptor(&quest_type_Int);
            const QTypeDescriptor *arr_str = quest_make_array_descriptor(&quest_type_String);

            assert(arr1 != NULL);
            assert(arr2 != NULL);
            /* Canonical pointer equality check */
            assert(arr1 == arr2);
            assert(arr1 != arr_str);

            assert(arr1->kind == QTYPE_KIND_ARRAY);
            assert(strcmp(arr1->name, "Array(Int)") == 0);
            assert(strcmp(arr_str->name, "Array(String)") == 0);

            /* Nested array: Array(Array(Int)) */
            const QTypeDescriptor *nested1 = quest_make_array_descriptor(arr1);
            const QTypeDescriptor *nested2 = quest_make_array_descriptor(arr2);
            assert(nested1 == nested2);
            assert(strcmp(nested1->name, "Array(Array(Int))") == 0);

            /* Subtyping checks */
            assert(arr1->is_subtype(arr1, arr1));
            assert(arr1->is_subtype(arr1, &quest_type_EmptyTuple));
            assert(!arr1->is_subtype(arr1, arr_str));

            printf("ARRAY_INTERN_OK\\n");
            return 0;
        }
        """
        proc = self.compile_and_run_c(c_code)
        self.assertEqual(proc.returncode, 0, f"Failed: {proc.stderr}")
        self.assertIn("ARRAY_INTERN_OK", proc.stdout)

    def test_opaque_descriptor_identity(self):
        """Tests that opaque type descriptors have nominal identity (never equal even with same name)."""
        c_code = """
        #include "quest_runtime.h"
        #include <assert.h>
        #include <stdio.h>

        int main(void) {
            quest_gc_init();

            const QTypeDescriptor *t1 = quest_make_opaque_descriptor("T");
            const QTypeDescriptor *t2 = quest_make_opaque_descriptor("T");

            assert(t1 != NULL);
            assert(t2 != NULL);
            assert(t1 != t2); /* Unique nominal pointer identity */
            assert(strcmp(t1->name, "T") == 0);
            assert(strcmp(t2->name, "T") == 0);
            assert(t1->kind == QTYPE_KIND_OPAQUE);

            printf("OPAQUE_IDENTITY_OK\\n");
            return 0;
        }
        """
        proc = self.compile_and_run_c(c_code)
        self.assertEqual(proc.returncode, 0, f"Failed: {proc.stderr}")
        self.assertIn("OPAQUE_IDENTITY_OK", proc.stdout)

    def test_dynamic_new_and_be_success(self):
        """Tests packaging a value into QDynamic and extracting it with matching descriptor."""
        c_code = """
        #include "quest_runtime.h"
        #include <assert.h>
        #include <stdio.h>

        int main(void) {
            quest_gc_init();

            QVal val = { .i = 42LL };
            QDynamic *d = quest_dynamic_new(&quest_type_Int, val);
            assert(d != NULL);
            assert(d->type_desc == &quest_type_Int);
            assert(d->payload.i == 42LL);

            /* Successful extraction via dynamic.be with matching descriptor */
            QVal extracted = quest_dynamic_be(&quest_type_Int, d);
            assert(extracted.i == 42LL);

            /* Extraction via supertype (Tuple end) */
            QVal extracted_top = quest_dynamic_be(&quest_type_EmptyTuple, d);
            assert(extracted_top.i == 42LL);

            printf("DYNAMIC_SUCCESS_OK\\n");
            return 0;
        }
        """
        proc = self.compile_and_run_c(c_code)
        self.assertEqual(proc.returncode, 0, f"Failed: {proc.stderr}")
        self.assertIn("DYNAMIC_SUCCESS_OK", proc.stdout)

    def test_dynamic_be_failure_raises_dynamic_error(self):
        """Tests that quest_dynamic_be raises quest_exc_dynamic_error when type mismatches."""
        c_code = """
        #include "quest_runtime.h"
        #include <assert.h>
        #include <stdio.h>

        int main(void) {
            quest_gc_init();

            QVal val = { .i = 42LL };
            QDynamic *d = quest_dynamic_new(&quest_type_Int, val);

            QExceptionHandler handler;
            handler.prev = quest_current_exception_handler;
            quest_current_exception_handler = &handler;

            if (setjmp(handler.env_jmp) == 0) {
                /* Attempting to coerce Int to String must fail */
                quest_dynamic_be(&quest_type_String, d);
                printf("UNREACHABLE\\n");
                return 1;
            } else {
                /* Exception caught! Verify it is quest_exc_dynamic_error */
                quest_current_exception_handler = handler.prev;
                assert(quest_current_exception.exc == &quest_exc_dynamic_error);
                assert(strcmp(quest_current_exception.exc->name, "dynamic.error") == 0);
                printf("DYNAMIC_ERROR_CAUGHT_OK\\n");
                return 0;
            }
        }
        """
        proc = self.compile_and_run_c(c_code)
        self.assertEqual(proc.returncode, 0, f"Failed: {proc.stderr}")
        self.assertIn("DYNAMIC_ERROR_CAUGHT_OK", proc.stdout)

    def test_compound_record_subtyping_and_adaptation(self):
        """Tests record width/depth subtyping and dynamic dictionary synthesis."""
        c_code = """
        #include "quest_runtime.h"
        #include <assert.h>
        #include <stdio.h>

        /* Big record: { x: Int, y: Int, z: Int } */
        struct BigRec {
            int64_t qf_x;
            int64_t qf_y;
            int64_t qf_z;
        };
        /* Small record: { y: Int } */
        struct SmallRec {
            int64_t qf_y;
        };

        /* Offset dict for SmallRec */
        struct DictSmall {
            size_t offset_y;
        };

        int main(void) {
            quest_gc_init();

            QRecordFieldDescriptor big_fields[] = {
                { .name = "x", .type = &quest_type_Int, .offset = offsetof(struct BigRec, qf_x), .is_var = false },
                { .name = "y", .type = &quest_type_Int, .offset = offsetof(struct BigRec, qf_y), .is_var = false },
                { .name = "z", .type = &quest_type_Int, .offset = offsetof(struct BigRec, qf_z), .is_var = false }
            };
            const QTypeDescriptor *big_desc = quest_make_record_descriptor(
                "Record x: Int y: Int z: Int end", sizeof(struct BigRec), 8, 3, big_fields);

            QRecordFieldDescriptor small_fields[] = {
                { .name = "y", .type = &quest_type_Int, .offset = offsetof(struct SmallRec, qf_y), .is_var = false }
            };
            const QTypeDescriptor *small_desc = quest_make_record_descriptor(
                "Record y: Int end", sizeof(struct SmallRec), 8, 1, small_fields);

            /* Subtyping: big <: small, but NOT small <: big */
            assert(quest_is_subtype(big_desc, small_desc));
            assert(!quest_is_subtype(small_desc, big_desc));

            /* Allocate big record payload */
            struct BigRec *b = (struct BigRec *)quest_alloc(sizeof(struct BigRec));
            b->qf_x = 100;
            b->qf_y = 200;
            b->qf_z = 300;

            QRecordVal r_big = { .val = b, .dict = NULL };
            QDynamic *d = quest_dynamic_new(big_desc, (QVal){ .p = quest_record_box(r_big) });

            /* Coerce to SmallRec via dynamic.be */
            QVal extracted = quest_dynamic_be(small_desc, d);
            QRecordVal *r_small = (QRecordVal *)extracted.p;
            assert(r_small != NULL);

            /* Check that dictionary correctly mapped 'y' offset to BigRec.qf_y */
            const struct DictSmall *dict = (const struct DictSmall *)r_small->dict;
            assert(dict->offset_y == offsetof(struct BigRec, qf_y));

            int64_t val_y = *(int64_t *)((char *)r_small->val + dict->offset_y);
            assert(val_y == 200);

            printf("RECORD_SUBTYPING_OK\\n");
            return 0;
        }
        """
        proc = self.compile_and_run_c(c_code)
        self.assertEqual(proc.returncode, 0, f"Failed: {proc.stderr}")
        self.assertIn("RECORD_SUBTYPING_OK", proc.stdout)

    def test_compound_variant_subtyping_and_adaptation(self):
        """Tests variant subtyping and dynamic tag remapping."""
        c_code = """
        #include "quest_runtime.h"
        #include <assert.h>
        #include <stdio.h>

        int main(void) {
            quest_gc_init();

            /* Subvariant: Option b end (case count 1, tag 'b' = 0) */
            QVariantCaseDescriptor sub_cases[] = {
                { .name = "b", .payload_type = NULL, .tag_index = 0, .is_var = false }
            };
            const QTypeDescriptor *sub_desc = quest_make_variant_descriptor(
                "Option b end", sizeof(QVariantVal), 8, 1, sub_cases);

            /* Supervariant: Option a b c end (tag 'a' = 0, 'b' = 1, 'c' = 2) */
            QVariantCaseDescriptor super_cases[] = {
                { .name = "a", .payload_type = NULL, .tag_index = 0, .is_var = false },
                { .name = "b", .payload_type = NULL, .tag_index = 1, .is_var = false },
                { .name = "c", .payload_type = NULL, .tag_index = 2, .is_var = false }
            };
            const QTypeDescriptor *super_desc = quest_make_variant_descriptor(
                "Option a b c end", sizeof(QVariantVal), 8, 3, super_cases);

            /* Subtyping: sub <: super (fewer cases is subtype of more cases) */
            assert(quest_is_subtype(sub_desc, super_desc));
            assert(!quest_is_subtype(super_desc, sub_desc));

            /* Create variant 'b' with local tag 0 */
            QVariantVal v = { .tag = 0, .payload = (QVal){ .u = 0 } };
            QDynamic *d = quest_dynamic_new(sub_desc, (QVal){ .p = quest_variant_box(v) });

            /* Coerce to supervariant */
            QVal extracted = quest_dynamic_be(super_desc, d);
            QVariantVal *res_v = (QVariantVal *)extracted.p;
            assert(res_v != NULL);
            /* Tag must be remapped from 0 to 1! */
            assert(res_v->tag == 1);

            printf("VARIANT_SUBTYPING_OK\\n");
            return 0;
        }
        """
        proc = self.compile_and_run_c(c_code)
        self.assertEqual(proc.returncode, 0, f"Failed: {proc.stderr}")
        self.assertIn("VARIANT_SUBTYPING_OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()


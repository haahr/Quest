/*
 * Quest C Runtime ABI & Foundation Header
 * Part of Step 4: Bootstrap C Transpiler
 */

#ifndef QUEST_RUNTIME_H
#define QUEST_RUNTIME_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

/* Compile-time portable layout assertions */
#define Q_ASSERT_CONCAT_(a, b) a##b
#define Q_ASSERT_CONCAT(a, b)  Q_ASSERT_CONCAT_(a, b)

#ifndef static_assert
#  if defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L
#    define static_assert(cond, msg) _Static_assert(cond, #msg)
#  else
#    define static_assert(cond, msg)        typedef char Q_ASSERT_CONCAT(q_assert_##msg##_, __LINE__)[(cond) ? 1 : -1]
#  endif
#endif

/* 64-bit Universal Value Word (QVal) */
typedef int64_t QInt;
typedef double  QReal;
typedef bool    QBool;
typedef char    QChar;

typedef union QVal {
    void    *p;   /* Heap pointers: strings, arrays, records, tuples, closures */
    QInt     i;   /* 64-bit signed two's complement integer */
    QReal    r;   /* 64-bit IEEE-754 double precision float */
    uint64_t u;   /* 64-bit raw unsigned word for identity checks */
} QVal;

/* String representation: length-prefixed, null-terminated */
typedef struct QString {
    int64_t length;
    int64_t capacity;
    char   *data;
} QString;

/* First-class closure representation: function pointer and environment */
typedef struct QClosure {
    void *fn;   /* C function pointer */
    void *env;  /* Captured environment pointer or NULL */
} QClosure;

/* Array representation: length-prefixed buffer of 64-bit QVal words */
typedef struct QArray {
    int64_t length;
    QVal    data[];
} QArray;

/* Variant representation: tag and single 64-bit value word */
typedef struct QVariant {
    int64_t tag;
    QVal    payload;
} QVariant;

/* Generic Option header for inspections */
typedef struct QOptionHeader {
    int64_t tag;
    QVal    fields[];
} QOptionHeader;

/* Static ABI layout assertions */
static_assert(sizeof(QInt)     == 8, qint_must_be_8_bytes);
static_assert(sizeof(QReal)    == 8, qreal_must_be_8_bytes);
static_assert(sizeof(void *)   == 8, ptr_must_be_8_bytes);
static_assert(sizeof(QVal)     == 8, qval_must_be_8_bytes);
static_assert(sizeof(uint64_t) == 8, u64_must_be_8_bytes);
static_assert(sizeof(QString)  == 24, qstring_must_be_24_bytes);
static_assert(sizeof(QClosure) == 16, qclosure_must_be_16_bytes);
static_assert(sizeof(QVariant) == 16, qvariant_must_be_16_bytes);
static_assert(offsetof(QClosure, env) == 8, qclosure_env_at_offset_8);
static_assert(offsetof(QArray, data)  == 8, qarray_data_at_offset_8);
static_assert(offsetof(QVariant, payload) == 8, qvariant_payload_at_offset_8);
static_assert(offsetof(QOptionHeader, fields) == 8, qoptionheader_fields_at_offset_8);

/* Value constants */
#define Q_OK_VAL    ((QVal){ .u = 0 })
#define Q_TRUE_VAL  ((QVal){ .i = 1 })
#define Q_FALSE_VAL ((QVal){ .i = 0 })

/* Memory allocation abstraction */
#ifdef QUEST_NOGC
static inline void *quest_alloc(size_t sz)        { return calloc(1, sz); }
static inline void *quest_alloc_atomic(size_t sz) { return malloc(sz); }
static inline void  quest_gc_init(void)           { /* no-op */ }
#else
#  include <gc.h>
static inline void *quest_alloc(size_t sz)        { return GC_MALLOC(sz); }
static inline void *quest_alloc_atomic(size_t sz) { return GC_MALLOC_ATOMIC(sz); }
static inline void  quest_gc_init(void)           { GC_INIT(); }
#endif

/* Runtime helper prototypes */
QString *quest_string_new(const char *src, int64_t len);
QString *quest_string_concat(const QString *s1, const QString *s2);
bool     quest_string_equal(const QString *s1, const QString *s2);
QChar    quest_string_get_char(const QString *s, int64_t idx);
void     quest_string_set_char(QString *s, int64_t idx, QChar ch);
QString *quest_string_get_sub(const QString *s, int64_t start, int64_t len);
void     quest_string_set_sub(QString *dest, int64_t dest_start, const QString *src, int64_t src_start, int64_t len);

QArray  *quest_array_new(int64_t len, QVal init_val);
double   quest_real_pow(double base, double exp);
void     quest_raise_divide_by_zero(void);
void     quest_raise_array_error(void);
void     quest_raise_string_error(void);
void     quest_raise_variant_error(void);
void     quest_print_val(QVal val, const char *type_name);

static inline void quest_check_array_bounds(const QArray *a, int64_t idx) {
    if (a == NULL || idx < 0 || idx >= a->length) {
        quest_raise_array_error();
    }
}

static inline QInt quest_int_div(QInt a, QInt b) {
    if (b == 0) {
        quest_raise_divide_by_zero();
    }
    return a / b;
}

static inline QInt quest_int_mod(QInt a, QInt b) {
    if (b == 0) {
        quest_raise_divide_by_zero();
    }
    return a % b;
}

#endif /* QUEST_RUNTIME_H */

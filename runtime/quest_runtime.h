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
#include <setjmp.h>

#if defined(_MSC_VER)
#  define Q_THREAD_LOCAL __declspec(thread)
#elif defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L && !defined(__STDC_NO_THREADS__)
#  define Q_THREAD_LOCAL _Thread_local
#elif defined(__GNUC__) || defined(__clang__)
#  define Q_THREAD_LOCAL __thread
#else
#  define Q_THREAD_LOCAL
#endif

#if defined(__GNUC__) || defined(__clang__)
#  define Q_UNUSED __attribute__((unused))
#else
#  define Q_UNUSED
#endif

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

/* Record header for self-describing shape and identity */
typedef struct QRecordHeader {
    const void *descriptor;
} QRecordHeader;

/* First-class 16-byte record value: payload pointer and evidence dictionary */
typedef struct QRecordVal {
    void       *val;
    const void *dict;
} QRecordVal;

/* First-class 16-byte variant value: local tag index and payload value */
typedef struct QVariantVal {
    int64_t tag;
    QVal    payload;
} QVariantVal;

/* Wide array representations: length-prefixed buffers of 16-byte elements */
typedef struct QArrayWideRecord {
    int64_t    length;
    QRecordVal data[];
} QArrayWideRecord;

typedef struct QArrayWideVariant {
    int64_t     length;
    QVariantVal data[];
} QArrayWideVariant;

/* Standard I/O sink and source representations */
typedef struct QWriter {
    FILE *file;
    bool  is_file;
    bool  is_closed;
} QWriter;

typedef struct QReader {
    FILE *file;
    int   peek_char; /* EOF (-1) if no unread character */
    bool  is_file;
    bool  is_closed;
} QReader;

/* Legacy Variant representation: descriptor, tag and single 64-bit value word */
typedef struct QVariant {
    const void *descriptor;
    int64_t     tag;
    QVal        payload;
} QVariant;

/* Generic Option header for inspections */
typedef struct QOptionHeader {
    int64_t tag;
    QVal    fields[];
} QOptionHeader;

/* First-class generative exception descriptor */
typedef struct QException {
    const char *name;
} QException;

/* Runtime Type Descriptors (Intensional Type Analysis) */
typedef enum QTypeKind {
    QTYPE_KIND_INT,
    QTYPE_KIND_REAL,
    QTYPE_KIND_BOOL,
    QTYPE_KIND_CHAR,
    QTYPE_KIND_STRING,
    QTYPE_KIND_OK,
    QTYPE_KIND_TUPLE,
    QTYPE_KIND_RECORD,
    QTYPE_KIND_VARIANT,
    QTYPE_KIND_OPTION,
    QTYPE_KIND_ARRAY,
    QTYPE_KIND_FUN,
    QTYPE_KIND_DYNAMIC,
    QTYPE_KIND_EXCEPTION,
    QTYPE_KIND_OPAQUE
} QTypeKind;

typedef struct QTypeDescriptor QTypeDescriptor;

struct QTypeDescriptor {
    QTypeKind   kind;
    const char *name;
    size_t      size;
    size_t      alignment;
    bool      (*is_subtype)(const QTypeDescriptor *sub, const QTypeDescriptor *super_type);
    const void *extra;
};

/* Compound descriptor metadata */
typedef struct QArrayTypeDescriptor {
    const QTypeDescriptor *element_type;
} QArrayTypeDescriptor;

typedef struct QRecordFieldDescriptor {
    const char            *name;
    const QTypeDescriptor *type;
    size_t                 offset;
    bool                   is_var;
} QRecordFieldDescriptor;

typedef struct QRecordTypeDescriptor {
    size_t                       field_count;
    const QRecordFieldDescriptor fields[];
} QRecordTypeDescriptor;

/* First-class Dynamic object: type descriptor paired with 64-bit value */
typedef struct QDynamic {
    const QTypeDescriptor *type_desc;
    QVal                   payload;
} QDynamic;

/* Thread-local active exception state */
typedef struct QExceptionState {
    const QException *exc;
    QVal              payload;
} QExceptionState;

/* Linked node in thread-local exception handler stack */
typedef struct QExceptionHandler {
    jmp_buf                    env_jmp;
    struct QExceptionHandler  *prev;
} QExceptionHandler;

extern Q_THREAD_LOCAL QExceptionHandler *quest_current_exception_handler;
extern Q_THREAD_LOCAL QExceptionState    quest_current_exception;

/* Built-in singleton exception descriptors */
extern const QException quest_exc_DivideByZero;
extern const QException quest_exc_arrayOp_error;
extern const QException quest_exc_string_error;
extern const QException quest_exc_variant_error;
extern const QException quest_exc_dynamic_error;

/* Pre-allocated static type descriptors for base types */
extern const QTypeDescriptor quest_type_Int;
extern const QTypeDescriptor quest_type_Real;
extern const QTypeDescriptor quest_type_Bool;
extern const QTypeDescriptor quest_type_Char;
extern const QTypeDescriptor quest_type_String;
extern const QTypeDescriptor quest_type_Ok;
extern const QTypeDescriptor quest_type_Dynamic;
extern const QTypeDescriptor quest_type_EmptyTuple;

/* Static ABI layout assertions */
static_assert(sizeof(QInt)          == 8, qint_must_be_8_bytes);
static_assert(sizeof(QReal)         == 8, qreal_must_be_8_bytes);
static_assert(sizeof(void *)        == 8, ptr_must_be_8_bytes);
static_assert(sizeof(QVal)          == 8, qval_must_be_8_bytes);
static_assert(sizeof(uint64_t)      == 8, u64_must_be_8_bytes);
static_assert(sizeof(QString)       == 24, qstring_must_be_24_bytes);
static_assert(sizeof(QClosure)      == 16, qclosure_must_be_16_bytes);
static_assert(sizeof(QRecordHeader) == 8, qrecord_header_must_be_8_bytes);
static_assert(sizeof(QRecordVal)    == 16, qrecordval_must_be_16_bytes);
static_assert(offsetof(QRecordVal, dict) == 8, qrecordval_dict_at_offset_8);
static_assert(sizeof(QVariantVal)          == 16, qvariantval_must_be_16_bytes);
static_assert(offsetof(QVariantVal, tag)     == 0,  qvariantval_tag_at_offset_0);
static_assert(offsetof(QVariantVal, payload) == 8,  qvariantval_payload_at_offset_8);
static_assert(sizeof(QVariant)      == 24, qvariant_must_be_24_bytes);
static_assert(sizeof(QException)    == 8, qexception_must_be_8_bytes);
static_assert(sizeof(QExceptionState) == 16, qexception_state_must_be_16_bytes);
static_assert(offsetof(QClosure, env) == 8, qclosure_env_at_offset_8);
static_assert(offsetof(QArray, data)  == 8, qarray_data_at_offset_8);
static_assert(offsetof(QArrayWideRecord, data)  == 8, qarray_wide_rec_data_at_offset_8);
static_assert(offsetof(QArrayWideVariant, data) == 8, qarray_wide_var_data_at_offset_8);
static_assert(offsetof(QVariant, tag)     == 8, qvariant_tag_at_offset_8);
static_assert(offsetof(QVariant, payload) == 16, qvariant_payload_at_offset_16);
static_assert(offsetof(QOptionHeader, fields) == 8, qoptionheader_fields_at_offset_8);
static_assert(offsetof(QExceptionState, payload) == 8, qexception_state_payload_at_offset_8);

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
QString *quest_string_alloc(int64_t size, QChar init);
bool     quest_string_is_empty(const QString *s);
int64_t  quest_string_length(const QString *s);
QString *quest_string_concat(const QString *s1, const QString *s2);
bool     quest_string_equal(const QString *s1, const QString *s2);
QChar    quest_string_get_char(const QString *s, int64_t idx);
void     quest_string_set_char(QString *s, int64_t idx, QChar ch);
QString *quest_string_get_sub(const QString *s, int64_t start, int64_t len);
void     quest_string_set_sub(QString *dest, int64_t dest_start, const QString *src, int64_t src_start, int64_t len);
QString *quest_string_cat_sub(const QString *s1, int64_t st1, int64_t sz1,
                              const QString *s2, int64_t st2, int64_t sz2);
QString *quest_string_conc(const QArray *strings);
bool     quest_string_equal_sub(const QString *s1, int64_t st1, int64_t sz1,
                                const QString *s2, int64_t st2, int64_t sz2);
bool     quest_string_precedes(const QString *s1, const QString *s2);
bool     quest_string_precedes_sub(const QString *s1, int64_t st1, int64_t sz1,
                                   const QString *s2, int64_t st2, int64_t sz2);

QArray  *quest_array_new(int64_t len, QVal init_val);
QArrayWideRecord  *quest_array_new_wide_record(int64_t len, QRecordVal init_val);
QArrayWideVariant *quest_array_new_wide_variant(int64_t len, QVariantVal init_val);
int64_t  quest_array_size(const QArray *a);
double   quest_real_pow(double base, double exp);
const QException *quest_alloc_exception(const char *name);
void     quest_raise(const QException *exc, QVal payload);
void     quest_raise_divide_by_zero(void);
void     quest_raise_array_error(void);
void     quest_raise_string_error(void);
void     quest_raise_variant_error(void);
void     quest_raise_dynamic_error(void);
void     quest_print_val(QVal val, const char *type_name);

/* Standard library singleton exceptions */
extern const QException quest_exc_writer_error;
extern const QException quest_exc_reader_error;
extern const QException quest_exc_ascii_error;
extern const QException quest_exc_int_error;
extern const QException quest_exc_real_error;
extern const QException quest_exc_system_error;

void quest_raise_writer_error(void);
void quest_raise_reader_error(void);
void quest_raise_ascii_error(void);
void quest_raise_int_error(void);
void quest_raise_real_error(void);
void quest_raise_system_error(void);

/* System module primitives */
extern QArray *quest_system_args;
void     quest_system_init(int argc, char **argv);
void     quest_system_exit(int64_t code);
QString *quest_system_getenv(const QString *var);
bool     quest_system_file_exists(const QString *path);

/* Writer module primitives */
extern QWriter quest_writer_output_val;
extern QWriter quest_writer_err_val;
#define quest_writer_output (&quest_writer_output_val)
#define quest_writer_err    (&quest_writer_err_val)

QWriter *quest_writer_file(const QString *name);
void     quest_writer_put_string(QWriter *w, const QString *s);
void     quest_writer_put_char(QWriter *w, QChar ch);
void     quest_writer_put_substring(QWriter *w, const QString *s, int64_t start, int64_t size);
void     quest_writer_flush(QWriter *w);
void     quest_writer_close(QWriter *w);

/* Reader module primitives */
extern QReader quest_reader_input_val;
#define quest_reader_input (&quest_reader_input_val)

QReader *quest_reader_file(const QString *name);
bool     quest_reader_more(QReader *r);
bool     quest_reader_ready(QReader *r);
QChar    quest_reader_get_char(QReader *r);
QString *quest_reader_get_string(QReader *r, int64_t size);
void     quest_reader_get_substring(QReader *r, QString *s, int64_t start, int64_t size);
void     quest_reader_close(QReader *r);

/* Conv module primitives */
QString *quest_conv_okay(void);
QString *quest_conv_bool(bool b);
QString *quest_conv_int(int64_t n);
QString *quest_conv_real(double r);
QString *quest_conv_char(QChar ch);
QString *quest_conv_string(const QString *s);

/* Ascii module primitives */
QChar   quest_ascii_char(int64_t n);
int64_t quest_ascii_val(QChar ch);

/* IntOp constants & primitives */
#define QUEST_INT_MIN (-9223372036854775807LL - 1LL)
#define QUEST_INT_MAX (9223372036854775807LL)

static inline int64_t quest_int_abs(int64_t n) {
    if (n == QUEST_INT_MIN) return QUEST_INT_MIN;
    return n < 0 ? -n : n;
}
static inline int64_t quest_int_min(int64_t a, int64_t b) { return a < b ? a : b; }
static inline int64_t quest_int_max(int64_t a, int64_t b) { return a > b ? a : b; }

/* RealOp constants & primitives */
#define QUEST_REAL_MIN (-1.7976931348623157e+308)
#define QUEST_REAL_MAX (1.7976931348623157e+308)
#define QUEST_REAL_POS_EPSILON (2.2204460492503131e-16)
#define QUEST_REAL_NEG_EPSILON (-2.2204460492503131e-16)
#define QUEST_REAL_E (2.71828182845904523536)

double  quest_real_from_int(int64_t n);
double  quest_real_log(double r);
int64_t quest_real_floor(double r);
int64_t quest_real_round(double r);
static inline double quest_real_abs(double r) { return fabs(r); }
static inline double quest_real_min(double a, double b) { return a < b ? a : b; }
static inline double quest_real_max(double a, double b) { return a > b ? a : b; }
double  quest_real_div(double a, double b);
double  quest_real_exp(double a, double b);

/* Global standard library initialization */
void quest_builtins_init(int argc, char **argv);

/* Type descriptor interning and dynamic operations */
const QTypeDescriptor *quest_intern_type_descriptor(const QTypeDescriptor *desc);
const QTypeDescriptor *quest_make_array_descriptor(const QTypeDescriptor *element_desc);
const QTypeDescriptor *quest_make_opaque_descriptor(const char *name);
QDynamic              *quest_dynamic_new(const QTypeDescriptor *type_desc, QVal val);
QVal                   quest_dynamic_be(const QTypeDescriptor *target_type_desc, const QDynamic *d);

static inline QRecordVal *quest_record_box(QRecordVal rec) {
    QRecordVal *box = (QRecordVal *)quest_alloc(sizeof(QRecordVal));
    *box = rec;
    return box;
}

static inline QVariantVal *quest_variant_box(QVariantVal var) {
    QVariantVal *box = (QVariantVal *)quest_alloc(sizeof(QVariantVal));
    *box = var;
    return box;
}

static inline void quest_check_array_bounds(const void *arr_ptr, int64_t idx) {
    const QArray *a = (const QArray *)arr_ptr;
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

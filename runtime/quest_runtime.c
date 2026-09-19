/*
 * Quest C Runtime Implementation
 * Part of Step 4: Bootstrap C Transpiler
 */

#include "quest_runtime.h"

QString *quest_string_new(const char *src, int64_t len) {
    if (len < 0 && src != NULL) {
        len = (int64_t)strlen(src);
    }
    QString *s = (QString *)quest_alloc(sizeof(QString));
    s->length = len;
    s->capacity = len;
    s->data = (char *)quest_alloc_atomic(len + 1);
    if (len > 0 && src != NULL) {
        memcpy(s->data, src, (size_t)len);
    }
    s->data[len] = 0;
    return s;
}

QString *quest_string_concat(const QString *s1, const QString *s2) {
    if (s1 == NULL && s2 == NULL) return quest_string_new("", 0);
    if (s1 == NULL) return quest_string_new(s2->data, s2->length);
    if (s2 == NULL) return quest_string_new(s1->data, s1->length);

    int64_t total = s1->length + s2->length;
    QString *res = (QString *)quest_alloc(sizeof(QString));
    res->length = total;
    res->capacity = total;
    res->data = (char *)quest_alloc_atomic(total + 1);
    if (s1->length > 0) {
        memcpy(res->data, s1->data, (size_t)s1->length);
    }
    if (s2->length > 0) {
        memcpy(res->data + s1->length, s2->data, (size_t)s2->length);
    }
    res->data[total] = 0;
    return res;
}

bool quest_string_equal(const QString *s1, const QString *s2) {
    if (s1 == s2) return true;
    if (s1 == NULL || s2 == NULL) return false;
    if (s1->length != s2->length) return false;
    return memcmp(s1->data, s2->data, (size_t)s1->length) == 0;
}

QChar quest_string_get_char(const QString *s, int64_t idx) {
    if (s == NULL || idx < 0 || idx >= s->length) {
        quest_raise_string_error();
    }
    return s->data[idx];
}

void quest_string_set_char(QString *s, int64_t idx, QChar ch) {
    if (s == NULL || idx < 0 || idx >= s->length) {
        quest_raise_string_error();
    }
    s->data[idx] = ch;
}

QString *quest_string_get_sub(const QString *s, int64_t start, int64_t len) {
    if (s == NULL || start < 0 || len < 0 || start + len > s->length) {
        quest_raise_string_error();
    }
    return quest_string_new(s->data + start, len);
}

void quest_string_set_sub(QString *dest, int64_t dest_start, const QString *src, int64_t src_start, int64_t len) {
    if (dest == NULL || src == NULL || len < 0 ||
        dest_start < 0 || dest_start + len > dest->length ||
        src_start < 0 || src_start + len > src->length) {
        quest_raise_string_error();
    }
    if (len > 0) {
        memmove(dest->data + dest_start, src->data + src_start, (size_t)len);
    }
}

QString *quest_string_alloc(int64_t size, QChar init) {
    if (size < 0) {
        quest_raise_string_error();
    }
    char *buf = (char *)quest_alloc((size_t)size + 1);
    memset(buf, (int)init, (size_t)size);
    buf[size] = '\0';
    return quest_string_new(buf, size);
}

bool quest_string_is_empty(const QString *s) {
    return s == NULL || s->length == 0;
}

QString *quest_string_cat_sub(const QString *s1, int64_t st1, int64_t sz1,
                              const QString *s2, int64_t st2, int64_t sz2) {
    if (s1 == NULL || s2 == NULL || st1 < 0 || sz1 < 0 || st1 + sz1 > s1->length ||
        st2 < 0 || sz2 < 0 || st2 + sz2 > s2->length) {
        quest_raise_string_error();
    }
    int64_t total = sz1 + sz2;
    char *buf = (char *)quest_alloc((size_t)total + 1);
    if (sz1 > 0) memcpy(buf, s1->data + st1, (size_t)sz1);
    if (sz2 > 0) memcpy(buf + sz1, s2->data + st2, (size_t)sz2);
    buf[total] = '\0';
    return quest_string_new(buf, total);
}

QString *quest_string_conc(const QArray *strings) {
    if (strings == NULL) {
        quest_raise_string_error();
    }
    int64_t total = 0;
    for (int64_t i = 0; i < strings->length; ++i) {
        const QString *part = (const QString *)strings->data[i].p;
        if (part != NULL) {
            total += part->length;
        }
    }
    char *buf = (char *)quest_alloc((size_t)total + 1);
    int64_t offset = 0;
    for (int64_t i = 0; i < strings->length; ++i) {
        const QString *part = (const QString *)strings->data[i].p;
        if (part != NULL && part->length > 0) {
            memcpy(buf + offset, part->data, (size_t)part->length);
            offset += part->length;
        }
    }
    buf[total] = '\0';
    return quest_string_new(buf, total);
}

bool quest_string_equal_sub(const QString *s1, int64_t st1, int64_t sz1,
                            const QString *s2, int64_t st2, int64_t sz2) {
    if (s1 == NULL || s2 == NULL || st1 < 0 || sz1 < 0 || st1 + sz1 > s1->length ||
        st2 < 0 || sz2 < 0 || st2 + sz2 > s2->length) {
        quest_raise_string_error();
    }
    if (sz1 != sz2) return false;
    if (sz1 == 0) return true;
    return memcmp(s1->data + st1, s2->data + st2, (size_t)sz1) == 0;
}

bool quest_string_precedes(const QString *s1, const QString *s2) {
    if (s1 == NULL || s2 == NULL) {
        quest_raise_string_error();
    }
    int64_t min_len = s1->length < s2->length ? s1->length : s2->length;
    int cmp = 0;
    if (min_len > 0) {
        cmp = memcmp(s1->data, s2->data, (size_t)min_len);
    }
    if (cmp != 0) return cmp < 0;
    return s1->length <= s2->length;
}

bool quest_string_precedes_sub(const QString *s1, int64_t st1, int64_t sz1,
                               const QString *s2, int64_t st2, int64_t sz2) {
    if (s1 == NULL || s2 == NULL || st1 < 0 || sz1 < 0 || st1 + sz1 > s1->length ||
        st2 < 0 || sz2 < 0 || st2 + sz2 > s2->length) {
        quest_raise_string_error();
    }
    int64_t min_len = sz1 < sz2 ? sz1 : sz2;
    int cmp = 0;
    if (min_len > 0) {
        cmp = memcmp(s1->data + st1, s2->data + st2, (size_t)min_len);
    }
    if (cmp != 0) return cmp < 0;
    return sz1 <= sz2;
}

QArray *quest_array_new(int64_t len, QVal init_val) {
    if (len < 0) {
        quest_raise_array_error();
    }
    QArray *arr = (QArray *)quest_alloc(sizeof(QArray) + (size_t)len * sizeof(QVal));
    arr->length = len;
    for (int64_t i = 0; i < len; ++i) {
        arr->data[i] = init_val;
    }
    return arr;
}

QArrayWideRecord *quest_array_new_wide_record(int64_t len, QRecordVal init_val) {
    if (len < 0) {
        quest_raise_array_error();
    }
    QArrayWideRecord *arr = (QArrayWideRecord *)quest_alloc(
        sizeof(QArrayWideRecord) + (size_t)len * sizeof(QRecordVal)
    );
    arr->length = len;
    for (int64_t i = 0; i < len; ++i) {
        arr->data[i] = init_val;
    }
    return arr;
}

QArrayWideVariant *quest_array_new_wide_variant(int64_t len, QVariantVal init_val) {
    if (len < 0) {
        quest_raise_array_error();
    }
    QArrayWideVariant *arr = (QArrayWideVariant *)quest_alloc(
        sizeof(QArrayWideVariant) + (size_t)len * sizeof(QVariantVal)
    );
    arr->length = len;
    for (int64_t i = 0; i < len; ++i) {
        arr->data[i] = init_val;
    }
    return arr;
}

double quest_real_pow(double base, double exp) {
    if (base == 0.0 && exp <= 0.0) {
        quest_raise_divide_by_zero();
    }
    return pow(base, exp);
}

/* Exception handling globals */
Q_THREAD_LOCAL QExceptionHandler *quest_current_exception_handler = NULL;
Q_THREAD_LOCAL QExceptionState    quest_current_exception = { NULL, { .u = 0 } };

/* Built-in singleton exception descriptors */
const QException quest_exc_DivideByZero  = { "DivideByZero" };
const QException quest_exc_arrayOp_error = { "arrayOp.error" };
const QException quest_exc_string_error  = { "string.error" };
const QException quest_exc_variant_error = { "variant.tagMismatch" };
const QException quest_exc_dynamic_error = { "dynamic.error" };
const QException quest_exc_writer_error  = { "writer.error" };
const QException quest_exc_reader_error  = { "reader.error" };
const QException quest_exc_ascii_error   = { "ascii.error" };
const QException quest_exc_int_error     = { "int.error" };
const QException quest_exc_real_error    = { "real.error" };
const QException quest_exc_system_error  = { "system.error" };

const QException *quest_alloc_exception(const char *name) {
    QException *exc = (QException *)quest_alloc(sizeof(QException));
    exc->name = name ? name : "Exception";
    return exc;
}

void quest_raise(const QException *exc, QVal payload) {
    if (quest_current_exception_handler == NULL) {
        const char *name = (exc != NULL && exc->name != NULL) ? exc->name : "<unknown>";
        fprintf(stderr, "Exception: %s\n", name);
        exit(1);
    }
    quest_current_exception.exc = exc;
    quest_current_exception.payload = payload;
    longjmp(quest_current_exception_handler->env_jmp, 1);
}

void quest_raise_divide_by_zero(void) {
    quest_raise(&quest_exc_DivideByZero, Q_OK_VAL);
}

void quest_raise_array_error(void) {
    quest_raise(&quest_exc_arrayOp_error, Q_OK_VAL);
}

void quest_raise_string_error(void) {
    quest_raise(&quest_exc_string_error, Q_OK_VAL);
}

void quest_raise_variant_error(void) {
    quest_raise(&quest_exc_variant_error, Q_OK_VAL);
}

void quest_raise_dynamic_error(void) {
    quest_raise(&quest_exc_dynamic_error, Q_OK_VAL);
}

void quest_raise_writer_error(void) {
    quest_raise(&quest_exc_writer_error, Q_OK_VAL);
}

void quest_raise_reader_error(void) {
    quest_raise(&quest_exc_reader_error, Q_OK_VAL);
}

void quest_raise_ascii_error(void) {
    quest_raise(&quest_exc_ascii_error, Q_OK_VAL);
}

void quest_raise_int_error(void) {
    quest_raise(&quest_exc_int_error, Q_OK_VAL);
}

void quest_raise_real_error(void) {
    quest_raise(&quest_exc_real_error, Q_OK_VAL);
}

void quest_raise_system_error(void) {
    quest_raise(&quest_exc_system_error, Q_OK_VAL);
}

void quest_print_val(QVal val, const char *type_name) {
    if (type_name == NULL) return;
    if (strcmp(type_name, "Ok") == 0) {
        return;
    }
    if (strcmp(type_name, "Int") == 0) {
        printf("%lld : Int\n", (long long)val.i);
        return;
    }
    if (strcmp(type_name, "Real") == 0) {
        if (val.r == (double)(int64_t)val.r) {
            printf("%.1f : Real\n", val.r);
        } else {
            printf("%g : Real\n", val.r);
        }
        return;
    }
    if (strcmp(type_name, "Bool") == 0) {
        printf("%s : Bool\n", val.i ? "true" : "false");
        return;
    }
    if (strcmp(type_name, "Char") == 0) {
        printf("'%c' : Char\n", (char)val.i);
        return;
    }
    if (strcmp(type_name, "String") == 0) {
        QString *s = (QString *)val.p;
        printf("\"%s\" : String\n", s ? s->data : "");
        return;
    }
    printf("<val> : %s\n", type_name);
}

/* Base type subtyping predicate: initially canonical pointer equality */
static bool quest_base_is_subtype(const QTypeDescriptor *sub, const QTypeDescriptor *super_type) {
    if (sub == super_type) return true;
    /* EmptyTuple ("Tuple end") is the top type of kind TYPE in Cardelli Quest */
    if (super_type == &quest_type_EmptyTuple) return true;
    return false;
}

/* Statically pre-allocated base type descriptors */
const QTypeDescriptor quest_type_Int = {
    .kind = QTYPE_KIND_INT,
    .name = "Int",
    .size = sizeof(QInt),
    .alignment = sizeof(QInt),
    .is_subtype = quest_base_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_Real = {
    .kind = QTYPE_KIND_REAL,
    .name = "Real",
    .size = sizeof(QReal),
    .alignment = sizeof(QReal),
    .is_subtype = quest_base_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_Bool = {
    .kind = QTYPE_KIND_BOOL,
    .name = "Bool",
    .size = sizeof(QInt),
    .alignment = sizeof(QInt),
    .is_subtype = quest_base_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_Char = {
    .kind = QTYPE_KIND_CHAR,
    .name = "Char",
    .size = sizeof(QInt),
    .alignment = sizeof(QInt),
    .is_subtype = quest_base_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_String = {
    .kind = QTYPE_KIND_STRING,
    .name = "String",
    .size = sizeof(void *),
    .alignment = sizeof(void *),
    .is_subtype = quest_base_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_Ok = {
    .kind = QTYPE_KIND_OK,
    .name = "Ok",
    .size = sizeof(QInt),
    .alignment = sizeof(QInt),
    .is_subtype = quest_base_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_Dynamic = {
    .kind = QTYPE_KIND_DYNAMIC,
    .name = "Dynamic",
    .size = sizeof(void *),
    .alignment = sizeof(void *),
    .is_subtype = quest_base_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_EmptyTuple = {
    .kind = QTYPE_KIND_TUPLE,
    .name = "Tuple end",
    .size = sizeof(void *),
    .alignment = sizeof(void *),
    .is_subtype = quest_base_is_subtype,
    .extra = NULL
};

/* Global Interning Table for Type Descriptors */
typedef struct QTypeDescriptorEntry {
    const QTypeDescriptor       *desc;
    struct QTypeDescriptorEntry *next;
} QTypeDescriptorEntry;

#define Q_TYPE_INTERN_TABLE_SIZE 256
static QTypeDescriptorEntry *quest_type_intern_buckets[Q_TYPE_INTERN_TABLE_SIZE];
static bool quest_type_intern_initialized = false;

/* FNV-1a 64-bit hash for descriptor canonical names */
static uint64_t quest_hash_string(const char *s) {
    uint64_t h = 14695981039346656037ULL;
    if (s == NULL) return h;
    for (; *s; ++s) {
        h ^= (uint64_t)(unsigned char)(*s);
        h *= 1099511628211ULL;
    }
    return h;
}

static void quest_init_type_intern_table(void) {
    if (quest_type_intern_initialized) return;
    quest_type_intern_initialized = true;

    /* Register base types in table */
    const QTypeDescriptor *base_descs[] = {
        &quest_type_Int,
        &quest_type_Real,
        &quest_type_Bool,
        &quest_type_Char,
        &quest_type_String,
        &quest_type_Ok,
        &quest_type_Dynamic,
        &quest_type_EmptyTuple,
        NULL
    };

    for (int i = 0; base_descs[i] != NULL; ++i) {
        const QTypeDescriptor *d = base_descs[i];
        uint64_t h = quest_hash_string(d->name) % Q_TYPE_INTERN_TABLE_SIZE;
        QTypeDescriptorEntry *entry = (QTypeDescriptorEntry *)quest_alloc(sizeof(QTypeDescriptorEntry));
        entry->desc = d;
        entry->next = quest_type_intern_buckets[h];
        quest_type_intern_buckets[h] = entry;
    }
}

const QTypeDescriptor *quest_intern_type_descriptor(const QTypeDescriptor *desc) {
    if (desc == NULL) return NULL;
    quest_init_type_intern_table();

    /* Check if already in table by canonical name match */
    uint64_t h = quest_hash_string(desc->name) % Q_TYPE_INTERN_TABLE_SIZE;
    for (QTypeDescriptorEntry *cur = quest_type_intern_buckets[h]; cur != NULL; cur = cur->next) {
        if (cur->desc == desc) {
            return cur->desc;
        }
        if (cur->desc->name != NULL && desc->name != NULL && strcmp(cur->desc->name, desc->name) == 0) {
            return cur->desc;
        }
    }

    /* Not found: insert into bucket */
    QTypeDescriptorEntry *entry = (QTypeDescriptorEntry *)quest_alloc(sizeof(QTypeDescriptorEntry));
    entry->desc = desc;
    entry->next = quest_type_intern_buckets[h];
    quest_type_intern_buckets[h] = entry;
    return desc;
}

/* Array subtyping: Cardelli arrays are invariant in their element type */
static bool quest_array_is_subtype(const QTypeDescriptor *sub, const QTypeDescriptor *super_type) {
    if (sub == super_type) return true;
    if (super_type == &quest_type_EmptyTuple) return true;
    if (sub == NULL || super_type == NULL) return false;
    if (super_type->kind != QTYPE_KIND_ARRAY) return false;

    const QArrayTypeDescriptor *sub_arr = (const QArrayTypeDescriptor *)sub->extra;
    const QArrayTypeDescriptor *sup_arr = (const QArrayTypeDescriptor *)super_type->extra;
    if (sub_arr == NULL || sup_arr == NULL) return false;

    /* Invariance check: element types must be identical descriptors */
    return sub_arr->element_type == sup_arr->element_type;
}

const QTypeDescriptor *quest_make_array_descriptor(const QTypeDescriptor *element_desc) {
    quest_init_type_intern_table();

    const char *elem_name = (element_desc && element_desc->name) ? element_desc->name : "Unknown";
    size_t name_len = strlen("Array()") + strlen(elem_name) + 1;
    char *arr_name = (char *)quest_alloc_atomic(name_len);
    snprintf(arr_name, name_len, "Array(%s)", elem_name);

    /* Check if already interned */
    uint64_t h = quest_hash_string(arr_name) % Q_TYPE_INTERN_TABLE_SIZE;
    for (QTypeDescriptorEntry *cur = quest_type_intern_buckets[h]; cur != NULL; cur = cur->next) {
        if (cur->desc->name != NULL && strcmp(cur->desc->name, arr_name) == 0) {
            return cur->desc;
        }
    }

    /* Allocate array descriptor */
    QTypeDescriptor *desc = (QTypeDescriptor *)quest_alloc(sizeof(QTypeDescriptor));
    desc->kind = QTYPE_KIND_ARRAY;
    desc->name = arr_name;
    desc->size = sizeof(void *);
    desc->alignment = sizeof(void *);
    desc->is_subtype = quest_array_is_subtype;

    QArrayTypeDescriptor *arr_meta = (QArrayTypeDescriptor *)quest_alloc(sizeof(QArrayTypeDescriptor));
    arr_meta->element_type = element_desc;
    desc->extra = arr_meta;

    return quest_intern_type_descriptor(desc);
}

const QTypeDescriptor *quest_make_opaque_descriptor(const char *name) {
    /* Opaque types use unique pointer identity for encapsulation */
    QTypeDescriptor *desc = (QTypeDescriptor *)quest_alloc(sizeof(QTypeDescriptor));
    desc->kind = QTYPE_KIND_OPAQUE;
    if (name != NULL) {
        size_t len = strlen(name);
        char *n = (char *)quest_alloc_atomic(len + 1);
        memcpy(n, name, len + 1);
        desc->name = n;
    } else {
        desc->name = "Opaque";
    }
    desc->size = sizeof(QVal);
    desc->alignment = sizeof(QVal);
    desc->is_subtype = quest_base_is_subtype;
    desc->extra = NULL;
    /* Do NOT intern: each opaque type creation has unique nominal identity */
    return desc;
}

QDynamic *quest_dynamic_new(const QTypeDescriptor *type_desc, QVal val) {
    QDynamic *d = (QDynamic *)quest_alloc(sizeof(QDynamic));
    d->type_desc = type_desc;
    d->payload = val;
    return d;
}

QVal quest_dynamic_be(const QTypeDescriptor *target_type_desc, const QDynamic *d) {
    if (d == NULL || d->type_desc == NULL || target_type_desc == NULL) {
        quest_raise_dynamic_error();
    }
    /* Check exact pointer identity or subtyping predicate */
    if (d->type_desc == target_type_desc) {
        return d->payload;
    }
    if (target_type_desc->is_subtype != NULL && target_type_desc->is_subtype(d->type_desc, target_type_desc)) {
        return d->payload;
    }
    /* Type mismatch */
    quest_raise_dynamic_error();
    return (QVal){ .u = 0 }; /* Unreachable */
}

/* ------------------------------------------------------------------------- */
/* Standard Library Implementation                                           */
/* ------------------------------------------------------------------------- */

#include <unistd.h>

/* System module primitives */
QArray *quest_system_args = NULL;

void quest_system_init(int argc, char **argv) {
    if (argc < 0) argc = 0;
    quest_system_args = quest_array_new(argc, (QVal){ .p = NULL });
    for (int i = 0; i < argc; i++) {
        const char *arg = (argv != NULL && argv[i] != NULL) ? argv[i] : "";
        quest_system_args->data[i].p = quest_string_new(arg, (int64_t)strlen(arg));
    }
}

void quest_system_exit(int64_t code) {
    exit((int)code);
}

QString *quest_system_getenv(const QString *var) {
    if (var == NULL || var->data == NULL) return quest_string_new("", 0);
    const char *val = getenv(var->data);
    if (val == NULL) {
        return quest_string_new("", 0);
    }
    return quest_string_new(val, (int64_t)strlen(val));
}

bool quest_system_file_exists(const QString *path) {
    if (path == NULL || path->data == NULL) return false;
    return access(path->data, F_OK) == 0;
}

/* Writer module primitives */
QWriter quest_writer_output_val = { NULL, false, false };
QWriter quest_writer_err_val    = { NULL, false, false };

static void quest_writer_init_std(void) {
    if (quest_writer_output_val.file == NULL) {
        quest_writer_output_val.file = stdout;
        quest_writer_output_val.is_file = false;
        quest_writer_output_val.is_closed = false;
    }
    if (quest_writer_err_val.file == NULL) {
        quest_writer_err_val.file = stderr;
        quest_writer_err_val.is_file = false;
        quest_writer_err_val.is_closed = false;
    }
}

QWriter *quest_writer_file(const QString *name) {
    if (name == NULL || name->data == NULL) {
        quest_raise_writer_error();
    }
    FILE *f = fopen(name->data, "w");
    if (f == NULL) {
        quest_raise_writer_error();
    }
    QWriter *w = (QWriter *)quest_alloc(sizeof(QWriter));
    w->file = f;
    w->is_file = true;
    w->is_closed = false;
    return w;
}

void quest_writer_put_string(QWriter *w, const QString *s) {
    if (w == NULL || w->is_closed || w->file == NULL || s == NULL) {
        quest_raise_writer_error();
    }
    if (s->length > 0) {
        size_t written = fwrite(s->data, 1, (size_t)s->length, w->file);
        if (written != (size_t)s->length) {
            quest_raise_writer_error();
        }
    }
}

void quest_writer_put_char(QWriter *w, QChar ch) {
    if (w == NULL || w->is_closed || w->file == NULL) {
        quest_raise_writer_error();
    }
    if (fputc((int)ch, w->file) == EOF) {
        quest_raise_writer_error();
    }
}

void quest_writer_put_substring(QWriter *w, const QString *s, int64_t start, int64_t size) {
    if (w == NULL || w->is_closed || w->file == NULL || s == NULL) {
        quest_raise_writer_error();
    }
    if (start < 0 || size < 0 || start + size > s->length) {
        quest_raise_writer_error();
    }
    if (size > 0) {
        size_t written = fwrite(s->data + start, 1, (size_t)size, w->file);
        if (written != (size_t)size) {
            quest_raise_writer_error();
        }
    }
}

void quest_writer_flush(QWriter *w) {
    if (w == NULL || w->is_closed || w->file == NULL) {
        quest_raise_writer_error();
    }
    if (fflush(w->file) != 0) {
        quest_raise_writer_error();
    }
}

void quest_writer_close(QWriter *w) {
    if (w == NULL) {
        quest_raise_writer_error();
    }
    if (!w->is_closed) {
        if (w->is_file && w->file != NULL) {
            fclose(w->file);
        } else if (w->file != NULL) {
            fflush(w->file);
        }
        w->is_closed = true;
    }
}

/* Reader module primitives */
QReader quest_reader_input_val = { NULL, -1, false, false };

static void quest_reader_init_std(void) {
    if (quest_reader_input_val.file == NULL) {
        quest_reader_input_val.file = stdin;
        quest_reader_input_val.peek_char = -1;
        quest_reader_input_val.is_file = false;
        quest_reader_input_val.is_closed = false;
    }
}

QReader *quest_reader_file(const QString *name) {
    if (name == NULL || name->data == NULL) {
        quest_raise_reader_error();
    }
    FILE *f = fopen(name->data, "r");
    if (f == NULL) {
        quest_raise_reader_error();
    }
    QReader *r = (QReader *)quest_alloc(sizeof(QReader));
    r->file = f;
    r->peek_char = -1;
    r->is_file = true;
    r->is_closed = false;
    return r;
}

bool quest_reader_more(QReader *r) {
    if (r == NULL || r->is_closed || r->file == NULL) {
        quest_raise_reader_error();
    }
    if (r->peek_char != -1) {
        return true;
    }
    int ch = fgetc(r->file);
    if (ch == EOF) {
        return false;
    }
    r->peek_char = ch;
    return true;
}

bool quest_reader_ready(QReader *r) {
    if (r == NULL || r->is_closed || r->file == NULL) {
        quest_raise_reader_error();
    }
    return quest_reader_more(r);
}

QChar quest_reader_get_char(QReader *r) {
    if (r == NULL || r->is_closed || r->file == NULL) {
        quest_raise_reader_error();
    }
    int ch;
    if (r->peek_char != -1) {
        ch = r->peek_char;
        r->peek_char = -1;
    } else {
        ch = fgetc(r->file);
    }
    if (ch == EOF) {
        quest_raise_reader_error();
    }
    return (QChar)(unsigned char)ch;
}

QString *quest_reader_get_string(QReader *r, int64_t size) {
    if (r == NULL || r->is_closed || r->file == NULL || size < 0) {
        quest_raise_reader_error();
    }
    if (size == 0) {
        return quest_string_new("", 0);
    }
    char *buf = (char *)quest_alloc_atomic((size_t)size + 1);
    int64_t count = 0;
    if (r->peek_char != -1) {
        buf[count++] = (char)r->peek_char;
        r->peek_char = -1;
    }
    if (count < size) {
        size_t n = fread(buf + count, 1, (size_t)(size - count), r->file);
        count += (int64_t)n;
    }
    buf[count] = 0;
    QString *res = (QString *)quest_alloc(sizeof(QString));
    res->length = count;
    res->capacity = count;
    res->data = buf;
    return res;
}

void quest_reader_get_substring(QReader *r, QString *s, int64_t start, int64_t size) {
    if (r == NULL || r->is_closed || r->file == NULL || s == NULL ||
        start < 0 || size < 0 || start + size > s->length) {
        quest_raise_reader_error();
    }
    if (size == 0) return;
    int64_t count = 0;
    if (r->peek_char != -1) {
        s->data[start + count++] = (char)r->peek_char;
        r->peek_char = -1;
    }
    if (count < size) {
        size_t n = fread(s->data + start + count, 1, (size_t)(size - count), r->file);
        if ((int64_t)n < size - count) {
            quest_raise_reader_error();
        }
    }
}

void quest_reader_close(QReader *r) {
    if (r == NULL) {
        quest_raise_reader_error();
    }
    if (!r->is_closed) {
        if (r->is_file && r->file != NULL) {
            fclose(r->file);
        }
        r->is_closed = true;
        r->peek_char = -1;
    }
}

/* Conv module primitives */
QString *quest_conv_okay(void) {
    return quest_string_new("ok", 2);
}

QString *quest_conv_bool(bool b) {
    return b ? quest_string_new("true", 4) : quest_string_new("false", 5);
}

QString *quest_conv_int(int64_t n) {
    char buf[64];
    if (n < 0) {
        if (n == QUEST_INT_MIN) {
            snprintf(buf, sizeof(buf), "~9223372036854775808");
        } else {
            snprintf(buf, sizeof(buf), "~%lld", (long long)-n);
        }
    } else {
        snprintf(buf, sizeof(buf), "%lld", (long long)n);
    }
    return quest_string_new(buf, (int64_t)strlen(buf));
}

QString *quest_conv_real(double r) {
    char buf[64];
    bool is_neg = (r < 0.0);
    double abs_r = is_neg ? -r : r;
    if (abs_r == (double)(int64_t)abs_r) {
        snprintf(buf, sizeof(buf), "%s%.1f", is_neg ? "~" : "", abs_r);
    } else {
        snprintf(buf, sizeof(buf), "%s%g", is_neg ? "~" : "", abs_r);
    }
    return quest_string_new(buf, (int64_t)strlen(buf));
}

QString *quest_conv_char(QChar ch) {
    char buf[8];
    buf[0] = '\'';
    buf[1] = (char)ch;
    buf[2] = '\'';
    buf[3] = 0;
    return quest_string_new(buf, 3);
}

QString *quest_conv_string(const QString *s) {
    if (s == NULL) return quest_string_new("\"\"", 2);
    int64_t len = s->length;
    char *buf = (char *)quest_alloc_atomic((size_t)(len + 3));
    buf[0] = '"';
    if (len > 0) memcpy(buf + 1, s->data, (size_t)len);
    buf[len + 1] = '"';
    buf[len + 2] = 0;
    QString *res = (QString *)quest_alloc(sizeof(QString));
    res->length = len + 2;
    res->capacity = len + 2;
    res->data = buf;
    return res;
}

/* Ascii module primitives */
QChar quest_ascii_char(int64_t n) {
    if (n < 0 || n > 255) {
        quest_raise_ascii_error();
    }
    return (QChar)(unsigned char)n;
}

int64_t quest_ascii_val(QChar ch) {
    return (int64_t)(unsigned char)ch;
}

/* RealOp primitives */
double quest_real_log(double r) {
    if (r <= 0.0) {
        quest_raise_real_error();
    }
    return log(r);
}

int64_t quest_real_floor(double r) {
    return (int64_t)floor(r);
}

int64_t quest_real_round(double r) {
    return (int64_t)round(r);
}

double quest_real_div(double a, double b) {
    if (b == 0.0) {
        quest_raise_real_error();
    }
    return a / b;
}

double quest_real_exp(double a, double b) {
    return pow(a, b);
}

/* Builtins initialization */
void quest_builtins_init(int argc, char **argv) {
    quest_writer_init_std();
    quest_reader_init_std();
    quest_system_init(argc, argv);
}



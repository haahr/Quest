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

int64_t quest_string_length(const QString *s) {
    if (s == NULL) return 0;
    return s->length;
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

int64_t quest_array_size(const QArray *a) {
    if (a == NULL) return 0;
    return a->length;
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

/* Universal subtyping predicate forward declaration */
bool quest_is_subtype(const QTypeDescriptor *sub, const QTypeDescriptor *super_type);

/* Statically pre-allocated base type descriptors */
const QTypeDescriptor quest_type_Int = {
    .kind = QTYPE_KIND_INT,
    .name = "Int",
    .size = sizeof(QInt),
    .alignment = sizeof(QInt),
    .is_subtype = quest_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_Real = {
    .kind = QTYPE_KIND_REAL,
    .name = "Real",
    .size = sizeof(QReal),
    .alignment = sizeof(QReal),
    .is_subtype = quest_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_Bool = {
    .kind = QTYPE_KIND_BOOL,
    .name = "Bool",
    .size = sizeof(QInt),
    .alignment = sizeof(QInt),
    .is_subtype = quest_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_Char = {
    .kind = QTYPE_KIND_CHAR,
    .name = "Char",
    .size = sizeof(QInt),
    .alignment = sizeof(QInt),
    .is_subtype = quest_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_String = {
    .kind = QTYPE_KIND_STRING,
    .name = "String",
    .size = sizeof(void *),
    .alignment = sizeof(void *),
    .is_subtype = quest_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_Ok = {
    .kind = QTYPE_KIND_OK,
    .name = "Ok",
    .size = sizeof(QInt),
    .alignment = sizeof(QInt),
    .is_subtype = quest_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_Dynamic = {
    .kind = QTYPE_KIND_DYNAMIC,
    .name = "Dynamic",
    .size = sizeof(void *),
    .alignment = sizeof(void *),
    .is_subtype = quest_is_subtype,
    .extra = NULL
};

const QTypeDescriptor quest_type_EmptyTuple = {
    .kind = QTYPE_KIND_TUPLE,
    .name = "Tuple end",
    .size = sizeof(void *),
    .alignment = sizeof(void *),
    .is_subtype = quest_is_subtype,
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

static char *quest_dup_str(const char *s) {
    if (s == NULL) return NULL;
    size_t len = strlen(s);
    char *copy = (char *)quest_alloc_atomic(len + 1);
    memcpy(copy, s, len + 1);
    return copy;
}

#define Q_SUBTYPE_TRAIL_MAX 64
typedef struct QSubtypePair {
    const QTypeDescriptor *sub;
    const QTypeDescriptor *super_type;
} QSubtypePair;

static Q_THREAD_LOCAL QSubtypePair quest_subtyping_trail[Q_SUBTYPE_TRAIL_MAX];
static Q_THREAD_LOCAL size_t quest_subtyping_trail_len = 0;

bool quest_is_subtype(const QTypeDescriptor *sub, const QTypeDescriptor *super_type) {
    if (sub == super_type) return true;
    if (super_type == &quest_type_EmptyTuple) return true;
    if (sub == NULL || super_type == NULL) return false;

    /* Cycle detection trail */
    for (size_t i = 0; i < quest_subtyping_trail_len; ++i) {
        if (quest_subtyping_trail[i].sub == sub && quest_subtyping_trail[i].super_type == super_type) {
            return true;
        }
    }
    if (quest_subtyping_trail_len >= Q_SUBTYPE_TRAIL_MAX) {
        return false;
    }
    quest_subtyping_trail[quest_subtyping_trail_len++] = (QSubtypePair){ sub, super_type };

    bool result = false;

    switch (super_type->kind) {
        case QTYPE_KIND_INT:
        case QTYPE_KIND_REAL:
        case QTYPE_KIND_BOOL:
        case QTYPE_KIND_CHAR:
        case QTYPE_KIND_STRING:
        case QTYPE_KIND_OK:
        case QTYPE_KIND_DYNAMIC:
            result = (sub == super_type);
            break;

        case QTYPE_KIND_OPAQUE:
            result = (sub == super_type) ||
                     (sub->name != NULL && super_type->name != NULL && strcmp(sub->name, super_type->name) == 0);
            break;

        case QTYPE_KIND_ARRAY: {
            if (sub->kind != QTYPE_KIND_ARRAY) { result = false; break; }
            const QArrayTypeDescriptor *s = (const QArrayTypeDescriptor *)sub->extra;
            const QArrayTypeDescriptor *t = (const QArrayTypeDescriptor *)super_type->extra;
            if (s == NULL || t == NULL) { result = false; break; }
            result = quest_is_subtype(s->element_type, t->element_type) &&
                     quest_is_subtype(t->element_type, s->element_type);
            break;
        }

        case QTYPE_KIND_TUPLE: {
            if (super_type == &quest_type_EmptyTuple) { result = true; break; }
            if (sub->kind != QTYPE_KIND_TUPLE) { result = false; break; }
            const QTupleTypeDescriptor *s = (const QTupleTypeDescriptor *)sub->extra;
            const QTupleTypeDescriptor *t = (const QTupleTypeDescriptor *)super_type->extra;
            if (t == NULL || t->element_count == 0) { result = true; break; }
            if (s == NULL || s->element_count < t->element_count) { result = false; break; }
            bool match = true;
            for (size_t i = 0; i < t->element_count; ++i) {
                if (t->elements[i].name != NULL) {
                    if (s->elements[i].name == NULL || strcmp(s->elements[i].name, t->elements[i].name) != 0) {
                        match = false;
                        break;
                    }
                }
                if (!quest_is_subtype(s->elements[i].type, t->elements[i].type)) {
                    match = false;
                    break;
                }
            }
            result = match;
            break;
        }

        case QTYPE_KIND_RECORD: {
            if (sub->kind != QTYPE_KIND_RECORD) { result = false; break; }
            const QRecordTypeDescriptor *s = (const QRecordTypeDescriptor *)sub->extra;
            const QRecordTypeDescriptor *t = (const QRecordTypeDescriptor *)super_type->extra;
            if (t == NULL || t->field_count == 0) { result = true; break; }
            if (s == NULL) { result = false; break; }
            bool match = true;
            for (size_t j = 0; j < t->field_count; ++j) {
                const QRecordFieldDescriptor *tf = &t->fields[j];
                const QRecordFieldDescriptor *sf = NULL;
                for (size_t i = 0; i < s->field_count; ++i) {
                    if (s->fields[i].name != NULL && strcmp(s->fields[i].name, tf->name) == 0) {
                        sf = &s->fields[i];
                        break;
                    }
                }
                if (sf == NULL) { match = false; break; }
                if (tf->is_var) {
                    if (!sf->is_var) { match = false; break; }
                    if (!quest_is_subtype(sf->type, tf->type) || !quest_is_subtype(tf->type, sf->type)) {
                        match = false;
                        break;
                    }
                } else {
                    if (!quest_is_subtype(sf->type, tf->type)) {
                        match = false;
                        break;
                    }
                }
            }
            result = match;
            break;
        }

        case QTYPE_KIND_VARIANT:
        case QTYPE_KIND_OPTION: {
            if (sub->kind != QTYPE_KIND_VARIANT && sub->kind != QTYPE_KIND_OPTION) {
                result = false;
                break;
            }
            const QVariantTypeDescriptor *s = (const QVariantTypeDescriptor *)sub->extra;
            const QVariantTypeDescriptor *t = (const QVariantTypeDescriptor *)super_type->extra;
            if (s == NULL || s->case_count == 0) { result = true; break; }
            if (t == NULL) { result = false; break; }
            bool match = true;
            for (size_t i = 0; i < s->case_count; ++i) {
                const QVariantCaseDescriptor *sc = &s->cases[i];
                const QVariantCaseDescriptor *tc = NULL;
                for (size_t j = 0; j < t->case_count; ++j) {
                    if (t->cases[j].name != NULL && strcmp(t->cases[j].name, sc->name) == 0) {
                        tc = &t->cases[j];
                        break;
                    }
                }
                if (tc == NULL) { match = false; break; }
                if (sc->payload_type == NULL) {
                    if (tc->payload_type != NULL) { match = false; break; }
                } else {
                    if (tc->payload_type == NULL) { match = false; break; }
                    if (sc->is_var || tc->is_var) {
                        if (!quest_is_subtype(sc->payload_type, tc->payload_type) ||
                            !quest_is_subtype(tc->payload_type, sc->payload_type)) {
                            match = false;
                            break;
                        }
                    } else {
                        if (!quest_is_subtype(sc->payload_type, tc->payload_type)) {
                            match = false;
                            break;
                        }
                    }
                }
            }
            result = match;
            break;
        }

        case QTYPE_KIND_FUN: {
            if (sub->kind != QTYPE_KIND_FUN) { result = false; break; }
            const QFunTypeDescriptor *s = (const QFunTypeDescriptor *)sub->extra;
            const QFunTypeDescriptor *t = (const QFunTypeDescriptor *)super_type->extra;
            if (s == NULL || t == NULL) { result = (s == t); break; }
            if (s->param_count != t->param_count) { result = false; break; }
            bool match = true;
            for (size_t i = 0; i < s->param_count; ++i) {
                if (s->params[i].type != t->params[i].type ||
                    s->params[i].is_var != t->params[i].is_var ||
                    s->params[i].is_out != t->params[i].is_out) {
                    match = false;
                    break;
                }
            }
            if (match && s->result_type != t->result_type) {
                match = false;
            }
            result = match;
            break;
        }

        default:
            result = (sub == super_type);
            break;
    }

    quest_subtyping_trail_len--;
    return result;
}

/* ------------------------------------------------------------------------- */
/* Dynamic Aggregate Adaptation Cache & Coercion Functions                   */
/* ------------------------------------------------------------------------- */

typedef struct QRecordAdapterCacheEntry {
    const QTypeDescriptor          *sub_desc;
    const QTypeDescriptor          *super_desc;
    const size_t                   *dict;
    bool                            needs_recursive;
    struct QRecordAdapterCacheEntry *next;
} QRecordAdapterCacheEntry;

static QRecordAdapterCacheEntry *quest_record_adapter_cache = NULL;

QRecordVal quest_record_adapt(const QTypeDescriptor *sub_desc, const QTypeDescriptor *super_desc, QVal payload) {
    if (payload.p == NULL) {
        return (QRecordVal){ .val = NULL, .dict = NULL };
    }
    const QRecordVal *orig_rec = (const QRecordVal *)payload.p;
    if (sub_desc == super_desc || super_desc == &quest_type_EmptyTuple) {
        return *orig_rec;
    }

    const QRecordTypeDescriptor *s_meta = (const QRecordTypeDescriptor *)sub_desc->extra;
    const QRecordTypeDescriptor *t_meta = (const QRecordTypeDescriptor *)super_desc->extra;
    if (t_meta == NULL || t_meta->field_count == 0) {
        return *orig_rec;
    }

    /* Check adaptation cache */
    QRecordAdapterCacheEntry *cached = NULL;
    for (QRecordAdapterCacheEntry *cur = quest_record_adapter_cache; cur != NULL; cur = cur->next) {
        if (cur->sub_desc == sub_desc && cur->super_desc == super_desc) {
            cached = cur;
            break;
        }
    }

    if (cached == NULL) {
        size_t *dict = (size_t *)quest_alloc(sizeof(size_t) * t_meta->field_count);
        bool recursive = false;
        for (size_t j = 0; j < t_meta->field_count; ++j) {
            const QRecordFieldDescriptor *tf = &t_meta->fields[j];
            const QRecordFieldDescriptor *sf = NULL;
            if (s_meta != NULL) {
                for (size_t i = 0; i < s_meta->field_count; ++i) {
                    if (s_meta->fields[i].name != NULL && strcmp(s_meta->fields[i].name, tf->name) == 0) {
                        sf = &s_meta->fields[i];
                        break;
                    }
                }
            }
            if (sf != NULL) {
                dict[j] = sf->offset;
                if (!tf->is_var && (tf->type->kind == QTYPE_KIND_RECORD || tf->type->kind == QTYPE_KIND_VARIANT)) {
                    if (sf->type != tf->type) {
                        recursive = true;
                    }
                }
            } else {
                dict[j] = 0;
            }
        }
        cached = (QRecordAdapterCacheEntry *)quest_alloc(sizeof(QRecordAdapterCacheEntry));
        cached->sub_desc = sub_desc;
        cached->super_desc = super_desc;
        cached->dict = dict;
        cached->needs_recursive = recursive;
        cached->next = quest_record_adapter_cache;
        quest_record_adapter_cache = cached;
    }

    if (!cached->needs_recursive) {
        return (QRecordVal){ .val = orig_rec->val, .dict = cached->dict };
    }

    /* Recursive payload allocation and field adaptation */
    void *new_val = quest_alloc(super_desc->size > 0 ? super_desc->size : sizeof(void *));
    for (size_t j = 0; j < t_meta->field_count; ++j) {
        const QRecordFieldDescriptor *tf = &t_meta->fields[j];
        const QRecordFieldDescriptor *sf = NULL;
        for (size_t i = 0; i < s_meta->field_count; ++i) {
            if (s_meta->fields[i].name != NULL && strcmp(s_meta->fields[i].name, tf->name) == 0) {
                sf = &s_meta->fields[i];
                break;
            }
        }
        if (sf == NULL) continue;
        void *src_field = (char *)orig_rec->val + sf->offset;
        void *dst_field = (char *)new_val + tf->offset;

        if (tf->type->kind == QTYPE_KIND_RECORD && sf->type != tf->type) {
            QRecordVal *sub_r = (QRecordVal *)src_field;
            QRecordVal adapted_inner = quest_record_adapt(sf->type, tf->type, (QVal){ .p = sub_r });
            *(QRecordVal *)dst_field = adapted_inner;
        } else if ((tf->type->kind == QTYPE_KIND_VARIANT || tf->type->kind == QTYPE_KIND_OPTION) &&
                   sf->type != tf->type) {
            QVariantVal *sub_v = (QVariantVal *)src_field;
            QVariantVal adapted_inner = quest_variant_adapt(sf->type, tf->type, (QVal){ .p = sub_v });
            *(QVariantVal *)dst_field = adapted_inner;
        } else {
            size_t copy_size = tf->type->size > 0 ? tf->type->size : sizeof(QVal);
            memcpy(dst_field, src_field, copy_size);
        }
    }
    return (QRecordVal){ .val = new_val, .dict = cached->dict };
}

typedef struct QVariantAdapterCacheEntry {
    const QTypeDescriptor            *sub_desc;
    const QTypeDescriptor            *super_desc;
    const int64_t                    *tagmap;
    struct QVariantAdapterCacheEntry *next;
} QVariantAdapterCacheEntry;

static QVariantAdapterCacheEntry *quest_variant_adapter_cache = NULL;

QVariantVal quest_variant_adapt(const QTypeDescriptor *sub_desc, const QTypeDescriptor *super_desc, QVal payload) {
    if (payload.p == NULL) {
        return (QVariantVal){ .tag = 0, .payload = (QVal){ .u = 0 } };
    }
    const QVariantVal *orig_var = (const QVariantVal *)payload.p;
    if (sub_desc == super_desc) {
        return *orig_var;
    }

    const QVariantTypeDescriptor *s_meta = (const QVariantTypeDescriptor *)sub_desc->extra;
    const QVariantTypeDescriptor *t_meta = (const QVariantTypeDescriptor *)super_desc->extra;
    if (s_meta == NULL || t_meta == NULL) {
        return *orig_var;
    }

    /* Check tagmap cache */
    QVariantAdapterCacheEntry *cached = NULL;
    for (QVariantAdapterCacheEntry *cur = quest_variant_adapter_cache; cur != NULL; cur = cur->next) {
        if (cur->sub_desc == sub_desc && cur->super_desc == super_desc) {
            cached = cur;
            break;
        }
    }

    if (cached == NULL) {
        int64_t *tagmap = (int64_t *)quest_alloc(sizeof(int64_t) * s_meta->case_count);
        for (size_t i = 0; i < s_meta->case_count; ++i) {
            const QVariantCaseDescriptor *sc = &s_meta->cases[i];
            int64_t target_idx = -1;
            for (size_t j = 0; j < t_meta->case_count; ++j) {
                if (t_meta->cases[j].name != NULL && strcmp(t_meta->cases[j].name, sc->name) == 0) {
                    target_idx = (int64_t)j;
                    break;
                }
            }
            tagmap[i] = target_idx >= 0 ? target_idx : 0;
        }
        cached = (QVariantAdapterCacheEntry *)quest_alloc(sizeof(QVariantAdapterCacheEntry));
        cached->sub_desc = sub_desc;
        cached->super_desc = super_desc;
        cached->tagmap = tagmap;
        cached->next = quest_variant_adapter_cache;
        quest_variant_adapter_cache = cached;
    }

    int64_t target_tag = (orig_var->tag >= 0 && (size_t)orig_var->tag < s_meta->case_count)
                             ? cached->tagmap[orig_var->tag]
                             : 0;

    /* Adapt payload if payload type is a compound subtype */
    QVal adapted_payload = orig_var->payload;
    const QVariantCaseDescriptor *sc = (orig_var->tag >= 0 && (size_t)orig_var->tag < s_meta->case_count)
                                           ? &s_meta->cases[orig_var->tag]
                                           : NULL;
    const QVariantCaseDescriptor *tc = (target_tag >= 0 && (size_t)target_tag < t_meta->case_count)
                                           ? &t_meta->cases[target_tag]
                                           : NULL;
    if (sc != NULL && tc != NULL && sc->payload_type != NULL && tc->payload_type != NULL &&
        sc->payload_type != tc->payload_type) {
        if (tc->payload_type->kind == QTYPE_KIND_RECORD) {
            QRecordVal adapted_rec = quest_record_adapt(sc->payload_type, tc->payload_type, orig_var->payload);
            adapted_payload = (QVal){ .p = quest_record_box(adapted_rec) };
        } else if (tc->payload_type->kind == QTYPE_KIND_VARIANT || tc->payload_type->kind == QTYPE_KIND_OPTION) {
            QVariantVal adapted_v = quest_variant_adapt(sc->payload_type, tc->payload_type, orig_var->payload);
            adapted_payload = (QVal){ .p = quest_variant_box(adapted_v) };
        }
    }

    return (QVariantVal){ .tag = target_tag, .payload = adapted_payload };
}

/* ------------------------------------------------------------------------- */
/* Type Descriptor Constructors & Helpers                                    */
/* ------------------------------------------------------------------------- */

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
    desc->is_subtype = quest_is_subtype;

    QArrayTypeDescriptor *arr_meta = (QArrayTypeDescriptor *)quest_alloc(sizeof(QArrayTypeDescriptor));
    arr_meta->element_type = element_desc;
    desc->extra = arr_meta;

    return quest_intern_type_descriptor(desc);
}

const QTypeDescriptor *quest_make_opaque_descriptor(const char *name) {
    /* Opaque types use unique pointer identity for encapsulation */
    QTypeDescriptor *desc = (QTypeDescriptor *)quest_alloc(sizeof(QTypeDescriptor));
    desc->kind = QTYPE_KIND_OPAQUE;
    desc->name = name != NULL ? quest_dup_str(name) : "Opaque";
    desc->size = sizeof(QVal);
    desc->alignment = sizeof(QVal);
    desc->is_subtype = quest_is_subtype;
    desc->extra = NULL;
    /* Do NOT intern: each opaque type creation has unique nominal identity */
    return desc;
}

const QTypeDescriptor *quest_make_record_descriptor(
    const char *name, size_t size, size_t alignment, size_t field_count, const QRecordFieldDescriptor *fields
) {
    quest_init_type_intern_table();
    const char *rec_name = name ? name : "Record end";

    uint64_t h = quest_hash_string(rec_name) % Q_TYPE_INTERN_TABLE_SIZE;
    for (QTypeDescriptorEntry *cur = quest_type_intern_buckets[h]; cur != NULL; cur = cur->next) {
        if (cur->desc->name != NULL && strcmp(cur->desc->name, rec_name) == 0) {
            return cur->desc;
        }
    }

    QTypeDescriptor *desc = (QTypeDescriptor *)quest_alloc(sizeof(QTypeDescriptor));
    desc->kind = QTYPE_KIND_RECORD;
    desc->name = quest_dup_str(rec_name);
    desc->size = size;
    desc->alignment = alignment > 0 ? alignment : sizeof(void *);
    desc->is_subtype = quest_is_subtype;

    size_t meta_size = sizeof(QRecordTypeDescriptor) + sizeof(QRecordFieldDescriptor) * field_count;
    QRecordTypeDescriptor *meta = (QRecordTypeDescriptor *)quest_alloc(meta_size);
    meta->field_count = field_count;
    if (fields != NULL && field_count > 0) {
        memcpy((void *)meta->fields, fields, sizeof(QRecordFieldDescriptor) * field_count);
    }
    desc->extra = meta;
    return quest_intern_type_descriptor(desc);
}

const QTypeDescriptor *quest_make_tuple_descriptor(
    const char *name, size_t size, size_t alignment, size_t element_count, const QTupleElementDescriptor *elements
) {
    if (element_count == 0) return &quest_type_EmptyTuple;
    quest_init_type_intern_table();
    const char *tup_name = name ? name : "Tuple end";

    uint64_t h = quest_hash_string(tup_name) % Q_TYPE_INTERN_TABLE_SIZE;
    for (QTypeDescriptorEntry *cur = quest_type_intern_buckets[h]; cur != NULL; cur = cur->next) {
        if (cur->desc->name != NULL && strcmp(cur->desc->name, tup_name) == 0) {
            return cur->desc;
        }
    }

    QTypeDescriptor *desc = (QTypeDescriptor *)quest_alloc(sizeof(QTypeDescriptor));
    desc->kind = QTYPE_KIND_TUPLE;
    desc->name = quest_dup_str(tup_name);
    desc->size = size;
    desc->alignment = alignment > 0 ? alignment : sizeof(void *);
    desc->is_subtype = quest_is_subtype;

    size_t meta_size = sizeof(QTupleTypeDescriptor) + sizeof(QTupleElementDescriptor) * element_count;
    QTupleTypeDescriptor *meta = (QTupleTypeDescriptor *)quest_alloc(meta_size);
    meta->element_count = element_count;
    if (elements != NULL && element_count > 0) {
        memcpy((void *)meta->elements, elements, sizeof(QTupleElementDescriptor) * element_count);
    }
    desc->extra = meta;
    return quest_intern_type_descriptor(desc);
}

const QTypeDescriptor *quest_make_variant_descriptor(
    const char *name, size_t size, size_t alignment, size_t case_count, const QVariantCaseDescriptor *cases
) {
    quest_init_type_intern_table();
    const char *var_name = name ? name : "Variant end";

    uint64_t h = quest_hash_string(var_name) % Q_TYPE_INTERN_TABLE_SIZE;
    for (QTypeDescriptorEntry *cur = quest_type_intern_buckets[h]; cur != NULL; cur = cur->next) {
        if (cur->desc->name != NULL && strcmp(cur->desc->name, var_name) == 0) {
            return cur->desc;
        }
    }

    QTypeDescriptor *desc = (QTypeDescriptor *)quest_alloc(sizeof(QTypeDescriptor));
    desc->kind = QTYPE_KIND_VARIANT;
    desc->name = quest_dup_str(var_name);
    desc->size = size > 0 ? size : sizeof(QVariantVal);
    desc->alignment = alignment > 0 ? alignment : sizeof(void *);
    desc->is_subtype = quest_is_subtype;

    size_t meta_size = sizeof(QVariantTypeDescriptor) + sizeof(QVariantCaseDescriptor) * case_count;
    QVariantTypeDescriptor *meta = (QVariantTypeDescriptor *)quest_alloc(meta_size);
    meta->case_count = case_count;
    if (cases != NULL && case_count > 0) {
        memcpy((void *)meta->cases, cases, sizeof(QVariantCaseDescriptor) * case_count);
    }
    desc->extra = meta;
    return quest_intern_type_descriptor(desc);
}

const QTypeDescriptor *quest_make_fun_descriptor(
    const char *name, size_t param_count, const QFunParamDescriptor *params, const QTypeDescriptor *result_type
) {
    quest_init_type_intern_table();
    const char *fn_name = name ? name : "Fun()";

    uint64_t h = quest_hash_string(fn_name) % Q_TYPE_INTERN_TABLE_SIZE;
    for (QTypeDescriptorEntry *cur = quest_type_intern_buckets[h]; cur != NULL; cur = cur->next) {
        if (cur->desc->name != NULL && strcmp(cur->desc->name, fn_name) == 0) {
            return cur->desc;
        }
    }

    QTypeDescriptor *desc = (QTypeDescriptor *)quest_alloc(sizeof(QTypeDescriptor));
    desc->kind = QTYPE_KIND_FUN;
    desc->name = quest_dup_str(fn_name);
    desc->size = sizeof(QClosure);
    desc->alignment = sizeof(void *);
    desc->is_subtype = quest_is_subtype;

    size_t meta_size = sizeof(QFunTypeDescriptor) + sizeof(QFunParamDescriptor) * param_count;
    QFunTypeDescriptor *meta = (QFunTypeDescriptor *)quest_alloc(meta_size);
    meta->param_count = param_count;
    meta->result_type = result_type;
    if (params != NULL && param_count > 0) {
        memcpy((void *)meta->params, params, sizeof(QFunParamDescriptor) * param_count);
    }
    desc->extra = meta;
    return quest_intern_type_descriptor(desc);
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
    /* Check exact pointer identity */
    if (d->type_desc == target_type_desc) {
        return d->payload;
    }
    /* Check structural subtyping */
    if (!quest_is_subtype(d->type_desc, target_type_desc)) {
        quest_raise_dynamic_error();
    }
    /* Coercion and adaptation for aggregates */
    if (target_type_desc->kind == QTYPE_KIND_RECORD) {
        QRecordVal adapted = quest_record_adapt(d->type_desc, target_type_desc, d->payload);
        return (QVal){ .p = quest_record_box(adapted) };
    }
    if (target_type_desc->kind == QTYPE_KIND_VARIANT || target_type_desc->kind == QTYPE_KIND_OPTION) {
        QVariantVal adapted = quest_variant_adapt(d->type_desc, target_type_desc, d->payload);
        return (QVal){ .p = quest_variant_box(adapted) };
    }
    return d->payload;
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
double quest_real_from_int(int64_t n) {
    return (double)n;
}

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

/* ============================================================================
 * Built-in Operator Trampolines & Closures (Cardelli §4.2)
 * ============================================================================
 */

/* Integer arithmetic */
static QInt qv_sym_plus_trampoline(void *env, QInt a, QInt b) { (void)env; return a + b; }
QClosure qv_sym_plus_closure = { (void *)qv_sym_plus_trampoline, NULL };

static QInt qv_sym_minus_trampoline(void *env, QInt a, QInt b) { (void)env; return a - b; }
QClosure qv_sym_minus_closure = { (void *)qv_sym_minus_trampoline, NULL };

static QInt qv_sym_star_trampoline(void *env, QInt a, QInt b) { (void)env; return a * b; }
QClosure qv_sym_star_closure = { (void *)qv_sym_star_trampoline, NULL };

static QInt qv_sym_slash_trampoline(void *env, QInt a, QInt b) { (void)env; return quest_int_div(a, b); }
QClosure qv_sym_slash_closure = { (void *)qv_sym_slash_trampoline, NULL };

static QInt qv_sym_percent_trampoline(void *env, QInt a, QInt b) { (void)env; return quest_int_mod(a, b); }
QClosure qv_sym_percent_closure = { (void *)qv_sym_percent_trampoline, NULL };

static QInt qv_mod_trampoline(void *env, QInt a, QInt b) { (void)env; return quest_int_mod(a, b); }
QClosure qv_mod_closure = { (void *)qv_mod_trampoline, NULL };

/* Integer relational */
static QBool qv_sym_lt_trampoline(void *env, QInt a, QInt b) { (void)env; return a < b; }
QClosure qv_sym_lt_closure = { (void *)qv_sym_lt_trampoline, NULL };

static QBool qv_sym_lt_equals_trampoline(void *env, QInt a, QInt b) { (void)env; return a <= b; }
QClosure qv_sym_lt_equals_closure = { (void *)qv_sym_lt_equals_trampoline, NULL };

static QBool qv_sym_gt_trampoline(void *env, QInt a, QInt b) { (void)env; return a > b; }
QClosure qv_sym_gt_closure = { (void *)qv_sym_gt_trampoline, NULL };

static QBool qv_sym_gt_equals_trampoline(void *env, QInt a, QInt b) { (void)env; return a >= b; }
QClosure qv_sym_gt_equals_closure = { (void *)qv_sym_gt_equals_trampoline, NULL };

/* Real arithmetic */
static QReal qv_sym_plus_plus_trampoline(void *env, QReal a, QReal b) { (void)env; return a + b; }
QClosure qv_sym_plus_plus_closure = { (void *)qv_sym_plus_plus_trampoline, NULL };

static QReal qv_sym_minus_minus_trampoline(void *env, QReal a, QReal b) { (void)env; return a - b; }
QClosure qv_sym_minus_minus_closure = { (void *)qv_sym_minus_minus_trampoline, NULL };

static QReal qv_sym_star_star_trampoline(void *env, QReal a, QReal b) { (void)env; return a * b; }
QClosure qv_sym_star_star_closure = { (void *)qv_sym_star_star_trampoline, NULL };

static QReal qv_sym_slash_slash_trampoline(void *env, QReal a, QReal b) { (void)env; return a / b; }
QClosure qv_sym_slash_slash_closure = { (void *)qv_sym_slash_slash_trampoline, NULL };

static QReal qv_sym_caret_caret_trampoline(void *env, QReal a, QReal b) { (void)env; return quest_real_pow(a, b); }
QClosure qv_sym_caret_caret_closure = { (void *)qv_sym_caret_caret_trampoline, NULL };

/* Real relational */
static QBool qv_sym_lt_lt_trampoline(void *env, QReal a, QReal b) { (void)env; return a < b; }
QClosure qv_sym_lt_lt_closure = { (void *)qv_sym_lt_lt_trampoline, NULL };

static QBool qv_sym_lt_lt_equals_trampoline(void *env, QReal a, QReal b) { (void)env; return a <= b; }
QClosure qv_sym_lt_lt_equals_closure = { (void *)qv_sym_lt_lt_equals_trampoline, NULL };

static QBool qv_sym_gt_gt_trampoline(void *env, QReal a, QReal b) { (void)env; return a > b; }
QClosure qv_sym_gt_gt_closure = { (void *)qv_sym_gt_gt_trampoline, NULL };

static QBool qv_sym_gt_gt_equals_trampoline(void *env, QReal a, QReal b) { (void)env; return a >= b; }
QClosure qv_sym_gt_gt_equals_closure = { (void *)qv_sym_gt_gt_equals_trampoline, NULL };

/* String concatenation */
static QString *qv_sym_lt_gt_trampoline(void *env, const QString *a, const QString *b) {
    (void)env;
    return quest_string_concat(a, b);
}
QClosure qv_sym_lt_gt_closure = { (void *)qv_sym_lt_gt_trampoline, NULL };

/* Boolean eager operations */
static QBool qv_sym_slash_backslash_trampoline(void *env, QBool a, QBool b) { (void)env; return a && b; }
QClosure qv_sym_slash_backslash_closure = { (void *)qv_sym_slash_backslash_trampoline, NULL };

static QBool qv_sym_backslash_slash_trampoline(void *env, QBool a, QBool b) { (void)env; return a || b; }
QClosure qv_sym_backslash_slash_closure = { (void *)qv_sym_backslash_slash_trampoline, NULL };

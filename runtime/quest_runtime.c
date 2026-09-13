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


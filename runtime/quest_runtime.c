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

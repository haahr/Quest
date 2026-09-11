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

double quest_real_pow(double base, double exp) {
    if (base == 0.0 && exp <= 0.0) {
        quest_raise_divide_by_zero();
    }
    return pow(base, exp);
}

void quest_raise_divide_by_zero(void) {
    fprintf(stderr, "Exception: DivideByZero\n");
    exit(1);
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

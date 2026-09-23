/*
 * quest_serialization.c
 * Dynamic serialization (JSON / JSOG) for Quest C Runtime.
 */

#include "quest_serialization.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <math.h>
#include <ctype.h>

#define Q_PTR_TABLE_SIZE 1024

typedef struct QPtrNode {
    const void      *ptr;
    int              count;
    int              id;
    struct QPtrNode *next;
} QPtrNode;

typedef struct QPtrTable {
    QPtrNode *buckets[Q_PTR_TABLE_SIZE];
} QPtrTable;

static uint64_t quest_ptr_hash(const void *ptr) {
    uintptr_t val = (uintptr_t)ptr;
    return (uint64_t)((val >> 3) ^ (val >> 16)) % Q_PTR_TABLE_SIZE;
}

static QPtrNode *quest_ptr_find(const QPtrTable *table, const void *ptr) {
    if (table == NULL || ptr == NULL) return NULL;
    uint64_t h = quest_ptr_hash(ptr);
    for (QPtrNode *cur = table->buckets[h]; cur != NULL; cur = cur->next) {
        if (cur->ptr == ptr) return cur;
    }
    return NULL;
}

static QPtrNode *quest_ptr_insert_or_inc(QPtrTable *table, const void *ptr) {
    if (table == NULL || ptr == NULL) return NULL;
    uint64_t h = quest_ptr_hash(ptr);
    for (QPtrNode *cur = table->buckets[h]; cur != NULL; cur = cur->next) {
        if (cur->ptr == ptr) {
            cur->count++;
            return cur;
        }
    }
    QPtrNode *node = (QPtrNode *)quest_alloc(sizeof(QPtrNode));
    node->ptr = ptr;
    node->count = 1;
    node->id = 0;
    node->next = table->buckets[h];
    table->buckets[h] = node;
    return node;
}

static QVal quest_extract_field_val(const QTypeDescriptor *t, const void *ptr) {
    if (t == NULL || ptr == NULL) return (QVal){ .p = NULL };
    switch (t->kind) {
        case QTYPE_KIND_INT:
        case QTYPE_KIND_BOOL:
        case QTYPE_KIND_CHAR:
            return (QVal){ .i = *(const int64_t *)ptr };
        case QTYPE_KIND_REAL:
            return (QVal){ .r = *(const double *)ptr };
        case QTYPE_KIND_RECORD:
            return (QVal){ .p = (void *)quest_record_box(*(const QRecordVal *)ptr) };
        case QTYPE_KIND_VARIANT:
            return (QVal){ .p = (void *)quest_variant_box(*(const QVariantVal *)ptr) };
        case QTYPE_KIND_STRING:
        case QTYPE_KIND_ARRAY:
        case QTYPE_KIND_DYNAMIC:
        case QTYPE_KIND_TUPLE:
        case QTYPE_KIND_OPTION:
        default:
            return (QVal){ .p = *(void * const *)ptr };
    }
}

static void quest_write_raw(QWriter *wr, const char *s) {
    size_t len = strlen(s);
    if (len > 0) {
        quest_writer_put_string(wr, quest_string_new(s, (int64_t)len));
    }
}

static void quest_write_json_string(QWriter *wr, const char *s, size_t len) {
    quest_writer_put_char(wr, '"');
    for (size_t i = 0; i < len; ++i) {
        unsigned char c = (unsigned char)s[i];
        switch (c) {
            case '"':  quest_write_raw(wr, "\\\""); break;
            case '\\': quest_write_raw(wr, "\\\\"); break;
            case '\b': quest_write_raw(wr, "\\b"); break;
            case '\f': quest_write_raw(wr, "\\f"); break;
            case '\n': quest_write_raw(wr, "\\n"); break;
            case '\r': quest_write_raw(wr, "\\r"); break;
            case '\t': quest_write_raw(wr, "\\t"); break;
            default:
                if (c < 0x20) {
                    char hex[8];
                    snprintf(hex, sizeof(hex), "\\u%04x", c);
                    quest_write_raw(wr, hex);
                } else {
                    quest_writer_put_char(wr, (QChar)c);
                }
                break;
        }
    }
    quest_writer_put_char(wr, '"');
}

/* ------------------------------------------------------------------------- */
/* Pass 1: Cycle & Multi-reference Graph Scan                                */
/* ------------------------------------------------------------------------- */

static void quest_scan_value(const QTypeDescriptor *desc, QVal val, QPtrTable *table) {
    if (desc == NULL) return;
    if (desc->kind == QTYPE_KIND_FUN || desc->kind == QTYPE_KIND_OPAQUE) {
        quest_raise_dynamic_error();
    }

    switch (desc->kind) {
        case QTYPE_KIND_INT:
        case QTYPE_KIND_REAL:
        case QTYPE_KIND_BOOL:
        case QTYPE_KIND_CHAR:
        case QTYPE_KIND_STRING:
        case QTYPE_KIND_OK:
            break;

        case QTYPE_KIND_DYNAMIC: {
            const QDynamic *dyn = (const QDynamic *)val.p;
            if (dyn != NULL && dyn->type_desc != NULL) {
                quest_scan_value(dyn->type_desc, dyn->payload, table);
            }
            break;
        }

        case QTYPE_KIND_RECORD: {
            const QRecordVal *rec = (const QRecordVal *)val.p;
            if (rec == NULL || rec->val == NULL) return;
            QPtrNode *node = quest_ptr_insert_or_inc(table, rec->val);
            if (node->count > 1) return; /* Cycle or multi-ref cut */

            const QRecordTypeDescriptor *meta = (const QRecordTypeDescriptor *)desc->extra;
            if (meta != NULL) {
                for (size_t i = 0; i < meta->field_count; ++i) {
                    const QRecordFieldDescriptor *f = &meta->fields[i];
                    QVal f_val = quest_extract_field_val(f->type, (char *)rec->val + f->offset);
                    quest_scan_value(f->type, f_val, table);
                }
            }
            break;
        }

        case QTYPE_KIND_ARRAY: {
            const QArray *arr = (const QArray *)val.p;
            if (arr == NULL) return;
            QPtrNode *node = quest_ptr_insert_or_inc(table, arr);
            if (node->count > 1) return;

            const QArrayTypeDescriptor *meta = (const QArrayTypeDescriptor *)desc->extra;
            const QTypeDescriptor *elem_desc = meta ? meta->element_type : NULL;
            if (elem_desc != NULL) {
                if (elem_desc->kind == QTYPE_KIND_RECORD) {
                    const QArrayWideRecord *w_arr = (const QArrayWideRecord *)arr;
                    for (int64_t i = 0; i < w_arr->length; ++i) {
                        QVal b = (QVal){ .p = (void *)quest_record_box(w_arr->data[i]) };
                        quest_scan_value(elem_desc, b, table);
                    }
                } else if (elem_desc->kind == QTYPE_KIND_VARIANT) {
                    const QArrayWideVariant *w_arr = (const QArrayWideVariant *)arr;
                    for (int64_t i = 0; i < w_arr->length; ++i) {
                        QVal b = (QVal){ .p = (void *)quest_variant_box(w_arr->data[i]) };
                        quest_scan_value(elem_desc, b, table);
                    }
                } else {
                    for (int64_t i = 0; i < arr->length; ++i) {
                        quest_scan_value(elem_desc, arr->data[i], table);
                    }
                }
            }
            break;
        }

        case QTYPE_KIND_TUPLE: {
            const void *tup = val.p;
            if (tup == NULL) return;
            QPtrNode *node = quest_ptr_insert_or_inc(table, tup);
            if (node->count > 1) return;

            const QTupleTypeDescriptor *meta = (const QTupleTypeDescriptor *)desc->extra;
            if (meta != NULL) {
                for (size_t i = 0; i < meta->element_count; ++i) {
                    const QTupleElementDescriptor *elem = &meta->elements[i];
                    QVal elem_val = quest_extract_field_val(elem->type, (char *)tup + elem->offset);
                    quest_scan_value(elem->type, elem_val, table);
                }
            }
            break;
        }

        case QTYPE_KIND_VARIANT:
        case QTYPE_KIND_OPTION: {
            const QVariantVal *var = (const QVariantVal *)val.p;
            if (var == NULL) return;
            const QVariantTypeDescriptor *meta = (const QVariantTypeDescriptor *)desc->extra;
            if (meta != NULL && var->tag >= 0 && (size_t)var->tag < meta->case_count) {
                const QVariantCaseDescriptor *c = &meta->cases[var->tag];
                if (c->payload_type != NULL && c->payload_type->kind != QTYPE_KIND_OK) {
                    quest_scan_value(c->payload_type, var->payload, table);
                }
            }
            break;
        }

        default:
            break;
    }
}

/* ------------------------------------------------------------------------- */
/* Pass 2: JSOG Emission to QWriter                                          */
/* ------------------------------------------------------------------------- */

static void quest_emit_value(
    const QTypeDescriptor *desc, QVal val, QPtrTable *table, int *next_id, QWriter *wr
) {
    if (desc == NULL) {
        quest_write_raw(wr, "null");
        return;
    }

    if (desc->kind == QTYPE_KIND_FUN || desc->kind == QTYPE_KIND_OPAQUE) {
        quest_raise_dynamic_error();
    }

    switch (desc->kind) {
        case QTYPE_KIND_INT: {
            char buf[64];
            snprintf(buf, sizeof(buf), "%" PRId64, val.i);
            quest_write_raw(wr, buf);
            break;
        }

        case QTYPE_KIND_REAL: {
            char buf[64];
            if (isnan(val.r) || isinf(val.r)) {
                quest_raise_dynamic_error();
            }
            snprintf(buf, sizeof(buf), "%.16g", val.r);
            if (strchr(buf, '.') == NULL && strchr(buf, 'e') == NULL && strchr(buf, 'E') == NULL) {
                strcat(buf, ".0");
            }
            quest_write_raw(wr, buf);
            break;
        }

        case QTYPE_KIND_BOOL:
            quest_write_raw(wr, val.i ? "true" : "false");
            break;

        case QTYPE_KIND_CHAR: {
            char ch = (char)val.i;
            quest_write_json_string(wr, &ch, 1);
            break;
        }

        case QTYPE_KIND_STRING: {
            const QString *s = (const QString *)val.p;
            if (s == NULL || s->data == NULL) {
                quest_write_raw(wr, "\"\"");
            } else {
                quest_write_json_string(wr, s->data, (size_t)s->length);
            }
            break;
        }

        case QTYPE_KIND_OK:
            quest_write_raw(wr, "null");
            break;

        case QTYPE_KIND_DYNAMIC: {
            const QDynamic *dyn = (const QDynamic *)val.p;
            if (dyn == NULL || dyn->type_desc == NULL) {
                quest_write_raw(wr, "null");
                break;
            }
            quest_write_raw(wr, "{\"@type\":");
            const char *t_name = dyn->type_desc->name ? dyn->type_desc->name : "Dynamic";
            quest_write_json_string(wr, t_name, strlen(t_name));
            quest_write_raw(wr, ",\"@value\":");
            quest_emit_value(dyn->type_desc, dyn->payload, table, next_id, wr);
            quest_writer_put_char(wr, '}');
            break;
        }

        case QTYPE_KIND_RECORD: {
            const QRecordVal *rec = (const QRecordVal *)val.p;
            if (rec == NULL || rec->val == NULL) {
                quest_write_raw(wr, "null");
                break;
            }

            QPtrNode *node = quest_ptr_find(table, rec->val);
            if (node != NULL && node->count > 1) {
                if (node->id > 0) {
                    char ref_buf[64];
                    snprintf(ref_buf, sizeof(ref_buf), "{\"@ref\":\"%d\"}", node->id);
                    quest_write_raw(wr, ref_buf);
                    return;
                }
                node->id = (*next_id)++;
            }

            quest_writer_put_char(wr, '{');
            bool first = true;
            if (node != NULL && node->id > 0) {
                char id_buf[64];
                snprintf(id_buf, sizeof(id_buf), "\"@id\":\"%d\"", node->id);
                quest_write_raw(wr, id_buf);
                first = false;
            }

            const QRecordTypeDescriptor *meta = (const QRecordTypeDescriptor *)desc->extra;
            if (meta != NULL) {
                for (size_t i = 0; i < meta->field_count; ++i) {
                    const QRecordFieldDescriptor *f = &meta->fields[i];
                    if (!first) {
                        quest_writer_put_char(wr, ',');
                    }
                    first = false;
                    quest_write_json_string(wr, f->name, strlen(f->name));
                    quest_writer_put_char(wr, ':');
                    QVal f_val = quest_extract_field_val(f->type, (char *)rec->val + f->offset);
                    quest_emit_value(f->type, f_val, table, next_id, wr);
                }
            }
            quest_writer_put_char(wr, '}');
            break;
        }

        case QTYPE_KIND_ARRAY: {
            const QArray *arr = (const QArray *)val.p;
            if (arr == NULL) {
                quest_write_raw(wr, "null");
                break;
            }

            QPtrNode *node = quest_ptr_find(table, arr);
            if (node != NULL && node->count > 1) {
                if (node->id > 0) {
                    char ref_buf[64];
                    snprintf(ref_buf, sizeof(ref_buf), "{\"@ref\":\"%d\"}", node->id);
                    quest_write_raw(wr, ref_buf);
                    return;
                }
                node->id = (*next_id)++;
            }

            bool is_jsog_wrap = (node != NULL && node->id > 0);
            if (is_jsog_wrap) {
                char id_buf[64];
                snprintf(id_buf, sizeof(id_buf), "{\"@id\":\"%d\",\"@array\":[", node->id);
                quest_write_raw(wr, id_buf);
            } else {
                quest_writer_put_char(wr, '[');
            }

            const QArrayTypeDescriptor *meta = (const QArrayTypeDescriptor *)desc->extra;
            const QTypeDescriptor *elem_desc = meta ? meta->element_type : NULL;
            int64_t len = arr->length;
            for (int64_t i = 0; i < len; ++i) {
                if (i > 0) quest_writer_put_char(wr, ',');
                QVal elem_val;
                if (elem_desc != NULL && elem_desc->kind == QTYPE_KIND_RECORD) {
                    const QArrayWideRecord *w_arr = (const QArrayWideRecord *)arr;
                    elem_val = (QVal){ .p = (void *)quest_record_box(w_arr->data[i]) };
                } else if (elem_desc != NULL && elem_desc->kind == QTYPE_KIND_VARIANT) {
                    const QArrayWideVariant *w_arr = (const QArrayWideVariant *)arr;
                    elem_val = (QVal){ .p = (void *)quest_variant_box(w_arr->data[i]) };
                } else {
                    elem_val = arr->data[i];
                }
                quest_emit_value(elem_desc, elem_val, table, next_id, wr);
            }

            if (is_jsog_wrap) {
                quest_write_raw(wr, "]}");
            } else {
                quest_writer_put_char(wr, ']');
            }
            break;
        }

        case QTYPE_KIND_TUPLE: {
            const void *tup = val.p;
            if (tup == NULL) {
                quest_write_raw(wr, "null");
                break;
            }

            QPtrNode *node = quest_ptr_find(table, tup);
            if (node != NULL && node->count > 1) {
                if (node->id > 0) {
                    char ref_buf[64];
                    snprintf(ref_buf, sizeof(ref_buf), "{\"@ref\":\"%d\"}", node->id);
                    quest_write_raw(wr, ref_buf);
                    return;
                }
                node->id = (*next_id)++;
            }

            bool is_jsog_wrap = (node != NULL && node->id > 0);
            if (is_jsog_wrap) {
                char id_buf[64];
                snprintf(id_buf, sizeof(id_buf), "{\"@id\":\"%d\",\"@tuple\":[", node->id);
                quest_write_raw(wr, id_buf);
            } else {
                quest_writer_put_char(wr, '[');
            }

            const QTupleTypeDescriptor *meta = (const QTupleTypeDescriptor *)desc->extra;
            if (meta != NULL) {
                for (size_t i = 0; i < meta->element_count; ++i) {
                    if (i > 0) quest_writer_put_char(wr, ',');
                    const QTupleElementDescriptor *elem = &meta->elements[i];
                    QVal elem_val = quest_extract_field_val(elem->type, (char *)tup + elem->offset);
                    quest_emit_value(elem->type, elem_val, table, next_id, wr);
                }
            }

            if (is_jsog_wrap) {
                quest_write_raw(wr, "]}");
            } else {
                quest_writer_put_char(wr, ']');
            }
            break;
        }

        case QTYPE_KIND_VARIANT:
        case QTYPE_KIND_OPTION: {
            const QVariantVal *var = (const QVariantVal *)val.p;
            if (var == NULL) {
                quest_write_raw(wr, "null");
                break;
            }
            const QVariantTypeDescriptor *meta = (const QVariantTypeDescriptor *)desc->extra;
            if (meta == NULL || var->tag < 0 || (size_t)var->tag >= meta->case_count) {
                quest_raise_dynamic_error();
            }
            const QVariantCaseDescriptor *c = &meta->cases[var->tag];
            const char *tag_name = c->name ? c->name : "tag";

            if (c->payload_type == NULL || c->payload_type->kind == QTYPE_KIND_OK) {
                quest_write_json_string(wr, tag_name, strlen(tag_name));
            } else {
                quest_writer_put_char(wr, '{');
                quest_write_json_string(wr, tag_name, strlen(tag_name));
                quest_writer_put_char(wr, ':');
                quest_emit_value(c->payload_type, var->payload, table, next_id, wr);
                quest_writer_put_char(wr, '}');
            }
            break;
        }

        default:
            quest_write_raw(wr, "null");
            break;
    }
}

/* ------------------------------------------------------------------------- */
/* Public Serialization Interface                                            */
/* ------------------------------------------------------------------------- */

void quest_dynamic_extern(QWriter *wr, const QDynamic *d) {
    if (wr == NULL || wr->is_closed || wr->file == NULL || d == NULL || d->type_desc == NULL) {
        quest_raise_dynamic_error();
    }

    QPtrTable table;
    memset(&table, 0, sizeof(table));

    /* Pass 1: detect cycles and multi-references */
    quest_scan_value(d->type_desc, d->payload, &table);

    /* Pass 2: emit JSON/JSOG root envelope */
    quest_write_raw(wr, "{\"@type\":");
    const char *t_name = d->type_desc->name ? d->type_desc->name : "Dynamic";
    quest_write_json_string(wr, t_name, strlen(t_name));
    quest_write_raw(wr, ",\"@value\":");

    int next_id = 1;
    quest_emit_value(d->type_desc, d->payload, &table, &next_id, wr);

    quest_writer_put_char(wr, '}');
}

/* ------------------------------------------------------------------------- */
/* Step 2: Streaming JSON Parser & Type Expression Parser                    */
/* ------------------------------------------------------------------------- */

static char *quest_dup_str(const char *s) {
    if (s == NULL) return NULL;
    size_t len = strlen(s);
    char *copy = (char *)quest_alloc_atomic(len + 1);
    memcpy(copy, s, len + 1);
    return copy;
}

typedef enum QJsonKind {
    QJSON_NULL,
    QJSON_BOOL,
    QJSON_INT,
    QJSON_REAL,
    QJSON_STRING,
    QJSON_ARRAY,
    QJSON_OBJECT,
} QJsonKind;

typedef struct QJsonValue QJsonValue;

typedef struct QJsonKeyValue {
    const char *key;
    QJsonValue *val;
} QJsonKeyValue;

struct QJsonValue {
    QJsonKind kind;
    union {
        bool   b;
        int64_t i;
        double  r;
        struct {
            const char *str;
            size_t      len;
        } s;
        struct {
            QJsonValue **items;
            size_t       count;
        } a;
        struct {
            QJsonKeyValue *entries;
            size_t         count;
        } o;
    } u;
};

typedef struct QJsonReader {
    QReader *rd;
    int      peek;
} QJsonReader;

static int quest_json_peek(QJsonReader *jr) {
    if (jr->peek != -1) return jr->peek;
    if (jr->rd == NULL || jr->rd->is_closed) return -1;
    if (!quest_reader_more(jr->rd)) return -1;
    jr->peek = (int)quest_reader_get_char(jr->rd);
    return jr->peek;
}

static int quest_json_next(QJsonReader *jr) {
    int ch = quest_json_peek(jr);
    jr->peek = -1;
    return ch;
}

static void quest_json_skip_ws(QJsonReader *jr) {
    int ch;
    while ((ch = quest_json_peek(jr)) != -1) {
        if (ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n') {
            quest_json_next(jr);
        } else {
            break;
        }
    }
}

static QJsonValue *quest_parse_json_value(QJsonReader *jr);

static QJsonValue *quest_parse_json_string(QJsonReader *jr) {
    quest_json_next(jr); /* consume opening quote */
    size_t cap = 32;
    size_t len = 0;
    char *buf = (char *)quest_alloc_atomic(cap);

    while (1) {
        int ch = quest_json_next(jr);
        if (ch == -1) quest_raise_dynamic_error();
        if (ch == '"') break;
        if (ch == '\\') {
            int esc = quest_json_next(jr);
            if (esc == -1) quest_raise_dynamic_error();
            switch (esc) {
                case '"':  ch = '"'; break;
                case '\\': ch = '\\'; break;
                case '/':  ch = '/'; break;
                case 'b':  ch = '\b'; break;
                case 'f':  ch = '\f'; break;
                case 'n':  ch = '\n'; break;
                case 'r':  ch = '\r'; break;
                case 't':  ch = '\t'; break;
                case 'u': {
                    unsigned int hex = 0;
                    for (int i = 0; i < 4; ++i) {
                        int h = quest_json_next(jr);
                        if (h >= '0' && h <= '9') hex = (hex << 4) | (h - '0');
                        else if (h >= 'a' && h <= 'f') hex = (hex << 4) | (h - 'a' + 10);
                        else if (h >= 'A' && h <= 'F') hex = (hex << 4) | (h - 'A' + 10);
                        else quest_raise_dynamic_error();
                    }
                    if (hex <= 0x7F) {
                        ch = (int)hex;
                    } else if (hex <= 0x7FF) {
                        if (len + 2 >= cap) {
                            cap *= 2;
                            char *nb = (char *)quest_alloc_atomic(cap);
                            memcpy(nb, buf, len);
                            buf = nb;
                        }
                        buf[len++] = (char)(0xC0 | (hex >> 6));
                        buf[len++] = (char)(0x80 | (hex & 0x3F));
                        continue;
                    } else {
                        if (len + 3 >= cap) {
                            cap = cap * 2 + 4;
                            char *nb = (char *)quest_alloc_atomic(cap);
                            memcpy(nb, buf, len);
                            buf = nb;
                        }
                        buf[len++] = (char)(0xE0 | (hex >> 12));
                        buf[len++] = (char)(0x80 | ((hex >> 6) & 0x3F));
                        buf[len++] = (char)(0x80 | (hex & 0x3F));
                        continue;
                    }
                    break;
                }
                default: quest_raise_dynamic_error();
            }
        }
        if (len + 1 >= cap) {
            cap *= 2;
            char *nb = (char *)quest_alloc_atomic(cap);
            memcpy(nb, buf, len);
            buf = nb;
        }
        buf[len++] = (char)ch;
    }
    buf[len] = '\0';
    QJsonValue *val = (QJsonValue *)quest_alloc(sizeof(QJsonValue));
    val->kind = QJSON_STRING;
    val->u.s.str = buf;
    val->u.s.len = len;
    return val;
}

static QJsonValue *quest_parse_json_number(QJsonReader *jr) {
    char buf[128];
    size_t len = 0;
    bool is_real = false;

    int ch = quest_json_peek(jr);
    if (ch == '-') {
        buf[len++] = (char)quest_json_next(jr);
    }
    while ((ch = quest_json_peek(jr)) != -1) {
        if ((ch >= '0' && ch <= '9') || ch == '+' || ch == '-') {
            if (len + 1 < sizeof(buf)) buf[len++] = (char)quest_json_next(jr);
            else quest_raise_dynamic_error();
        } else if (ch == '.' || ch == 'e' || ch == 'E') {
            is_real = true;
            if (len + 1 < sizeof(buf)) buf[len++] = (char)quest_json_next(jr);
            else quest_raise_dynamic_error();
        } else {
            break;
        }
    }
    buf[len] = '\0';
    QJsonValue *val = (QJsonValue *)quest_alloc(sizeof(QJsonValue));
    char *endptr = NULL;
    if (is_real) {
        val->kind = QJSON_REAL;
        val->u.r = strtod(buf, &endptr);
    } else {
        val->kind = QJSON_INT;
        val->u.i = (int64_t)strtoll(buf, &endptr, 10);
    }
    if (endptr == buf) quest_raise_dynamic_error();
    return val;
}

static QJsonValue *quest_parse_json_object(QJsonReader *jr) {
    quest_json_next(jr); /* consume '{' */
    size_t cap = 8;
    size_t count = 0;
    QJsonKeyValue *entries = (QJsonKeyValue *)quest_alloc(sizeof(QJsonKeyValue) * cap);

    quest_json_skip_ws(jr);
    if (quest_json_peek(jr) == '}') {
        quest_json_next(jr);
        QJsonValue *val = (QJsonValue *)quest_alloc(sizeof(QJsonValue));
        val->kind = QJSON_OBJECT;
        val->u.o.entries = entries;
        val->u.o.count = 0;
        return val;
    }

    while (1) {
        quest_json_skip_ws(jr);
        if (quest_json_peek(jr) != '"') quest_raise_dynamic_error();
        QJsonValue *key_node = quest_parse_json_string(jr);
        quest_json_skip_ws(jr);
        if (quest_json_next(jr) != ':') quest_raise_dynamic_error();
        quest_json_skip_ws(jr);
        QJsonValue *val_node = quest_parse_json_value(jr);

        if (count >= cap) {
            cap *= 2;
            QJsonKeyValue *ne = (QJsonKeyValue *)quest_alloc(sizeof(QJsonKeyValue) * cap);
            memcpy(ne, entries, sizeof(QJsonKeyValue) * count);
            entries = ne;
        }
        entries[count].key = key_node->u.s.str;
        entries[count].val = val_node;
        count++;

        quest_json_skip_ws(jr);
        int sep = quest_json_next(jr);
        if (sep == '}') break;
        if (sep == ',') continue;
        quest_raise_dynamic_error();
    }

    QJsonValue *val = (QJsonValue *)quest_alloc(sizeof(QJsonValue));
    val->kind = QJSON_OBJECT;
    val->u.o.entries = entries;
    val->u.o.count = count;
    return val;
}

static QJsonValue *quest_parse_json_array(QJsonReader *jr) {
    quest_json_next(jr); /* consume '[' */
    size_t cap = 8;
    size_t count = 0;
    QJsonValue **items = (QJsonValue **)quest_alloc(sizeof(QJsonValue *) * cap);

    quest_json_skip_ws(jr);
    if (quest_json_peek(jr) == ']') {
        quest_json_next(jr);
        QJsonValue *val = (QJsonValue *)quest_alloc(sizeof(QJsonValue));
        val->kind = QJSON_ARRAY;
        val->u.a.items = items;
        val->u.a.count = 0;
        return val;
    }

    while (1) {
        quest_json_skip_ws(jr);
        QJsonValue *item = quest_parse_json_value(jr);
        if (count >= cap) {
            cap *= 2;
            QJsonValue **ni = (QJsonValue **)quest_alloc(sizeof(QJsonValue *) * cap);
            memcpy(ni, items, sizeof(QJsonValue *) * count);
            items = ni;
        }
        items[count++] = item;

        quest_json_skip_ws(jr);
        int sep = quest_json_next(jr);
        if (sep == ']') break;
        if (sep == ',') continue;
        quest_raise_dynamic_error();
    }

    QJsonValue *val = (QJsonValue *)quest_alloc(sizeof(QJsonValue));
    val->kind = QJSON_ARRAY;
    val->u.a.items = items;
    val->u.a.count = count;
    return val;
}

static QJsonValue *quest_parse_json_value(QJsonReader *jr) {
    quest_json_skip_ws(jr);
    int ch = quest_json_peek(jr);
    if (ch == -1) quest_raise_dynamic_error();

    if (ch == '{') return quest_parse_json_object(jr);
    if (ch == '[') return quest_parse_json_array(jr);
    if (ch == '"') return quest_parse_json_string(jr);
    if ((ch >= '0' && ch <= '9') || ch == '-') return quest_parse_json_number(jr);

    if (ch == 't') {
        const char *t = "true";
        for (int i = 0; t[i]; ++i) {
            if (quest_json_next(jr) != t[i]) quest_raise_dynamic_error();
        }
        QJsonValue *val = (QJsonValue *)quest_alloc(sizeof(QJsonValue));
        val->kind = QJSON_BOOL;
        val->u.b = true;
        return val;
    }
    if (ch == 'f') {
        const char *f = "false";
        for (int i = 0; f[i]; ++i) {
            if (quest_json_next(jr) != f[i]) quest_raise_dynamic_error();
        }
        QJsonValue *val = (QJsonValue *)quest_alloc(sizeof(QJsonValue));
        val->kind = QJSON_BOOL;
        val->u.b = false;
        return val;
    }
    if (ch == 'n') {
        const char *n = "null";
        for (int i = 0; n[i]; ++i) {
            if (quest_json_next(jr) != n[i]) quest_raise_dynamic_error();
        }
        QJsonValue *val = (QJsonValue *)quest_alloc(sizeof(QJsonValue));
        val->kind = QJSON_NULL;
        return val;
    }

    quest_raise_dynamic_error();
    return NULL;
}

static QJsonValue *quest_json_obj_get(const QJsonValue *obj, const char *key) {
    if (obj == NULL || obj->kind != QJSON_OBJECT) return NULL;
    for (size_t i = 0; i < obj->u.o.count; ++i) {
        if (strcmp(obj->u.o.entries[i].key, key) == 0) {
            return obj->u.o.entries[i].val;
        }
    }
    return NULL;
}

/* ------------------------------------------------------------------------- */
/* Quest Type Expression Parser                                              */
/* ------------------------------------------------------------------------- */

typedef enum QTypeTokenKind {
    TOK_EOF,
    TOK_IDENT,
    TOK_LPAREN,
    TOK_RPAREN,
    TOK_COLON,
    TOK_COMMA,
    TOK_RECORD,
    TOK_VAR,
    TOK_TUPLE,
    TOK_VARIANT,
    TOK_OPTION,
    TOK_ARRAY,
    TOK_END,
} QTypeTokenKind;

typedef struct QTypeLexer {
    const char     *src;
    size_t          pos;
    QTypeTokenKind  kind;
    char            text[128];
} QTypeLexer;

static void quest_type_lexer_next(QTypeLexer *lex) {
    while (lex->src[lex->pos] && isspace((unsigned char)lex->src[lex->pos])) {
        lex->pos++;
    }
    char c = lex->src[lex->pos];
    if (c == '\0') {
        lex->kind = TOK_EOF;
        lex->text[0] = '\0';
        return;
    }
    if (c == '(') {
        lex->kind = TOK_LPAREN;
        lex->text[0] = '('; lex->text[1] = '\0';
        lex->pos++;
        return;
    }
    if (c == ')') {
        lex->kind = TOK_RPAREN;
        lex->text[0] = ')'; lex->text[1] = '\0';
        lex->pos++;
        return;
    }
    if (c == ':') {
        lex->kind = TOK_COLON;
        lex->text[0] = ':'; lex->text[1] = '\0';
        lex->pos++;
        return;
    }
    if (c == ',') {
        lex->kind = TOK_COMMA;
        lex->text[0] = ','; lex->text[1] = '\0';
        lex->pos++;
        return;
    }

    if (isalpha((unsigned char)c) || c == '_') {
        size_t start = lex->pos;
        while (lex->src[lex->pos] &&
               (isalnum((unsigned char)lex->src[lex->pos]) ||
                lex->src[lex->pos] == '_' ||
                lex->src[lex->pos] == '.')) {
            lex->pos++;
        }
        size_t len = lex->pos - start;
        if (len >= sizeof(lex->text)) len = sizeof(lex->text) - 1;
        memcpy(lex->text, lex->src + start, len);
        lex->text[len] = '\0';

        if (strcmp(lex->text, "Record") == 0) lex->kind = TOK_RECORD;
        else if (strcmp(lex->text, "var") == 0) lex->kind = TOK_VAR;
        else if (strcmp(lex->text, "Tuple") == 0) lex->kind = TOK_TUPLE;
        else if (strcmp(lex->text, "Variant") == 0) lex->kind = TOK_VARIANT;
        else if (strcmp(lex->text, "Option") == 0) lex->kind = TOK_OPTION;
        else if (strcmp(lex->text, "Array") == 0) lex->kind = TOK_ARRAY;
        else if (strcmp(lex->text, "end") == 0) lex->kind = TOK_END;
        else lex->kind = TOK_IDENT;
        return;
    }

    quest_raise_dynamic_error();
}

typedef struct QParsedField {
    char                   name[64];
    const QTypeDescriptor *type;
    bool                   is_var;
} QParsedField;

static int quest_field_cmp(const void *a, const void *b) {
    const QParsedField *fa = (const QParsedField *)a;
    const QParsedField *fb = (const QParsedField *)b;
    return strcmp(fa->name, fb->name);
}

static const QTypeDescriptor *quest_parse_type_expr(QTypeLexer *lex) {
    if (lex->kind == TOK_IDENT) {
        char name[128];
        strncpy(name, lex->text, sizeof(name) - 1);
        name[sizeof(name) - 1] = '\0';
        quest_type_lexer_next(lex);

        if (strcmp(name, "Int") == 0) return &quest_type_Int;
        if (strcmp(name, "Real") == 0) return &quest_type_Real;
        if (strcmp(name, "Bool") == 0) return &quest_type_Bool;
        if (strcmp(name, "Char") == 0) return &quest_type_Char;
        if (strcmp(name, "String") == 0) return &quest_type_String;
        if (strcmp(name, "Ok") == 0) return &quest_type_Ok;
        if (strcmp(name, "Dynamic") == 0 || strcmp(name, "Dynamic.T") == 0) return &quest_type_Dynamic;
        const QTypeDescriptor *d = quest_lookup_type_descriptor_by_name(name);
        if (d != NULL) return d;
        quest_raise_dynamic_error();
    }

    if (lex->kind == TOK_ARRAY) {
        quest_type_lexer_next(lex);
        if (lex->kind != TOK_LPAREN) quest_raise_dynamic_error();
        quest_type_lexer_next(lex);
        const QTypeDescriptor *elem = quest_parse_type_expr(lex);
        if (lex->kind != TOK_RPAREN) quest_raise_dynamic_error();
        quest_type_lexer_next(lex);
        return quest_make_array_descriptor(elem);
    }

    if (lex->kind == TOK_RECORD) {
        quest_type_lexer_next(lex);
        QParsedField fields[64];
        size_t count = 0;
        while (lex->kind != TOK_END && lex->kind != TOK_EOF) {
            if (count >= 64) quest_raise_dynamic_error();
            bool is_var = false;
            if (lex->kind == TOK_VAR) {
                is_var = true;
                quest_type_lexer_next(lex);
            }
            if (lex->kind != TOK_IDENT) quest_raise_dynamic_error();
            strncpy(fields[count].name, lex->text, sizeof(fields[count].name) - 1);
            fields[count].name[sizeof(fields[count].name) - 1] = '\0';
            fields[count].is_var = is_var;
            quest_type_lexer_next(lex);
            if (lex->kind != TOK_COLON) quest_raise_dynamic_error();
            quest_type_lexer_next(lex);
            fields[count].type = quest_parse_type_expr(lex);
            count++;
        }
        if (lex->kind != TOK_END) quest_raise_dynamic_error();
        quest_type_lexer_next(lex);

        qsort(fields, count, sizeof(QParsedField), quest_field_cmp);

        size_t offset = 0;
        size_t max_align = sizeof(void *);
        QRecordFieldDescriptor *f_descs = (QRecordFieldDescriptor *)quest_alloc(
            sizeof(QRecordFieldDescriptor) * (count > 0 ? count : 1)
        );
        for (size_t i = 0; i < count; ++i) {
            const QTypeDescriptor *ft = fields[i].type;
            size_t align = (ft->kind == QTYPE_KIND_RECORD || ft->kind == QTYPE_KIND_VARIANT) ? 16 : 8;
            if (align > max_align) max_align = align;
            offset = (offset + align - 1) & ~(align - 1);
            f_descs[i].name = quest_dup_str(fields[i].name);
            f_descs[i].type = ft;
            f_descs[i].offset = offset;
            f_descs[i].is_var = fields[i].is_var;
            size_t sz = (ft->kind == QTYPE_KIND_RECORD || ft->kind == QTYPE_KIND_VARIANT) ? 16 : 8;
            offset += sz;
        }
        size_t total_size = (offset + max_align - 1) & ~(max_align - 1);

        size_t name_len = 16;
        for (size_t i = 0; i < count; ++i) {
            name_len += strlen(fields[i].name) + (fields[i].is_var ? 5 : 0) + 4;
            if (fields[i].type->name) name_len += strlen(fields[i].type->name);
        }
        char *c_name = (char *)quest_alloc_atomic(name_len);
        strcpy(c_name, "Record");
        for (size_t i = 0; i < count; ++i) {
            strcat(c_name, " ");
            if (fields[i].is_var) strcat(c_name, "var ");
            strcat(c_name, fields[i].name);
            strcat(c_name, ": ");
            strcat(c_name, fields[i].type->name ? fields[i].type->name : "Dynamic");
        }
        strcat(c_name, " end");

        return quest_make_record_descriptor(c_name, total_size, max_align, count, f_descs);
    }

    if (lex->kind == TOK_TUPLE) {
        quest_type_lexer_next(lex);
        const QTypeDescriptor *elem_types[64];
        size_t count = 0;
        while (lex->kind != TOK_END && lex->kind != TOK_EOF) {
            if (count >= 64) quest_raise_dynamic_error();
            if (lex->kind == TOK_COLON) {
                quest_type_lexer_next(lex);
            }
            elem_types[count++] = quest_parse_type_expr(lex);
        }
        if (lex->kind != TOK_END) quest_raise_dynamic_error();
        quest_type_lexer_next(lex);

        if (count == 0) return &quest_type_EmptyTuple;

        size_t offset = 0;
        size_t max_align = sizeof(void *);
        QTupleElementDescriptor *e_descs = (QTupleElementDescriptor *)quest_alloc(
            sizeof(QTupleElementDescriptor) * count
        );
        for (size_t i = 0; i < count; ++i) {
            const QTypeDescriptor *et = elem_types[i];
            size_t align = (et->kind == QTYPE_KIND_RECORD || et->kind == QTYPE_KIND_VARIANT) ? 16 : 8;
            if (align > max_align) max_align = align;
            offset = (offset + align - 1) & ~(align - 1);
            e_descs[i].name = NULL;
            e_descs[i].type = et;
            e_descs[i].offset = offset;
            size_t sz = (et->kind == QTYPE_KIND_RECORD || et->kind == QTYPE_KIND_VARIANT) ? 16 : 8;
            offset += sz;
        }
        size_t total_size = (offset + max_align - 1) & ~(max_align - 1);

        size_t name_len = 16;
        for (size_t i = 0; i < count; ++i) {
            if (elem_types[i]->name) name_len += strlen(elem_types[i]->name) + 4;
        }
        char *c_name = (char *)quest_alloc_atomic(name_len);
        strcpy(c_name, "Tuple");
        for (size_t i = 0; i < count; ++i) {
            strcat(c_name, " :");
            strcat(c_name, elem_types[i]->name ? elem_types[i]->name : "Dynamic");
        }
        strcat(c_name, " end");

        return quest_make_tuple_descriptor(c_name, total_size, max_align, count, e_descs);
    }

    if (lex->kind == TOK_VARIANT || lex->kind == TOK_OPTION) {
        bool is_opt = (lex->kind == TOK_OPTION);
        quest_type_lexer_next(lex);
        char case_names[64][64];
        const QTypeDescriptor *p_types[64];
        size_t count = 0;
        while (lex->kind != TOK_END && lex->kind != TOK_EOF) {
            if (count >= 64) quest_raise_dynamic_error();
            if (lex->kind != TOK_IDENT) quest_raise_dynamic_error();
            strncpy(case_names[count], lex->text, sizeof(case_names[count]) - 1);
            case_names[count][sizeof(case_names[count]) - 1] = '\0';
            quest_type_lexer_next(lex);
            if (lex->kind == TOK_COLON) {
                quest_type_lexer_next(lex);
                p_types[count] = quest_parse_type_expr(lex);
            } else {
                p_types[count] = &quest_type_Ok;
            }
            count++;
        }
        if (lex->kind != TOK_END) quest_raise_dynamic_error();
        quest_type_lexer_next(lex);

        QVariantCaseDescriptor *c_descs = (QVariantCaseDescriptor *)quest_alloc(
            sizeof(QVariantCaseDescriptor) * (count > 0 ? count : 1)
        );
        for (size_t i = 0; i < count; ++i) {
            c_descs[i].name = quest_dup_str(case_names[i]);
            c_descs[i].payload_type = p_types[i];
            c_descs[i].tag_index = (int64_t)i;
            c_descs[i].is_var = false;
        }

        size_t name_len = 16;
        for (size_t i = 0; i < count; ++i) {
            name_len += strlen(case_names[i]) + 4;
            if (p_types[i] && p_types[i]->kind != QTYPE_KIND_OK && p_types[i]->name) {
                name_len += strlen(p_types[i]->name) + 3;
            }
        }
        char *c_name = (char *)quest_alloc_atomic(name_len);
        strcpy(c_name, is_opt ? "Option" : "Variant");
        for (size_t i = 0; i < count; ++i) {
            strcat(c_name, " ");
            strcat(c_name, case_names[i]);
            if (p_types[i] && p_types[i]->kind != QTYPE_KIND_OK) {
                strcat(c_name, ": ");
                strcat(c_name, p_types[i]->name ? p_types[i]->name : "Dynamic");
            }
        }
        strcat(c_name, " end");

        return quest_make_variant_descriptor(
            c_name, is_opt ? sizeof(int64_t) : sizeof(QVariantVal), sizeof(void *), count, c_descs
        );
    }

    quest_raise_dynamic_error();
    return NULL;
}

const QTypeDescriptor *quest_parse_type_descriptor(const char *type_str) {
    if (type_str == NULL) quest_raise_dynamic_error();
    const QTypeDescriptor *found = quest_lookup_type_descriptor_by_name(type_str);
    if (found != NULL) return found;

    QTypeLexer lex;
    memset(&lex, 0, sizeof(lex));
    lex.src = type_str;
    lex.pos = 0;
    quest_type_lexer_next(&lex);
    const QTypeDescriptor *desc = quest_parse_type_expr(&lex);
    if (desc == NULL) quest_raise_dynamic_error();
    return desc;
}

/* ------------------------------------------------------------------------- */
/* JSOG Preallocation (Pass 1) and Value Decoding (Pass 2)                   */
/* ------------------------------------------------------------------------- */

typedef enum QIdKind {
    QID_KIND_RECORD,
    QID_KIND_ARRAY,
    QID_KIND_TUPLE,
} QIdKind;

typedef struct QIdEntry {
    const char            *id;
    QIdKind                kind;
    void                  *ptr;
    const void            *dict;
    const QTypeDescriptor *desc;
    struct QIdEntry       *next;
} QIdEntry;

typedef struct QIdTable {
    QIdEntry *head;
} QIdTable;

static QIdEntry *quest_id_find(QIdTable *table, const char *id) {
    for (QIdEntry *cur = table->head; cur != NULL; cur = cur->next) {
        if (strcmp(cur->id, id) == 0) return cur;
    }
    return NULL;
}

static void quest_id_insert(
    QIdTable *table, const char *id, QIdKind kind, void *ptr, const void *dict, const QTypeDescriptor *desc
) {
    QIdEntry *entry = (QIdEntry *)quest_alloc(sizeof(QIdEntry));
    entry->id = quest_dup_str(id);
    entry->kind = kind;
    entry->ptr = ptr;
    entry->dict = dict;
    entry->desc = desc;
    entry->next = table->head;
    table->head = entry;
}

static void quest_jsog_preallocate(QJsonValue *node, const QTypeDescriptor *desc, QIdTable *table) {
    if (node == NULL) return;
    if (node->kind == QJSON_OBJECT) {
        QJsonValue *t_val = quest_json_obj_get(node, "@type");
        QJsonValue *v_val = quest_json_obj_get(node, "@value");
        if (t_val != NULL && t_val->kind == QJSON_STRING && v_val != NULL) {
            const QTypeDescriptor *inner_desc = quest_parse_type_descriptor(t_val->u.s.str);
            quest_jsog_preallocate(v_val, inner_desc, table);
            return;
        }

        QJsonValue *id_val = quest_json_obj_get(node, "@id");
        if (id_val != NULL && id_val->kind == QJSON_STRING) {
            const char *id_str = id_val->u.s.str;
            if (quest_json_obj_get(node, "@array") != NULL) {
                QJsonValue *arr_node = quest_json_obj_get(node, "@array");
                int64_t len = arr_node ? (int64_t)arr_node->u.a.count : 0;
                const QArrayTypeDescriptor *meta = desc ? (const QArrayTypeDescriptor *)desc->extra : NULL;
                const QTypeDescriptor *elem_t = meta ? meta->element_type : NULL;
                void *arr_ptr;
                if (elem_t != NULL && elem_t->kind == QTYPE_KIND_RECORD) {
                    QArrayWideRecord *w_arr = quest_alloc(sizeof(int64_t) + sizeof(QRecordVal) * len);
                    w_arr->length = len;
                    arr_ptr = w_arr;
                } else if (elem_t != NULL && elem_t->kind == QTYPE_KIND_VARIANT) {
                    QArrayWideVariant *w_arr = quest_alloc(sizeof(int64_t) + sizeof(QVariantVal) * len);
                    w_arr->length = len;
                    arr_ptr = w_arr;
                } else {
                    QArray *arr = quest_alloc(sizeof(int64_t) + sizeof(QVal) * len);
                    arr->length = len;
                    arr_ptr = arr;
                }
                quest_id_insert(table, id_str, QID_KIND_ARRAY, arr_ptr, NULL, desc);
            } else if (quest_json_obj_get(node, "@tuple") != NULL) {
                size_t sz = (desc && desc->size > 0) ? desc->size : sizeof(void *);
                void *tup_ptr = quest_alloc(sz);
                quest_id_insert(table, id_str, QID_KIND_TUPLE, tup_ptr, NULL, desc);
            } else {
                size_t sz = (desc && desc->size > 0) ? desc->size : sizeof(void *);
                void *rec_ptr = quest_alloc(sz);
                const QRecordTypeDescriptor *meta = desc ? (const QRecordTypeDescriptor *)desc->extra : NULL;
                size_t f_count = meta ? meta->field_count : 0;
                size_t *dict = (size_t *)quest_alloc(sizeof(size_t) * (f_count > 0 ? f_count : 1));
                if (meta) {
                    for (size_t i = 0; i < f_count; ++i) {
                        dict[i] = meta->fields[i].offset;
                    }
                }
                quest_id_insert(table, id_str, QID_KIND_RECORD, rec_ptr, dict, desc);
            }
        }

        if (desc != NULL && desc->kind == QTYPE_KIND_RECORD) {
            const QRecordTypeDescriptor *meta = (const QRecordTypeDescriptor *)desc->extra;
            if (meta != NULL) {
                for (size_t i = 0; i < meta->field_count; ++i) {
                    QJsonValue *f_node = quest_json_obj_get(node, meta->fields[i].name);
                    if (f_node != NULL) {
                        quest_jsog_preallocate(f_node, meta->fields[i].type, table);
                    }
                }
            }
        } else if (desc != NULL && (desc->kind == QTYPE_KIND_VARIANT || desc->kind == QTYPE_KIND_OPTION)) {
            const QVariantTypeDescriptor *meta = (const QVariantTypeDescriptor *)desc->extra;
            if (meta != NULL) {
                for (size_t i = 0; i < node->u.o.count; ++i) {
                    if (strcmp(node->u.o.entries[i].key, "@id") == 0) continue;
                    for (size_t j = 0; j < meta->case_count; ++j) {
                        if (strcmp(meta->cases[j].name, node->u.o.entries[i].key) == 0) {
                            quest_jsog_preallocate(node->u.o.entries[i].val, meta->cases[j].payload_type, table);
                            break;
                        }
                    }
                }
            }
        } else if (quest_json_obj_get(node, "@array") != NULL) {
            QJsonValue *arr_node = quest_json_obj_get(node, "@array");
            const QArrayTypeDescriptor *meta = desc ? (const QArrayTypeDescriptor *)desc->extra : NULL;
            quest_jsog_preallocate(arr_node, meta ? meta->element_type : NULL, table);
        } else if (quest_json_obj_get(node, "@tuple") != NULL) {
            QJsonValue *tup_node = quest_json_obj_get(node, "@tuple");
            quest_jsog_preallocate(tup_node, desc, table);
        }
    } else if (node->kind == QJSON_ARRAY) {
        if (desc != NULL && desc->kind == QTYPE_KIND_ARRAY) {
            const QArrayTypeDescriptor *meta = (const QArrayTypeDescriptor *)desc->extra;
            const QTypeDescriptor *elem_t = meta ? meta->element_type : NULL;
            for (size_t i = 0; i < node->u.a.count; ++i) {
                quest_jsog_preallocate(node->u.a.items[i], elem_t, table);
            }
        } else if (desc != NULL && desc->kind == QTYPE_KIND_TUPLE) {
            const QTupleTypeDescriptor *meta = (const QTupleTypeDescriptor *)desc->extra;
            for (size_t i = 0; i < node->u.a.count; ++i) {
                const QTypeDescriptor *elem_t = (meta && i < meta->element_count) ? meta->elements[i].type : NULL;
                quest_jsog_preallocate(node->u.a.items[i], elem_t, table);
            }
        }
    }
}

static void quest_write_field_val(const QTypeDescriptor *t, void *ptr, QVal val) {
    if (t == NULL) return;
    switch (t->kind) {
        case QTYPE_KIND_INT:
        case QTYPE_KIND_BOOL:
        case QTYPE_KIND_CHAR:
            *(int64_t *)ptr = val.i;
            break;
        case QTYPE_KIND_REAL:
            *(double *)ptr = val.r;
            break;
        case QTYPE_KIND_RECORD:
            *(QRecordVal *)ptr = *(const QRecordVal *)val.p;
            break;
        case QTYPE_KIND_VARIANT:
            *(QVariantVal *)ptr = *(const QVariantVal *)val.p;
            break;
        default:
            *(void **)ptr = val.p;
            break;
    }
}

static QVal quest_jsog_decode_value(QJsonValue *node, const QTypeDescriptor *desc, QIdTable *table) {
    if (node == NULL || desc == NULL) {
        quest_raise_dynamic_error();
    }

    if (node->kind == QJSON_OBJECT) {
        QJsonValue *ref_val = quest_json_obj_get(node, "@ref");
        if (ref_val != NULL && ref_val->kind == QJSON_STRING) {
            QIdEntry *entry = quest_id_find(table, ref_val->u.s.str);
            if (entry == NULL) quest_raise_dynamic_error();
            if (entry->kind == QID_KIND_RECORD) {
                QRecordVal rec = { .val = entry->ptr, .dict = entry->dict };
                return (QVal){ .p = quest_record_box(rec) };
            } else {
                return (QVal){ .p = entry->ptr };
            }
        }
    }

    switch (desc->kind) {
        case QTYPE_KIND_INT: {
            if (node->kind != QJSON_INT) quest_raise_dynamic_error();
            return (QVal){ .i = node->u.i };
        }

        case QTYPE_KIND_REAL: {
            if (node->kind == QJSON_REAL) return (QVal){ .r = node->u.r };
            if (node->kind == QJSON_INT) return (QVal){ .r = (double)node->u.i };
            quest_raise_dynamic_error();
            break;
        }

        case QTYPE_KIND_BOOL: {
            if (node->kind != QJSON_BOOL) quest_raise_dynamic_error();
            return (QVal){ .i = node->u.b ? 1 : 0 };
        }

        case QTYPE_KIND_CHAR: {
            if (node->kind != QJSON_STRING || node->u.s.len != 1) quest_raise_dynamic_error();
            return (QVal){ .i = (unsigned char)node->u.s.str[0] };
        }

        case QTYPE_KIND_STRING: {
            if (node->kind != QJSON_STRING) quest_raise_dynamic_error();
            QString *qs = quest_string_new(node->u.s.str, (int64_t)node->u.s.len);
            return (QVal){ .p = (void *)qs };
        }

        case QTYPE_KIND_OK: {
            if (node->kind != QJSON_NULL) quest_raise_dynamic_error();
            return Q_OK_VAL;
        }

        case QTYPE_KIND_RECORD: {
            if (node->kind != QJSON_OBJECT) quest_raise_dynamic_error();
            const QRecordTypeDescriptor *meta = (const QRecordTypeDescriptor *)desc->extra;
            if (meta == NULL) quest_raise_dynamic_error();

            void *rec_buf = NULL;
            const void *rec_dict = NULL;

            QJsonValue *id_val = quest_json_obj_get(node, "@id");
            if (id_val != NULL && id_val->kind == QJSON_STRING) {
                QIdEntry *entry = quest_id_find(table, id_val->u.s.str);
                if (entry != NULL) {
                    rec_buf = entry->ptr;
                    rec_dict = entry->dict;
                }
            }
            if (rec_buf == NULL) {
                rec_buf = quest_alloc(desc->size > 0 ? desc->size : sizeof(void *));
                size_t *d = (size_t *)quest_alloc(sizeof(size_t) * (meta->field_count > 0 ? meta->field_count : 1));
                for (size_t i = 0; i < meta->field_count; ++i) {
                    d[i] = meta->fields[i].offset;
                }
                rec_dict = d;
            }

            for (size_t i = 0; i < meta->field_count; ++i) {
                const QRecordFieldDescriptor *f = &meta->fields[i];
                QJsonValue *f_node = quest_json_obj_get(node, f->name);
                if (f_node == NULL) quest_raise_dynamic_error();
                QVal f_val = quest_jsog_decode_value(f_node, f->type, table);
                quest_write_field_val(f->type, (char *)rec_buf + f->offset, f_val);
            }

            QRecordVal rec = { .val = rec_buf, .dict = rec_dict };
            return (QVal){ .p = quest_record_box(rec) };
        }

        case QTYPE_KIND_ARRAY: {
            QJsonValue *arr_node = node;
            QArray *arr = NULL;
            if (node->kind == QJSON_OBJECT) {
                QJsonValue *id_val = quest_json_obj_get(node, "@id");
                if (id_val != NULL && id_val->kind == QJSON_STRING) {
                    QIdEntry *entry = quest_id_find(table, id_val->u.s.str);
                    if (entry != NULL) arr = (QArray *)entry->ptr;
                }
                arr_node = quest_json_obj_get(node, "@array");
            }
            if (arr_node == NULL || arr_node->kind != QJSON_ARRAY) quest_raise_dynamic_error();

            const QArrayTypeDescriptor *meta = (const QArrayTypeDescriptor *)desc->extra;
            const QTypeDescriptor *elem_t = meta ? meta->element_type : NULL;
            int64_t len = (int64_t)arr_node->u.a.count;

            if (arr == NULL) {
                if (elem_t != NULL && elem_t->kind == QTYPE_KIND_RECORD) {
                    QArrayWideRecord *w_arr = quest_alloc(sizeof(int64_t) + sizeof(QRecordVal) * len);
                    w_arr->length = len;
                    arr = (QArray *)w_arr;
                } else if (elem_t != NULL && elem_t->kind == QTYPE_KIND_VARIANT) {
                    QArrayWideVariant *w_arr = quest_alloc(sizeof(int64_t) + sizeof(QVariantVal) * len);
                    w_arr->length = len;
                    arr = (QArray *)w_arr;
                } else {
                    arr = quest_alloc(sizeof(int64_t) + sizeof(QVal) * len);
                    arr->length = len;
                }
            }

            for (int64_t i = 0; i < len; ++i) {
                QVal elem_val = quest_jsog_decode_value(arr_node->u.a.items[i], elem_t, table);
                if (elem_t != NULL && elem_t->kind == QTYPE_KIND_RECORD) {
                    ((QArrayWideRecord *)arr)->data[i] = *(const QRecordVal *)elem_val.p;
                } else if (elem_t != NULL && elem_t->kind == QTYPE_KIND_VARIANT) {
                    ((QArrayWideVariant *)arr)->data[i] = *(const QVariantVal *)elem_val.p;
                } else {
                    arr->data[i] = elem_val;
                }
            }
            return (QVal){ .p = (void *)arr };
        }

        case QTYPE_KIND_TUPLE: {
            QJsonValue *tup_node = node;
            void *tup_buf = NULL;
            if (node->kind == QJSON_OBJECT) {
                QJsonValue *id_val = quest_json_obj_get(node, "@id");
                if (id_val != NULL && id_val->kind == QJSON_STRING) {
                    QIdEntry *entry = quest_id_find(table, id_val->u.s.str);
                    if (entry != NULL) tup_buf = entry->ptr;
                }
                tup_node = quest_json_obj_get(node, "@tuple");
            }
            if (tup_node == NULL || tup_node->kind != QJSON_ARRAY) quest_raise_dynamic_error();

            const QTupleTypeDescriptor *meta = (const QTupleTypeDescriptor *)desc->extra;
            if (meta == NULL) quest_raise_dynamic_error();
            if (tup_node->u.a.count < meta->element_count) quest_raise_dynamic_error();

            if (tup_buf == NULL) {
                tup_buf = quest_alloc(desc->size > 0 ? desc->size : sizeof(void *));
            }

            for (size_t i = 0; i < meta->element_count; ++i) {
                const QTupleElementDescriptor *elem = &meta->elements[i];
                QVal elem_val = quest_jsog_decode_value(tup_node->u.a.items[i], elem->type, table);
                quest_write_field_val(elem->type, (char *)tup_buf + elem->offset, elem_val);
            }
            return (QVal){ .p = tup_buf };
        }

        case QTYPE_KIND_VARIANT:
        case QTYPE_KIND_OPTION: {
            const QVariantTypeDescriptor *meta = (const QVariantTypeDescriptor *)desc->extra;
            if (meta == NULL) quest_raise_dynamic_error();

            if (node->kind == QJSON_STRING) {
                for (size_t i = 0; i < meta->case_count; ++i) {
                    if (strcmp(meta->cases[i].name, node->u.s.str) == 0) {
                        QVariantVal v = { .tag = meta->cases[i].tag_index, .payload = Q_OK_VAL };
                        return (QVal){ .p = quest_variant_box(v) };
                    }
                }
                quest_raise_dynamic_error();
            } else if (node->kind == QJSON_OBJECT) {
                for (size_t i = 0; i < node->u.o.count; ++i) {
                    if (strcmp(node->u.o.entries[i].key, "@id") == 0) continue;
                    for (size_t j = 0; j < meta->case_count; ++j) {
                        if (strcmp(meta->cases[j].name, node->u.o.entries[i].key) == 0) {
                            QVal payload = quest_jsog_decode_value(
                                node->u.o.entries[i].val, meta->cases[j].payload_type, table
                            );
                            QVariantVal v = { .tag = meta->cases[j].tag_index, .payload = payload };
                            return (QVal){ .p = quest_variant_box(v) };
                        }
                    }
                }
                quest_raise_dynamic_error();
            } else {
                quest_raise_dynamic_error();
            }
            break;
        }

        case QTYPE_KIND_DYNAMIC: {
            if (node->kind != QJSON_OBJECT) quest_raise_dynamic_error();
            QJsonValue *t_node = quest_json_obj_get(node, "@type");
            QJsonValue *v_node = quest_json_obj_get(node, "@value");
            if (t_node == NULL || t_node->kind != QJSON_STRING || v_node == NULL) {
                quest_raise_dynamic_error();
            }
            const QTypeDescriptor *inner_desc = quest_parse_type_descriptor(t_node->u.s.str);
            if (inner_desc == NULL) quest_raise_dynamic_error();
            QVal inner_val = quest_jsog_decode_value(v_node, inner_desc, table);
            QDynamic *dyn = quest_dynamic_new(inner_desc, inner_val);
            return (QVal){ .p = (void *)dyn };
        }

        default:
            quest_raise_dynamic_error();
            break;
    }

    return Q_OK_VAL;
}

/* ------------------------------------------------------------------------- */
/* Public Deserialization Interface                                          */
/* ------------------------------------------------------------------------- */

QDynamic *quest_dynamic_intern(QReader *rd) {
    if (rd == NULL || rd->is_closed) {
        quest_raise_dynamic_error();
    }

    QJsonReader jr;
    jr.rd = rd;
    jr.peek = -1;

    QJsonValue *root_json = quest_parse_json_value(&jr);
    if (jr.peek != -1) {
        rd->peek_char = jr.peek;
    }

    if (root_json == NULL || root_json->kind != QJSON_OBJECT) {
        quest_raise_dynamic_error();
    }

    QJsonValue *type_node = quest_json_obj_get(root_json, "@type");
    QJsonValue *value_node = quest_json_obj_get(root_json, "@value");
    if (type_node == NULL || type_node->kind != QJSON_STRING || value_node == NULL) {
        quest_raise_dynamic_error();
    }

    const QTypeDescriptor *desc = quest_parse_type_descriptor(type_node->u.s.str);
    if (desc == NULL) {
        quest_raise_dynamic_error();
    }

    QIdTable table;
    table.head = NULL;

    /* Pass 1: JSOG Pre-allocation */
    quest_jsog_preallocate(value_node, desc, &table);

    /* Pass 2: Value Decoding */
    QVal val = quest_jsog_decode_value(value_node, desc, &table);

    return quest_dynamic_new(desc, val);
}

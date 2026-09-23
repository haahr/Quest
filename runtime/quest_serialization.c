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

/* Stubs for Step 2 */
QDynamic *quest_dynamic_intern(QReader *rd) {
    (void)rd;
    quest_raise_dynamic_error();
    return NULL;
}

const QTypeDescriptor *quest_parse_type_descriptor(const char *type_str) {
    (void)type_str;
    quest_raise_dynamic_error();
    return NULL;
}

#ifndef QUEST_SERIALIZATION_H
#define QUEST_SERIALIZATION_H

#include "quest_runtime.h"

#ifdef __cplusplus
extern "C" {
#endif

void                   quest_dynamic_extern(QWriter *wr, const QDynamic *d);
QDynamic              *quest_dynamic_intern(QReader *rd);
const QTypeDescriptor *quest_parse_type_descriptor(const char *type_str);

#ifdef __cplusplus
}
#endif

#endif /* QUEST_SERIALIZATION_H */

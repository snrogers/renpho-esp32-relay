#ifndef RELAY_SHA256_H
#define RELAY_SHA256_H

#include <stddef.h>
#include <stdint.h>

void sha256(const uint8_t *data, size_t length, uint8_t out[32]);

#endif

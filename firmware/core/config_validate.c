#include "config_validate.h"

#include <ctype.h>
#include <string.h>

int id_charset_ok(const char *value) {
  size_t n;
  size_t i;
  if (!value) {
    return 0;
  }
  n = strlen(value);
  if (n < 1 || n > 128) {
    return 0;
  }
  for (i = 0; i < n; i++) {
    char c = value[i];
    if (!(isalnum((unsigned char)c) || c == '.' || c == '_' || c == ':' || c == '-')) {
      return 0;
    }
  }
  return 1;
}

int validate_device_id(const char *value) {
  return id_charset_ok(value);
}

int validate_receiver_url(const char *value) {
  const char *p;
  if (!value) {
    return 0;
  }
  if (strncmp(value, "http://", 7) != 0 && strncmp(value, "https://", 8) != 0) {
    return 0;
  }
  if (strchr(value, '@') || strchr(value, '?') || strchr(value, '#')) {
    return 0;
  }
  p = strstr(value, "://");
  if (!p || p[3] == 0 || p[3] == '/') {
    return 0;
  }
  if (strlen(value) >= CFG_URL) {
    return 0;
  }
  return 1;
}

int validate_scale_address(const char *value) {
  int  i;
  int  n;
  if (!value) {
    return 0;
  }
  n = (int)strlen(value);
  if (n == 0) {
    return 1; /* Empty: pair with the first R-MSC01 that speaks the protocol. */
  }
  if (n != 17) {
    return 0;
  }
  for (i = 0; i < 17; i++) {
    if ((i + 1) % 3 == 0) {
      if (value[i] != ':') {
        return 0;
      }
    } else if (!isxdigit((unsigned char)value[i])) {
      return 0;
    }
  }
  return 1;
}

int validate_wifi_ssid(const char *value) {
  return value && value[0] && strlen(value) < CFG_SSID;
}

int validate_wifi_password(const char *value) {
  return value && strlen(value) < CFG_PASS;
}

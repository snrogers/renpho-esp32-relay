#ifndef RELAY_CONFIG_VALIDATE_H
#define RELAY_CONFIG_VALIDATE_H

enum { CFG_STR = 129, CFG_URL = 257, CFG_SSID = 33, CFG_PASS = 65 };

int id_charset_ok(const char *value);
int validate_device_id(const char *value);
int validate_receiver_url(const char *value);
int validate_scale_address(const char *value);
int validate_wifi_ssid(const char *value);
int validate_wifi_password(const char *value);

#endif

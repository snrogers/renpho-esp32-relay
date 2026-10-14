#ifndef RELAY_USB_LINE_H
#define RELAY_USB_LINE_H

#include "config_validate.h"

enum { USB_LINE_MAX = 1024 };

typedef struct {
  char device_id[CFG_STR];
  char receiver_url[CFG_URL];
  char scale_address[18];
  char wifi_ssid[CFG_SSID];
  char wifi_password[CFG_PASS];
} usb_config_t;

int usb_extract_command(const char *line, char *command, int command_len);
int usb_parse_configure(const char *line, usb_config_t *cfg, char *error, int error_len);

#endif

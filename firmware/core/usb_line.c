#include "usb_line.h"

#include "http_parse.h"

#include <stdio.h>
#include <string.h>

int usb_extract_command(const char *line, char *command, int command_len) {
  return http_extract_json_string(line, "command", command, command_len);
}

static int require(const char *line, const char *key, char *out, int out_len,
                   char *error, int error_len) {
  if (!http_extract_json_string(line, key, out, out_len)) {
    snprintf(error, (size_t)error_len, "missing %s", key);
    return 0;
  }
  return 1;
}

int usb_parse_configure(const char *line, usb_config_t *cfg, char *error, int error_len) {
  char command[32];
  memset(cfg, 0, sizeof(*cfg));
  if (error_len > 0) {
    error[0] = 0;
  }
  if (!usb_extract_command(line, command, sizeof(command)) || strcmp(command, "configure") != 0) {
    snprintf(error, (size_t)error_len, "not configure");
    return 0;
  }
  if (!require(line, "deviceId", cfg->device_id, sizeof(cfg->device_id), error, error_len) ||
      !require(line, "receiverUrl", cfg->receiver_url, sizeof(cfg->receiver_url), error, error_len) ||
      !require(line, "scaleAddress", cfg->scale_address, sizeof(cfg->scale_address), error, error_len) ||
      !require(line, "wifiSsid", cfg->wifi_ssid, sizeof(cfg->wifi_ssid), error, error_len) ||
      !require(line, "wifiPassword", cfg->wifi_password, sizeof(cfg->wifi_password), error, error_len)) {
    return 0;
  }
  if (!validate_device_id(cfg->device_id)) {
    snprintf(error, (size_t)error_len, "invalid deviceId");
    return 0;
  }
  if (!validate_receiver_url(cfg->receiver_url)) {
    snprintf(error, (size_t)error_len, "invalid receiverUrl");
    return 0;
  }
  if (!validate_scale_address(cfg->scale_address)) {
    snprintf(error, (size_t)error_len, "invalid scaleAddress");
    return 0;
  }
  if (!validate_wifi_ssid(cfg->wifi_ssid)) {
    snprintf(error, (size_t)error_len, "invalid wifiSsid");
    return 0;
  }
  if (!validate_wifi_password(cfg->wifi_password)) {
    snprintf(error, (size_t)error_len, "invalid wifiPassword");
    return 0;
  }
  return 1;
}

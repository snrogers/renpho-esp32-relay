#include "relay.h"

#include "nvs.h"
#include "nvs_flash.h"

#include <stdlib.h>
#include <string.h>

static const char *CFG_NS   = "relay";
static const char *BOX_NS   = "outbox";
static const char *BOX_KEY  = "box";
static const char *BOX_PART = "outbox";

static int cfg_complete(const usb_config_t *cfg) {
  return memchr(cfg->device_id, 0, sizeof(cfg->device_id)) &&
         memchr(cfg->receiver_url, 0, sizeof(cfg->receiver_url)) &&
         memchr(cfg->scale_address, 0, sizeof(cfg->scale_address)) &&
         memchr(cfg->wifi_ssid, 0, sizeof(cfg->wifi_ssid)) &&
         memchr(cfg->wifi_password, 0, sizeof(cfg->wifi_password)) &&
         validate_device_id(cfg->device_id) &&
         validate_receiver_url(cfg->receiver_url) &&
         validate_scale_address(cfg->scale_address) &&
         validate_wifi_ssid(cfg->wifi_ssid) &&
         validate_wifi_password(cfg->wifi_password);
}

void store_load(void) {
  nvs_handle_t h;
  size_t       len;

  if (nvs_open(CFG_NS, NVS_READONLY, &h) == ESP_OK) {
    len = sizeof(g_relay.cfg);
    esp_err_t err = nvs_get_blob(h, "config", &g_relay.cfg, &len);
    nvs_close(h);
    g_relay.configured =
        err == ESP_OK && len == sizeof(g_relay.cfg) && cfg_complete(&g_relay.cfg);
  }

  if (g_relay.storage_ready) {
    esp_err_t err = nvs_open_from_partition(BOX_PART, BOX_NS, NVS_READONLY, &h);
    if (err == ESP_OK) {
      len = 0;
      err = nvs_get_blob(h, BOX_KEY, NULL, &len);
      if (err == ESP_ERR_NVS_NOT_FOUND) {
        nvs_close(h);
      } else if (err != ESP_OK ||
                 (len != sizeof(g_outbox) && len != (size_t)OUTBOX_OBX2_SIZE &&
                  len != (size_t)OUTBOX_LEGACY_SIZE)) {
        nvs_close(h);
        g_relay.storage_ready = 0;
      } else {
        void *blob = malloc(len);
        if (!blob) {
          nvs_close(h);
          g_relay.storage_ready = 0;
        } else {
          err = nvs_get_blob(h, BOX_KEY, blob, &len);
          nvs_close(h);
          if (err != ESP_OK || !outbox_restore(&g_outbox, blob, len)) {
            g_relay.storage_ready = 0;
          } else if (len != sizeof(g_outbox)) {
            if (store_save_outbox() != ESP_OK) {
              g_relay.storage_ready = 0;
            }
          }
          free(blob);
        }
      }
    } else if (err != ESP_ERR_NVS_NOT_FOUND) {
      g_relay.storage_ready = 0;
    }
  }
}

esp_err_t store_save_config(const usb_config_t *cfg) {
  nvs_handle_t h;
  esp_err_t    err = nvs_open(CFG_NS, NVS_READWRITE, &h);
  if (err != ESP_OK) {
    return err;
  }
  err = nvs_set_blob(h, "config", cfg, sizeof(*cfg));
  if (err == ESP_OK) {
    err = nvs_commit(h);
  }
  nvs_close(h);
  return err;
}

esp_err_t store_save_outbox(void) {
  if (!g_relay.storage_ready) {
    return ESP_ERR_INVALID_STATE;
  }
  nvs_handle_t h;
  esp_err_t    err = nvs_open_from_partition(BOX_PART, BOX_NS, NVS_READWRITE, &h);
  if (err != ESP_OK) {
    return err;
  }
  err = nvs_set_blob(h, BOX_KEY, &g_outbox, sizeof(g_outbox));
  if (err == ESP_OK) {
    err = nvs_commit(h);
  }
  nvs_close(h);
  return err;
}

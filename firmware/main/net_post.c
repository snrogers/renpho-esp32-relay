#include "relay.h"

#include "esp_crt_bundle.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "http_parse.h"

#include <stdio.h>
#include <string.h>

#include "freertos/task.h"

static int  s_backoff_ms    = 2000;
static char s_post_body[HTTP_READING_MAX + 1];

typedef struct {
  char *buf;
  int   cap;
  int   used;
  int   overflow;
} body_buf_t;

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
  (void)arg;
  (void)data;
  if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
    esp_wifi_connect();
  } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
    xSemaphoreTake(g_lock, portMAX_DELAY);
    g_relay.wifi_connected = 0;
    xSemaphoreGive(g_lock);
    esp_wifi_connect();
  } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
    xSemaphoreTake(g_lock, portMAX_DELAY);
    g_relay.wifi_connected = 1;
    xSemaphoreGive(g_lock);
  }
}

static esp_err_t http_evt(esp_http_client_event_t *evt) {
  body_buf_t *body = evt->user_data;
  if (evt->event_id == HTTP_EVENT_ON_DATA && evt->data && evt->data_len > 0 && body) {
    int n = evt->data_len;
    if (body->used + n > body->cap - 1) {
      body->overflow = 1;
      n = body->cap - 1 - body->used;
    }
    if (n > 0) {
      memcpy(body->buf + body->used, evt->data, (size_t)n);
      body->used += n;
      body->buf[body->used] = 0;
    }
  }
  return ESP_OK;
}

static int post_one(const outbox_record_t *rec, char *status_out, int status_len) {
  char       url[320];
  char       resp[512];
  body_buf_t cap = {.buf = resp, .cap = (int)sizeof(resp), .used = 0};
  int        n;

  status_out[0] = 0;
  resp[0]       = 0;
  n = http_format_reading(s_post_body, sizeof(s_post_body), g_relay.cfg.device_id, rec);
  if (n <= 0) {
    return 0;
  }
  snprintf(url, sizeof(url), "%s/api/scale-readings", g_relay.cfg.receiver_url);
  {
    esp_http_client_config_t cfg = {
        .url            = url,
        .method         = HTTP_METHOD_POST,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms     = 8000,
        .event_handler  = http_evt,
        .user_data      = &cap,
        .buffer_size    = 512,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    int                      code   = 0;
    esp_err_t                err;
    if (!client) {
      return 0;
    }
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, s_post_body, n);
    err  = esp_http_client_perform(client);
    code = err == ESP_OK ? esp_http_client_get_status_code(client) : 0;
    esp_http_client_cleanup(client);
    if (cap.overflow || !http_response_accepts(code, resp, rec->event_id)) {
      return 0;
    }
    return http_extract_json_string(resp, "status", status_out, status_len);
  }
}

static void net_task(void *arg) {
  static outbox_record_t  rec;
  (void)arg;
  for (;;) {
    int  send = 0;
    int  idx  = 0;
    char status[32];
    xSemaphoreTake(g_lock, portMAX_DELAY);
    send = g_relay.storage_ready && g_relay.configured && g_relay.wifi_connected &&
           outbox_find_sendable(&g_outbox, &idx);
    if (send) {
      rec = g_outbox.records[idx];
    }
    xSemaphoreGive(g_lock);
    if (!send) {
      vTaskDelay(pdMS_TO_TICKS(1000));
      continue;
    }
    if (post_one(&rec, status, sizeof(status))) {
      int persisted = 0;
      xSemaphoreTake(g_lock, portMAX_DELAY);
      if (outbox_accept_http(&g_outbox, &rec, status)) {
        if (store_save_outbox() == ESP_OK) {
          g_relay.ui = outbox_queued_count(&g_outbox) ? UI_QUEUED : UI_DELIVERED;
          persisted  = 1;
        } else {
          /* The in-flight slot stayed queued, so it could not be recycled. */
          g_outbox.records[idx].state = OUTBOX_QUEUED;
        }
      }
      xSemaphoreGive(g_lock);
      if (persisted) {
        board_lcd_activity();
        s_backoff_ms = 2000;
      } else {
        vTaskDelay(pdMS_TO_TICKS(s_backoff_ms));
        if (s_backoff_ms < 60000) {
          s_backoff_ms *= 2;
        }
      }
    } else {
      vTaskDelay(pdMS_TO_TICKS(s_backoff_ms));
      if (s_backoff_ms < 60000) {
        s_backoff_ms *= 2;
      }
    }
  }
}

void net_start(void) {
  if (!g_relay.configured) {
    return;
  }
  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();
  {
    wifi_init_config_t wifi_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wifi_cfg));
  }
  ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
  ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
  {
    wifi_config_t sta = {0};
    memcpy(sta.sta.ssid, g_relay.cfg.wifi_ssid, strlen(g_relay.cfg.wifi_ssid));
    memcpy(sta.sta.password, g_relay.cfg.wifi_password, strlen(g_relay.cfg.wifi_password));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta));
    ESP_ERROR_CHECK(esp_wifi_start());
  }
  xTaskCreate(net_task, "net", 8192, NULL, 5, NULL);
}

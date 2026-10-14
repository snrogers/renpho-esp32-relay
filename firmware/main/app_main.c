#include "relay.h"

#include "esp_log.h"
#include "nvs_flash.h"

relay_state_t        g_relay;
outbox_t             g_outbox;
SemaphoreHandle_t    g_lock;
QueueHandle_t        g_ble_frames;

static const char *TAG = "app";

static void lcd_task(void *arg) {
  (void)arg;
  for (;;) {
    board_lcd_refresh();
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}

static void init_nvs(void) {
  esp_err_t err = nvs_flash_init();
  if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_LOGW(TAG, "config nvs reset %s", esp_err_to_name(err));
    ESP_ERROR_CHECK(nvs_flash_erase());
    err = nvs_flash_init();
  }
  ESP_ERROR_CHECK(err);

  err = nvs_flash_init_partition("outbox");
  g_relay.storage_ready = err == ESP_OK;
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "outbox nvs init failed %s; leaving flash unmodified",
             esp_err_to_name(err));
  }
}

void app_main(void) {
  init_nvs();
  g_lock       = xSemaphoreCreateMutex();
  g_ble_frames = xQueueCreate(16, sizeof(ble_frame_msg_t));
  outbox_init(&g_outbox);
  store_load();
  g_relay.ui = g_relay.configured
                   ? (outbox_queued_count(&g_outbox) ? UI_QUEUED : UI_LISTENING)
                   : UI_SETUP;
  board_lcd_init();
  usb_console_start();
  net_start();
  ble_scale_start();
  xTaskCreate(lcd_task, "lcd", 4096, NULL, 3, NULL);
}

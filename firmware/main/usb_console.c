#include "relay.h"

#include "esp_system.h"

#include <stdio.h>
#include <string.h>

static void usb_task(void *arg) {
  char line[USB_LINE_MAX];
  int  n = 0;
  int  overflow = 0;
  (void)arg;
  for (;;) {
    int c = fgetc(stdin);
    if (c == EOF) {
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      if (overflow) {
        n = 0;
        overflow = 0;
        printf("{\"event\":\"configuration_error\",\"error\":\"line too long\"}\n");
        fflush(stdout);
        continue;
      }
      line[n] = 0;
      n       = 0;
      if (line[0] != '{') {
        continue;
      }
      char command[32];
      if (!usb_extract_command(line, command, sizeof(command))) {
        continue;
      }
      if (strcmp(command, "status") == 0) {
        xSemaphoreTake(g_lock, portMAX_DELAY);
        printf("{\"event\":\"status\",\"configured\":%s",
               g_relay.configured ? "true" : "false");
        if (g_relay.configured) {
          printf(",\"deviceId\":\"%s\",\"scaleAddress\":\"%s\"", g_relay.cfg.device_id,
                 g_relay.cfg.scale_address);
        }
        printf(",\"queued\":%d,\"storageReady\":%s,\"wifiConnected\":%s}\n",
               outbox_queued_count(&g_outbox), g_relay.storage_ready ? "true" : "false",
               g_relay.wifi_connected ? "true" : "false");
        xSemaphoreGive(g_lock);
        fflush(stdout);
        continue;
      }
      if (strcmp(command, "configure") == 0) {
        usb_config_t cfg;
        char         error[80];
        if (!usb_parse_configure(line, &cfg, error, sizeof(error))) {
          printf("{\"event\":\"configuration_error\",\"error\":\"%s\"}\n", error);
          fflush(stdout);
          continue;
        }
        if (store_save_config(&cfg) != ESP_OK) {
          printf("{\"event\":\"configuration_error\",\"error\":\"persist failed\"}\n");
          fflush(stdout);
          continue;
        }
        printf("{\"event\":\"configured\"}\n");
        fflush(stdout);
        vTaskDelay(pdMS_TO_TICKS(200));
        esp_restart();
      }
      continue;
    }
    if (!overflow) {
      if (n < USB_LINE_MAX - 1) {
        line[n++] = (char)c;
      } else {
        overflow = 1;
      }
    }
  }
}

void usb_console_start(void) {
  xTaskCreate(usb_task, "usb", 4096, NULL, 4, NULL);
}

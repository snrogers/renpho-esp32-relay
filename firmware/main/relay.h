#ifndef RELAY_APP_H
#define RELAY_APP_H

#include "config_validate.h"
#include "outbox.h"
#include "protocol.h"
#include "render.h"
#include "usb_line.h"

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

typedef struct {
  uint8_t  data[FRAME_MAX];
  uint32_t epoch;
  uint16_t len;
  uint16_t attr;
} ble_frame_msg_t;

typedef struct {
  usb_config_t cfg;
  int          configured;
  int          wifi_connected;
  ui_state_t   ui;
  int          error;
  int          storage_ready;
} relay_state_t;

extern relay_state_t     g_relay;
extern outbox_t          g_outbox;
extern SemaphoreHandle_t g_lock;
extern QueueHandle_t     g_ble_frames;

void      store_load(void);
esp_err_t store_save_config(const usb_config_t *cfg);
esp_err_t store_save_outbox(void);

void board_lcd_init(void);
void board_lcd_refresh(void);
void board_lcd_activity(void);

void ble_scale_start(void);
void net_start(void);
void usb_console_start(void);

void relay_apply_measurement(const packet_t *packet, const packet_t *device_info,
                             const decoded_t *decoded, int *acked);

#endif

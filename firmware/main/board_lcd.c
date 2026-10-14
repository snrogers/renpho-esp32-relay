#include "relay.h"

#include "driver/ledc.h"
#include "driver/spi_master.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_timer.h"

#include "freertos/task.h"

#include <stdlib.h>
#include <stdatomic.h>
#include <string.h>

enum {
  PIN_MOSI = 45,
  PIN_SCLK = 40,
  PIN_CS   = 42,
  PIN_DC   = 41,
  PIN_RST  = 39,
  PIN_BL   = 48,
  /* Vendor ST7789.h Offset_X / LVGL flush; ST7789 native 240-wide, 172 visible. */
  GAP_X = 34,
  GAP_Y = 0,
  STRIP_H = 20,
  STRIP_PX = LCD_W * STRIP_H,
  DIM_MS = 30000
};

static esp_lcd_panel_handle_t s_panel;
static uint16_t              *s_fb;
static uint16_t              *s_strip;
static atomic_int             s_xfer_done = 1;
static atomic_uint_least32_t  s_last_activity_ms;
static ui_model_t             s_shown;
static int                    s_have_shown;
static int                    s_ready;

static bool on_color_done(esp_lcd_panel_io_handle_t io, esp_lcd_panel_io_event_data_t *edata,
                          void *user_ctx) {
  (void)io;
  (void)edata;
  (void)user_ctx;
  atomic_store_explicit(&s_xfer_done, 1, memory_order_release);
  return false;
}

static int wait_xfer(void) {
  int i;
  for (i = 0; i < 80 && !atomic_load_explicit(&s_xfer_done, memory_order_acquire); i++) {
    vTaskDelay(1);
  }
  return atomic_load_explicit(&s_xfer_done, memory_order_acquire);
}

static void backlight(int bright) {
  static int previous = -1;
  if (bright != previous) {
    ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, bright ? 4095 : 256));
    ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0));
    previous = bright;
  }
}

static uint32_t now_ms(void) {
  return (uint32_t)(esp_timer_get_time() / 1000);
}

void board_lcd_activity(void) {
  atomic_store_explicit(&s_last_activity_ms, now_ms(), memory_order_relaxed);
}

static int model_unchanged(const ui_model_t *a, const ui_model_t *b) {
  return a->state == b->state && a->has_weight == b->has_weight &&
         a->weight_grams == b->weight_grams && a->queued == b->queued &&
         a->backlight_dim == b->backlight_dim;
}

static int stream_frame(void) {
  int y;

  for (y = 0; y < LCD_H; y += STRIP_H) {
    int h = STRIP_H;
    if (y + h > LCD_H) {
      h = LCD_H - y;
    }
    if (!wait_xfer()) {
      return 0;
    }
    memcpy(s_strip, s_fb + (size_t)y * LCD_W, (size_t)h * LCD_W * sizeof(uint16_t));
    atomic_store_explicit(&s_xfer_done, 0, memory_order_release);
    if (esp_lcd_panel_draw_bitmap(s_panel, 0, y, LCD_W, y + h, s_strip) != ESP_OK) {
      atomic_store_explicit(&s_xfer_done, 1, memory_order_release);
      return 0;
    }
  }
  return 1;
}

static void panel_settings(esp_lcd_panel_io_handle_t io) {
  /* Waveshare's ESP-IDF Vernon_ST7789T initialization, including its LCM
   * control (required for the BGR/MX settings below) and calibrated gamma.
   * D0 takes both power-control bytes, as in the vendor Arduino driver. */
  static const uint8_t commands[] = {
    0xB0,  2, 0x00, 0xE8,
    0xB2,  5, 0x0C, 0x0C, 0x00, 0x33, 0x33,
    0xB7,  1, 0x75,
    0xBB,  1, 0x1A,
    0xC0,  1, 0x80,
    0xC2,  2, 0x01, 0xFF,
    0xC3,  1, 0x13,
    0xC4,  1, 0x20,
    0xC6,  1, 0x0F,
    0xD0,  2, 0xA4, 0xA1,
    0xE0, 14, 0xD0, 0x0D, 0x14, 0x0D, 0x0D, 0x09, 0x38, 0x44, 0x4E, 0x3A, 0x17, 0x18, 0x2F, 0x30,
    0xE1, 14, 0xD0, 0x09, 0x0F, 0x08, 0x07, 0x14, 0x37, 0x44, 0x4D, 0x38, 0x15, 0x16, 0x2C, 0x2E,
  };
  for (size_t i = 0; i < sizeof(commands); i += 2 + commands[i + 1]) {
    ESP_ERROR_CHECK(esp_lcd_panel_io_tx_param(io, commands[i], commands + i + 2, commands[i + 1]));
  }
}

void board_lcd_init(void) {
  esp_lcd_panel_io_handle_t io;
  spi_bus_config_t bus = {
      .mosi_io_num     = PIN_MOSI,
      .miso_io_num     = -1,
      .sclk_io_num     = PIN_SCLK,
      .quadwp_io_num   = -1,
      .quadhd_io_num   = -1,
      .max_transfer_sz = STRIP_PX * (int)sizeof(uint16_t) + 8,
  };

  s_fb = heap_caps_malloc((size_t)LCD_W * LCD_H * sizeof(uint16_t), MALLOC_CAP_SPIRAM);
  s_strip = heap_caps_malloc((size_t)STRIP_PX * sizeof(uint16_t),
                             MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
  if (!s_fb || !s_strip) {
    abort();
  }

  ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &bus, SPI_DMA_CH_AUTO));

  {
    esp_lcd_panel_io_spi_config_t io_cfg = {
        .dc_gpio_num         = PIN_DC,
        .cs_gpio_num         = PIN_CS,
        .pclk_hz             = 12 * 1000 * 1000,
        .lcd_cmd_bits        = 8,
        .lcd_param_bits      = 8,
        .spi_mode            = 0,
        .trans_queue_depth   = 4,
        .on_color_trans_done = on_color_done,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)SPI3_HOST, &io_cfg, &io));

    {
      esp_lcd_panel_dev_config_t panel_cfg = {
          .reset_gpio_num = PIN_RST,
          .rgb_ele_order  = LCD_RGB_ELEMENT_ORDER_BGR,
          .data_endian    = LCD_RGB_DATA_ENDIAN_LITTLE,
          .bits_per_pixel = 16,
      };
      ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(io, &panel_cfg, &s_panel));
    }
  }
  ESP_ERROR_CHECK(esp_lcd_panel_reset(s_panel));
  ESP_ERROR_CHECK(esp_lcd_panel_init(s_panel));
  panel_settings(io);
  ESP_ERROR_CHECK(esp_lcd_panel_set_gap(s_panel, GAP_X, GAP_Y));
  ESP_ERROR_CHECK(esp_lcd_panel_invert_color(s_panel, true));
  /* Rotated 180 degrees; the 172 visible columns sit centered in 240, so GAP_X holds. */
  ESP_ERROR_CHECK(esp_lcd_panel_mirror(s_panel, false, true));
  ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(s_panel, true));

  {
    ledc_timer_config_t timer = {
        .speed_mode      = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_12_BIT,
        .timer_num       = LEDC_TIMER_0,
        .freq_hz         = 5000,
        .clk_cfg         = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer));
  }
  {
    ledc_channel_config_t ch = {
        .gpio_num   = PIN_BL,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel    = LEDC_CHANNEL_0,
        .timer_sel  = LEDC_TIMER_0,
        .duty       = 4095,
        .hpoint     = 0,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&ch));
  }
  s_ready = 1;
  board_lcd_activity();
  board_lcd_refresh();
}

void board_lcd_refresh(void) {
  ui_model_t model;
  uint32_t   last;

  if (!s_ready) {
    return;
  }

  memset(&model, 0, sizeof(model));
  xSemaphoreTake(g_lock, portMAX_DELAY);
  model.state  = !g_relay.storage_ready                                ? UI_ERROR
                 : g_relay.configured && !g_relay.cfg.scale_address[0] ? UI_PAIRING
                                                                       : g_relay.ui;
  model.queued = outbox_queued_count(&g_outbox);
  {
    const outbox_record_t *latest = outbox_latest(&g_outbox);
    if (latest) {
      model.has_weight   = 1;
      model.weight_grams = latest->weight_grams;
    }
  }
  xSemaphoreGive(g_lock);

  last = atomic_load_explicit(&s_last_activity_ms, memory_order_relaxed);
  model.backlight_dim = (uint32_t)(now_ms() - last) > DIM_MS;
  backlight(!model.backlight_dim);

  if (s_have_shown && model_unchanged(&model, &s_shown)) {
    return;
  }

  render_frame(s_fb, &model);
  if (!stream_frame()) {
    return;
  }
  s_shown      = model;
  s_have_shown = 1;
}

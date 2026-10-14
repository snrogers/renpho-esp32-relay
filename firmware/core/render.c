#include "render.h"

#include <stdio.h>
#include <string.h>

static const uint8_t FONT[96][5] = {
    {0, 0, 0, 0, 0}, {0, 0, 0x5f, 0, 0}, {0, 7, 0, 7, 0}, {0x14, 0x7f, 0x14, 0x7f, 0x14},
    {0x24, 0x2a, 0x7f, 0x2a, 0x12}, {0x23, 0x13, 0x08, 0x64, 0x62}, {0x36, 0x49, 0x55, 0x22, 0x50},
    {0, 5, 3, 0, 0}, {0, 0x1c, 0x22, 0x41, 0}, {0, 0x41, 0x22, 0x1c, 0}, {0x14, 8, 0x3e, 8, 0x14},
    {8, 8, 0x3e, 8, 8}, {0, 0x50, 0x30, 0, 0}, {8, 8, 8, 8, 8}, {0, 0x60, 0x60, 0, 0},
    {0x20, 0x10, 8, 4, 2}, {0x3e, 0x51, 0x49, 0x45, 0x3e}, {0, 0x42, 0x7f, 0x40, 0},
    {0x42, 0x61, 0x51, 0x49, 0x46}, {0x21, 0x41, 0x45, 0x4b, 0x31}, {0x18, 0x14, 0x12, 0x7f, 0x10},
    {0x27, 0x45, 0x45, 0x45, 0x39}, {0x3c, 0x4a, 0x49, 0x49, 0x30}, {1, 0x71, 9, 5, 3},
    {0x36, 0x49, 0x49, 0x49, 0x36}, {6, 0x49, 0x49, 0x29, 0x1e}, {0, 0x36, 0x36, 0, 0},
    {0, 0x56, 0x36, 0, 0}, {8, 0x14, 0x22, 0x41, 0}, {0x14, 0x14, 0x14, 0x14, 0x14},
    {0, 0x41, 0x22, 0x14, 8}, {2, 1, 0x51, 9, 6}, {0x32, 0x49, 0x79, 0x41, 0x3e},
    {0x7e, 0x11, 0x11, 0x11, 0x7e}, {0x7f, 0x49, 0x49, 0x49, 0x36}, {0x3e, 0x41, 0x41, 0x41, 0x22},
    {0x7f, 0x41, 0x41, 0x22, 0x1c}, {0x7f, 0x49, 0x49, 0x49, 0x41}, {0x7f, 9, 9, 9, 1},
    {0x3e, 0x41, 0x49, 0x49, 0x7a}, {0x7f, 8, 8, 8, 0x7f}, {0, 0x41, 0x7f, 0x41, 0},
    {0x20, 0x40, 0x41, 0x3f, 1}, {0x7f, 8, 0x14, 0x22, 0x41}, {0x7f, 0x40, 0x40, 0x40, 0x40},
    {0x7f, 2, 0x0c, 2, 0x7f}, {0x7f, 4, 8, 0x10, 0x7f}, {0x3e, 0x41, 0x41, 0x41, 0x3e},
    {0x7f, 9, 9, 9, 6}, {0x3e, 0x41, 0x51, 0x21, 0x5e}, {0x7f, 9, 0x19, 0x29, 0x46},
    {0x46, 0x49, 0x49, 0x49, 0x31}, {1, 1, 0x7f, 1, 1}, {0x3f, 0x40, 0x40, 0x40, 0x3f},
    {0x1f, 0x20, 0x40, 0x20, 0x1f}, {0x3f, 0x40, 0x38, 0x40, 0x3f}, {0x63, 0x14, 8, 0x14, 0x63},
    {7, 8, 0x70, 8, 7}, {0x61, 0x51, 0x49, 0x45, 0x43}, {0, 0x7f, 0x41, 0x41, 0},
    {2, 4, 8, 0x10, 0x20}, {0, 0x41, 0x41, 0x7f, 0}, {4, 2, 1, 2, 4}, {0x40, 0x40, 0x40, 0x40, 0x40},
    {0, 1, 2, 4, 0}, {0x20, 0x54, 0x54, 0x54, 0x78}, {0x7f, 0x48, 0x44, 0x44, 0x38},
    {0x38, 0x44, 0x44, 0x44, 0x20}, {0x38, 0x44, 0x44, 0x48, 0x7f}, {0x38, 0x54, 0x54, 0x54, 0x18},
    {8, 0x7e, 9, 1, 2}, {0x0c, 0x52, 0x52, 0x52, 0x3e}, {0x7f, 8, 4, 4, 0x78}, {0, 0x44, 0x7d, 0x40, 0},
    {0x20, 0x40, 0x44, 0x3d, 0}, {0x7f, 0x10, 0x28, 0x44, 0}, {0, 0x41, 0x7f, 0x40, 0},
    {0x7c, 4, 0x18, 4, 0x78}, {0x7c, 8, 4, 4, 0x78}, {0x38, 0x44, 0x44, 0x44, 0x38},
    {0x7c, 0x14, 0x14, 0x14, 8}, {8, 0x14, 0x14, 0x18, 0x7c}, {0x7c, 8, 4, 4, 8},
    {0x48, 0x54, 0x54, 0x54, 0x20}, {4, 0x3f, 0x44, 0x40, 0x20}, {0x3c, 0x40, 0x40, 0x20, 0x7c},
    {0x1c, 0x20, 0x40, 0x20, 0x1c}, {0x3c, 0x40, 0x30, 0x40, 0x3c}, {0x44, 0x28, 8, 0x28, 0x44},
    {0x0c, 0x50, 0x50, 0x50, 0x3c}, {0x44, 0x64, 0x54, 0x4c, 0x44}, {0, 8, 0x36, 0x41, 0},
    {0, 0, 0x7f, 0, 0}, {0, 0x41, 0x36, 8, 0}, {8, 4, 8, 0x10, 8}, {0x08, 0x1c, 0x2a, 8, 8},
};

static uint16_t rgb(int r, int g, int b) {
  return (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
}

static void put_pixel(uint16_t *fb, int x, int y, uint16_t color) {
  if ((unsigned)x < LCD_W && (unsigned)y < LCD_H) {
    fb[y * LCD_W + x] = color;
  }
}

static void fill(uint16_t *fb, uint16_t color) {
  int i;
  for (i = 0; i < LCD_W * LCD_H; i++) {
    fb[i] = color;
  }
}

static void draw_char(uint16_t *fb, int x, int y, char c, uint16_t color, int scale) {
  int           col;
  int           row;
  unsigned      idx;
  unsigned char uc = (unsigned char)c;

  if (uc < 32 || uc > 127) {
    uc = '?';
  }
  idx = (unsigned)(uc - 32);
  for (col = 0; col < 5; col++) {
    uint8_t bits = FONT[idx][col];
    for (row = 0; row < 7; row++) {
      if (bits & (1u << row)) {
        for (int dy = 0; dy < scale; dy++) {
          for (int dx = 0; dx < scale; dx++) {
            put_pixel(fb, x + col * scale + dx, y + row * scale + dy, color);
          }
        }
      }
    }
  }
}

static void draw_text(uint16_t *fb, int x, int y, const char *text, uint16_t color, int scale) {
  while (*text) {
    draw_char(fb, x, y, *text, color, scale);
    x += 6 * scale;
    text++;
  }
}

static void draw_centered(uint16_t *fb, int y, const char *text, uint16_t color, int scale) {
  draw_text(fb, (LCD_W - (int)strlen(text) * 6 * scale) / 2, y, text, color, scale);
}

ui_state_t ui_after_idle(ui_state_t state, uint32_t idle_ms) {
  return state == UI_DELIVERED && idle_ms >= RESULT_MS ? UI_LISTENING : state;
}

void render_frame(uint16_t *fb, const ui_model_t *model) {
  uint16_t bg = rgb(8, 12, 20);
  uint16_t fg = rgb(240, 240, 240);
  uint16_t accent = rgb(80, 180, 255);
  char line[48];
  const char *state = "Listening";

  if (model->backlight_dim) {
    fg = rgb(160, 168, 176);
  }
  fill(fb, bg);
  switch (model->state) {
  case UI_SETUP:
    state = "USB setup";
    break;
  case UI_ERROR:
    state = "Storage error";
    accent = rgb(255, 100, 100);
    break;
  case UI_QUEUED:
    state = "Queued";
    accent = rgb(255, 190, 72);
    break;
  case UI_DELIVERED:
    state = "Delivered";
    accent = rgb(100, 220, 172);
    break;
  case UI_PAIRING:
    state = "Pairing";
    break;
  default:
    break;
  }
  draw_text(fb, 12, 16, "RENPHO RELAY", accent, 1);
  draw_text(fb, (LCD_W - (int)strlen(state) * 12) / 2, 43, state, accent, 2);
  if (model->state == UI_PAIRING) {
    /* No scale yet: a stored weight would suggest a scale is already paired. */
    draw_centered(fb, 91, "Step onto", fg, 2);
    draw_centered(fb, 115, "the scale", fg, 2);
    draw_centered(fb, 150, "to pair this relay", fg, 1);
  } else if (model->state == UI_ERROR) {
    /* The relay cannot save measurements: do not invite a weigh-in or show a weight. */
    draw_centered(fb, 91, "Readings", fg, 2);
    draw_centered(fb, 115, "not saved", fg, 2);
    draw_centered(fb, 150, "Keep a flash backup", fg, 1);
  } else if (model->has_weight && (model->state == UI_QUEUED || model->state == UI_DELIVERED)) {
    /* Only a measurement in progress shows a weight. The waiting screens show none. */
    unsigned lb_tenths = (unsigned)(((uint64_t)model->weight_grams * 1000000u + 22679618u) / 45359237u);
    snprintf(line, sizeof(line), "%u.%u", lb_tenths / 10, lb_tenths % 10);
    draw_text(fb, (LCD_W - (int)strlen(line) * 24) / 2, 91, line, fg, 4);
    draw_text(fb, (LCD_W - 24) / 2, 132, "lb", fg, 2);
    snprintf(line, sizeof(line), "%u.%02u kg",
             (unsigned)(model->weight_grams / 1000u),
             (unsigned)((model->weight_grams % 1000u) / 10u));
    draw_text(fb, (LCD_W - (int)strlen(line) * 6) / 2, 159, line, fg, 1);
  } else {
    draw_text(fb, 62, 91, "--", fg, 4);
    draw_text(fb, 26, 143, "Waiting for weight", fg, 1);
  }
  for (int x = 12; x < LCD_W - 12; x++) {
    put_pixel(fb, x, 181, accent);
  }
  draw_centered(fb, 209,
                model->state == UI_SETUP     ? "Configure over USB"
                : model->state == UI_PAIRING ? "Looking for R-MSC01"
                : model->state == UI_ERROR   ? "See the firmware guide"
                                             : "Step onto the scale",
                fg, 1);
  snprintf(line, sizeof(line), "%d locally queued", model->queued);
  draw_text(fb, (LCD_W - (int)strlen(line) * 6) / 2, 293, line, accent, 1);
}

int render_ppm(const uint16_t *fb, const char *path) {
  FILE *fp = fopen(path, "wb");
  int   i;
  if (!fp) {
    return -1;
  }
  fprintf(fp, "P6\n%d %d\n255\n", LCD_W, LCD_H);
  for (i = 0; i < LCD_W * LCD_H; i++) {
    uint16_t c = fb[i];
    uint8_t  rgb8[3];
    rgb8[0] = (uint8_t)(((c >> 11) & 31) * 255 / 31);
    rgb8[1] = (uint8_t)(((c >> 5) & 63) * 255 / 63);
    rgb8[2] = (uint8_t)((c & 31) * 255 / 31);
    fwrite(rgb8, 1, 3, fp);
  }
  fclose(fp);
  return 0;
}

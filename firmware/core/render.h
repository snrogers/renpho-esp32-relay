#ifndef RELAY_RENDER_H
#define RELAY_RENDER_H

#include <stdint.h>

enum { LCD_W = 172, LCD_H = 320 };

/* How long the Delivered screen stays before the relay waits for the next measurement. */
enum { RESULT_MS = 30000 };

typedef enum {
  UI_SETUP = 0,
  UI_ERROR,
  UI_LISTENING,
  UI_QUEUED,
  UI_DELIVERED,
  UI_PAIRING
} ui_state_t;

typedef struct {
  ui_state_t  state;
  int         has_weight;
  uint32_t    weight_grams;
  int         queued;
  int         backlight_dim;
} ui_model_t;

ui_state_t ui_after_idle(ui_state_t state, uint32_t idle_ms);
void       render_frame(uint16_t *fb, const ui_model_t *model);
int        render_ppm(const uint16_t *fb, const char *path);

#endif

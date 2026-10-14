/* Render each LCD screen with the firmware renderer and save it as a PPM file. */
#include <stdio.h>

#include "render.h"

typedef struct {
  const char *name;
  ui_model_t  model;
} screen_t;

/* 75.00 kg is an example weight. The relay shows the latest stored weight. */
static const screen_t SCREENS[] = {
    {"setup", {UI_SETUP, 0, 0, 0, 0}},
    {"pairing", {UI_PAIRING, 0, 0, 0, 0}},
    {"listening", {UI_LISTENING, 0, 0, 0, 0}},
    {"queued", {UI_QUEUED, 1, 75000, 1, 0}},
    {"delivered", {UI_DELIVERED, 1, 75000, 0, 0}},
    {"storage-error", {UI_ERROR, 0, 0, 0, 0}},
};

int main(int argc, char **argv) {
  static uint16_t fb[LCD_W * LCD_H];
  char            path[512];

  if (argc != 2) {
    fprintf(stderr, "usage: screens OUTPUT_DIRECTORY\n");
    return 2;
  }
  for (size_t i = 0; i < sizeof(SCREENS) / sizeof(SCREENS[0]); i++) {
    snprintf(path, sizeof(path), "%s/%s.ppm", argv[1], SCREENS[i].name);
    render_frame(fb, &SCREENS[i].model);
    if (render_ppm(fb, path) != 0) {
      fprintf(stderr, "cannot write %s\n", path);
      return 1;
    }
    puts(SCREENS[i].name);
  }
  return 0;
}

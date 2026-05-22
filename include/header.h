#include <Arduino.h>
#include "epd_driver.h"
#include "firasans.h"

#define BOARDER_X 15
#define BOARDER_Y 39

uint8_t *framebuffer;
void draw_icon(const uint8_t *bitmap, int x, int y, uint8_t *fb);
void printLine(const char *text, int y, const uint8_t *icon = NULL);
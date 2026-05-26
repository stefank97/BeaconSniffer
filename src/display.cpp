#include "display.h"
#include "epd_driver.h"
#include "firasans.h"

#define BOARDER_X 15
#define BOARDER_Y 39

static uint8_t *framebuffer = NULL;

namespace Display {

  //AI Function for Sniffing emoji
  static void drawIcon(const uint8_t *bitmap, int x, int y, uint8_t *fb) {
      for (int page_y = 0; page_y < 32; page_y++) {
          for (int page_x = 0; page_x < 32; page_x++) {
              int pixel_pos = page_y * 32 + page_x;
              if (!(bitmap[pixel_pos / 8] & (1 << (7 - (pixel_pos % 8))))) {
                  epd_draw_pixel(x + page_x, y + page_y, 0, fb);
              }
          }
      }
  }

  void init() {
    framebuffer = (uint8_t *)ps_calloc(sizeof(uint8_t), EPD_WIDTH * EPD_HEIGHT / 2);
    if (!framebuffer) {
      Serial.println("PSRAM allocation failed.");
      while (1);
    }

    memset(framebuffer, 0xFF, EPD_WIDTH * EPD_HEIGHT / 2);

    epd_init();
    epd_clear();
  }

  void refresh() {
    epd_poweron();
    epd_clear();
    epd_draw_grayscale_image(epd_full_screen(), framebuffer);
    epd_poweroff();
  }

  void printLine(int line, const char *text, const uint8_t *icon) {
    int y = BOARDER_Y * (line + 1);
    int cursor_x = BOARDER_X;
    int cursor_y = y;

    writeln((GFXfont *)&FiraSans, text, &cursor_x, &cursor_y, framebuffer);

    if (icon != nullptr) {
      drawIcon(icon, cursor_x + 10, y - 24, framebuffer);
    }
  } 

  void clear() {
    memset(framebuffer, 0xFF, EPD_WIDTH * EPD_HEIGHT / 2);
  }

  void refreshLine(int firstLine, int lineCount) {
    int y = BOARDER_Y * (firstLine + 1);
    int height = BOARDER_Y * lineCount;

    if (y + height > EPD_HEIGHT) {
      height = EPD_HEIGHT - y;
    }

    Rect_t area = {
      .x = 0,
      .y = y,
      .width = EPD_WIDTH,
      .height = height
    };

    epd_poweron();
    epd_clear_area(area);
    epd_draw_grayscale_image(area, framebuffer + y * EPD_WIDTH / 2);
    epd_poweroff();
  }

  void clearLine(int firstLine, int lineCount) {
    int y = BOARDER_Y * (firstLine + 1);
    int height = BOARDER_Y * lineCount;

    if (y + height > EPD_HEIGHT) {
      height = EPD_HEIGHT - y;
    }

    memset(framebuffer + y * EPD_WIDTH / 2, 0xFF, height * EPD_WIDTH / 2);
  }
}

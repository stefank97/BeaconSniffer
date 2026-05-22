#include "header.h"








void setup() {
  Serial.begin(115200);

  framebuffer = (uint8_t *)ps_calloc(sizeof(uint8_t), EPD_WIDTH * EPD_HEIGHT / 2);
  if (!framebuffer){
    Serial.println("PSRAM allocation failed.");
    while(1);
  }

  memset(framebuffer, 0xFF, EPD_WIDTH * EPD_HEIGHT / 2);

  epd_init();
    
  epd_clear();


  epd_poweron();


  //MOST IMPORTANT: SNIFFING
  // 'breathing', 32x32px
  const uint8_t epd_bitmap_breathing [] PROGMEM = {
    0xff, 0xef, 0xf7, 0xff, 0xff, 0xcf, 0xf3, 0xff, 0xff, 0xcf, 0xf3, 0xff, 0xff, 0xcf, 0xf3, 0xff, 
    0xff, 0xcf, 0xf3, 0xff, 0xff, 0xcf, 0xf3, 0xff, 0xff, 0xdf, 0xfb, 0xff, 0xff, 0x9f, 0xf9, 0xff, 
    0xff, 0x9f, 0xf9, 0xff, 0xff, 0x9f, 0xf9, 0xff, 0xff, 0x9f, 0xf9, 0xff, 0xff, 0x3f, 0xfc, 0xff, 
    0xfe, 0x7f, 0xfc, 0x7f, 0xfc, 0x7f, 0xfe, 0x3f, 0xf9, 0xff, 0xff, 0x9f, 0xf3, 0xff, 0xff, 0xcf, 
    0xf3, 0xff, 0xff, 0xcf, 0xf3, 0xff, 0xff, 0xcf, 0xf3, 0x8f, 0xf1, 0xcf, 0xf1, 0x87, 0xe1, 0x8f, 
    0xf8, 0x71, 0x8e, 0x1f, 0xfe, 0x78, 0x1e, 0x7f, 0xff, 0xfe, 0x7f, 0xff, 0xff, 0x9f, 0xf9, 0xff, 
    0xff, 0x9f, 0xf9, 0xff, 0xff, 0x93, 0xc9, 0xff, 0xff, 0x33, 0xcc, 0xff, 0xfc, 0x33, 0xcc, 0x3f, 
    0xf0, 0x73, 0xce, 0x0f, 0xfb, 0xe7, 0xe7, 0xdf, 0xff, 0x07, 0xe0, 0xff, 0xff, 0x1f, 0xf8, 0xff
  };

  // Array of all bitmaps for convenience. (Total bytes used to store images in PROGMEM = 144)
  const int epd_bitmap_allArray_LEN = 1;
  const uint8_t* epd_bitmap_allArray[1] = {
    epd_bitmap_breathing
  };


  // int cursor_x = BOARDER_X;
  // int cursor_y = BOARDER_Y;
  // writeln((GFXfont *)&FiraSans, ">>Starting BeaconSniffer", &cursor_x, &cursor_y, framebuffer);

  // draw_icon(epd_bitmap_breathing, cursor_x + 15, 15, framebuffer);

  printLine(">>Starting BeaconSniffer", BOARDER_Y, epd_bitmap_breathing);

  printLine(">>Sniffing for Networks...", BOARDER_Y * 2, epd_bitmap_breathing);
  epd_draw_grayscale_image(epd_full_screen(), framebuffer);
  //Debug
  Serial.println("Start BeaconSniffer");
  epd_poweroff();
}

void loop() {

}








//AI Function for Sniffing emoji
void draw_icon(const uint8_t *bitmap, int x, int y, uint8_t *fb) {
    for (int page_y = 0; page_y < 32; page_y++) {
        for (int page_x = 0; page_x < 32; page_x++) {
            int pixel_pos = page_y * 32 + page_x;
            if (!(bitmap[pixel_pos / 8] & (1 << (7 - (pixel_pos % 8))))) {
                epd_draw_pixel(x + page_x, y + page_y, 0, fb);
            }
        }
    }
}

void printLine(const char *text, int y, const uint8_t *icon) {
  int cursor_x = BOARDER_X;
  int cursor_y = y;

  writeln((GFXfont *)&FiraSans, text, &cursor_x, &cursor_y, framebuffer);

  if(icon != NULL) {
    draw_icon(icon, cursor_x + 10, y - 24, framebuffer);
  }
} 

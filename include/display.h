#ifndef DISPLAY_H
#define DISPLAY_H

#include <Arduino.h>


namespace Display {

    void init();
    void refresh();
    void printLine(int line, const char *text, const uint8_t *icon = nullptr);
}

#endif
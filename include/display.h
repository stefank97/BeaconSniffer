#ifndef DISPLAY_H
#define DISPLAY_H

#include <Arduino.h>


namespace Display {

    void init();
    void refresh();
    void clear();
    void refreshLine(int firstLine, int lineCount);
    void clearLine(int firstLine, int lineCount);
    void printLine(int line, const char *text, const uint8_t *icon = nullptr);
}

#endif

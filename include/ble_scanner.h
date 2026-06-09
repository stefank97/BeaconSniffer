#ifndef BLE_SCANNER_H
#define BLE_SCANNER_H

namespace BleScanner {
    void scanAndShowList();
    void nextSelection();
    void showList();
    bool returnSelected();
    void showDetails();
    void exitDetails();
    void loop();
}

#endif
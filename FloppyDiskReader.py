#!/bin/env python3
import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
import signal
import sys

from floppy import FloppyReader, codec
from PySide6.QtWidgets import *
from PySide6.QtGui import *
from PySide6.QtCore import *

floppy: FloppyReader = None

def main():
    global floppy
    signal.signal(signal.SIGINT, lambda signal, handler: QApplication.closeAllWindows)  # doesn't work.
    app = QApplication(sys.argv)
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=Path(sys.path[0], "FloppyDiskReader.conf"), type=Path, help="Configuration file")
    parser.add_argument("--debug", default=False, action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    try:
        if not args.config.exists():
            x = QMessageBox(QMessageBox.Icon.Critical, "Missing Config", f"The configuration file\n'{args.config.absolute()}'\n doesn't exist.")
            x.setModal(True)        
            x.show()
            app.exec()
            exit(1)

        try:
            floppy = FloppyReader(args.config)    
        except Exception as e:
            x = QMessageBox(QMessageBox.Icon.Critical, "Greaseweazle Error", f"Cannot connect to the greaseweazle:\n'{e}'")
            x.setModal(True)        
            x.show()
            app.exec()
            raise(e)
            
        window = MainWindow()
        window.show()
        return app.exec()

    except Exception as e:
        logging.exception(e)
        exit(2)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Floppy Disk Reader")
        layout = QGridLayout()
        
        # physical disk
        self.pdisk = QComboBox()
        for k, v in floppy.drives.items():
            self.pdisk.addItem(f"{k}: {v['type']}", k)
        self.pdisk.setCurrentIndex(0)
        layout.addWidget(QLabel("Physical Disk"), 0, 0)  
        layout.addWidget(self.pdisk, 0, 1, 1, -1)
        
        # disk format
        self.format = QComboBox()
        def refresh_formats():
            self.format.clear()
            for k, v in floppy.get_formats_for_drive(self.pdisk.currentData()).items():
                self.format.addItem(k, v)
        refresh_formats()
        self.pdisk.currentIndexChanged.connect(refresh_formats)
        layout.addWidget(QLabel(text="Disk Format"), 1, 0)
        layout.addWidget(self.format, 1, 1)
        
        probe = QPushButton("Probe")
        def do_probe():
            probewindow = ProbeWindow(self.pdisk.currentData())
            probewindow.show()
            probewindow.probe()
            probewindow.exec()
            res = probewindow.result()
            if res == QMessageBox.StandardButton.Ok:
                fmt = probewindow.format_name
                self.format.setCurrentIndex(self.format.findText(fmt))
        probe.pressed.connect(do_probe)
        layout.addWidget(probe, 1, 2)
        
        # tracks and parameters
        gbox = QGroupBox("Format Options")
        glayout = QGridLayout()
        self.tracks = QSpinBox(minimum=1, singleStep=1, value=40)
        self.heads = QSpinBox(minimum=1, singleStep=1, value=2)
        def refresh_tracks_and_heads():
            fmt: codec.DiskDef = self.format.currentData()
            if fmt:
                self.tracks.setMaximum(fmt.cyls)
                self.tracks.setValue(fmt.cyls)
                self.heads.setMaximum(fmt.heads)
                self.heads.setValue(fmt.heads)
        refresh_tracks_and_heads()
        self.format.currentIndexChanged.connect(refresh_tracks_and_heads)
        glayout.addWidget(QLabel("Tracks:"), 0, 0)
        glayout.addWidget(self.tracks, 0, 1)
        glayout.addWidget(QLabel("Heads:"), 0, 2)
        glayout.addWidget(self.heads, 0, 3)

        gbox.setLayout(glayout)
        layout.addWidget(gbox, 2, 0, 1, -1)

        read = QPushButton("Start")
        def do_read():
            probewindow = ProcessWindow(self.pdisk.currentData(), 
                                        self.format.currentText(), self.format.currentData(),
                                        self.tracks.value(), self.heads.value())
            probewindow.show()
            probewindow.read()
            probewindow.exec()
        read.pressed.connect(do_read)
        layout.addWidget(read, 3, 0)

        rpm = QPushButton("RPM")
        def check_rpm():
            dlg = QMessageBox(parent=self,
                              icon=QMessageBox.Icon.Information)
            dlg.setWindowTitle("Disk RPM")
            try:
                rpm = floppy.rpm(self.pdisk.currentData())
                nom_rpm = floppy.drives[self.pdisk.currentData()]['rpm']
                rate = 100 * (rpm / nom_rpm)
                dlg.setText(f"Drive Speed:\nMeasured {rpm:0.2f} RPM\nNominal {nom_rpm} RPM\nAccuracy {rate:0.2f}%")                
            except Exception as e:                
                dlg.setText(f"Error: {e}")
                dlg.setIcon(QMessageBox.Icon.Critical)
            dlg.setModal(True)
            dlg.show()

        rpm.pressed.connect(check_rpm)
        layout.addWidget(rpm, 3, 1)
        
        quit = QPushButton("Quit")
        quit.pressed.connect(QCoreApplication.quit)
        layout.addWidget(quit, 3, 2)
        self.setLayout(layout)


class ProbeWindow(QDialog):
    def __init__(self, drive: str):
        super().__init__()
        self.setWindowTitle("Probing Disk")
        self.setModal(True)
        self.drive = drive
        self.format_name = None
        self.result_value = None
        layout = QGridLayout()
        
        self.format = QComboBox()
        self.format.setFixedWidth(40 * 8)
        self.format.addItem("Probing...")
        layout.addWidget(self.format, 0, 0, 1, -1)
        
        self.ok = QPushButton("OK")    
        def ok_func():
            self.result_value = QMessageBox.StandardButton.Ok
            self.format_name = self.format.currentData()
            self.close()
        self.ok.pressed.connect(ok_func)
        layout.addWidget(self.ok, 1, 0)

        self.cancel = QPushButton("Cancel")
        def cancel_func():
            self.result_value = QMessageBox.StandardButton.Cancel
            self.close()
        self.cancel.pressed.connect(cancel_func)
        layout.addWidget(self.cancel, 1, 1)
        self.setLayout(layout)
        self.adjustSize()

    def probe(self):
        # turn off the buttons
        self.ok.setDisabled(True)
        self.cancel.setDisabled(True)
        self.format.setDisabled(True)
        QGuiApplication.processEvents()
        def callback(x):
            self.format.setItemText(0, f"{x['message']} ({100*x['progress']:0.2f}%)")
            QGuiApplication.processEvents()
        items = floppy.probe(self.drive, callback=callback)
        self.cancel.setDisabled(False)
        if not items:
            self.format.setItemText(0, "No Formats Found")
        else:
            self.format.clear()

            # sort these by largest percentage and then largest size.
            for t, d in  [(f"{x}: {items[x][0]:0.1f}% ({items[x][1]}h, {items[x][2]}t, {items[x][3]}s)", x) for x in sorted(items.keys(), key=lambda x: items[x], reverse=True)]:
                self.format.addItem(t, d)
            

            #self.format.addItems(items.keys())
            self.ok.setDisabled(False)
            self.format.setDisabled(False)
            

    def result(self):
        return self.result_value


class ProcessWindow(QDialog):
    def __init__(self, drive: str, format_name: str, format: codec.DiskDef, tracks: int, heads: int):
        super().__init__()
        self.setWindowTitle("Reading Disk")
        self.drive = drive
        self.format_name = format_name
        self.format = format
        self.tracks = tracks
        self.heads = heads
        logging.info(f"{drive}, {format_name}, {format}, {tracks}, {heads}")

        layout = QGridLayout()
        self.results = QTableWidget(rowCount=160,
                                    columnCount=5)
        self.results.setHorizontalHeaderLabels(['Head', 'Track', 'Message', 'Dat', 'Flux'])     
        self.results.setColumnWidth(0, 2)
        self.results.setColumnWidth(1, 2)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        layout.addWidget(self.results, 0, 0, 1, -1)

        """
        {'message': 'successfully read track',
                                    'head': head,
                                    'logical_cylinder': cyl,
                                    'physical_cylinder': pcyl,
                                    'flux': flux.summary_string(),
                                    'dat': dat.summary_string(),
                                    'progress': current / total})    
        """
        self.progress = QProgressBar(maximum=1)
        layout.addWidget(self.progress, 1, 0, 1, 3)

        close = QPushButton("Close")
        close.pressed.connect(self.close)
        layout.addWidget(close, 1, 3)

        self.setLayout(layout)
        self.adjustSize()

        self.setModal(True)

    def read(self):
        pass




if __name__ == "__main__":
    main()
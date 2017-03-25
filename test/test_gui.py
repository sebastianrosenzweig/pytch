import unittest
import sys
import time
import numpy as num

from PyQt5.QtWidgets import QApplication, QMainWindow, QHBoxLayout
from PyQt5 import QtGui as qg
from PyQt5 import QtCore as qc
from pytch import gui, plot



#class GUITestCase(unittest.TestCase):
class MainWindowQClose(QMainWindow):
    def __init__(self, *args, **kwargs):
        QMainWindow.__init__(self, *args, **kwargs)
        self.layout = QHBoxLayout()
        self.setLayout(self.layout)
        self.setMouseTracking(True)

    def keyPressEvent(self, key_event):
        ''' react on keyboard keys when they are pressed.'''
        if key_event.text() == 'q':
            self.close()
        QMainWindow.keyPressEvent(self, key_event)

    def paintEvent(self, e):
        painter = qg.QPainter(self)
        rect = self.rect()
        center = rect.center()
        gui.draw_label(painter, center, 20, 'A', 'red')

class GUITestCase():

    def test_scaling(self):
        app = QApplication(sys.argv)
        main_window = MainWindowQClose()

        plot_widget = gui.PlotWidget()
        plot_widget.plot(num.arange(199), num.arange(199))
        main_window.setCentralWidget(plot_widget)
        #plot_widget.set_xlim(0, 20)
        #plot_widget.set_ylim(-50, 150)

        main_window.show()
        main_window.repaint()
        sys.exit(app.exec_())

    def test_PitchWidget(self):
        app = QApplication(sys.argv)
        main_window = MainWindowQClose()
        plot_widget = gui.PlotWidget()
        #plot_widget.set_xlim(0, 18)
        #plot_widget.set_ylim(0, 1)
        n = 200


        #x1 = num.array([0,1,2,3,6,7,9,10,14,16])
        #x2 = num.array([0,1,3,4,5,6,8,11,16,17])
        #y1 = num.random.random(len(x1))*1000
        #y2 = num.random.random(len(x1))*1000

        x1 = num.linspace(0, 10., n)
        x2 = num.linspace(0, 10., n)
        y1 = num.random.random(len(x1))*100
        y2 = num.random.random(len(x1))*100


        #plot_widget.fill_between(x1, y1, x2, y2)
        plot_widget.colormap.set_vlim(0, 100)
        main_window.setCentralWidget(plot_widget)
        main_window.show()
        main_window.repaint()

        #main_window.close()
        sys.exit(app.exec_())

    def test_ColormapWidget(self):
        app = QApplication(sys.argv)
        main_window = MainWindowQClose()
        cmap = gui.InterpolatedColormap()
        plot_widget = gui.ColormapWidget(cmap)

        main_window.setCentralWidget(plot_widget)
        main_window.show()
        main_window.repaint()
        sys.exit(app.exec_())

    #def test_spectrogram(self):
    #    app = QApplication(sys.argv)
    #    main_window = MainWindowQClose()
    #    n = 30
    #    a = num.zeros((n, n, 3), dtype=num.uint32)
    #    #a = num.zeros((n, n, 3))
    #    for i in range(n):
    #        for j in range(n):
    #            a[j, i] = (0, 0, 1)
    #            #a[j, i] = (123, 123, 123)

    #    print(a)
    #    print('start')
    #    #spec = plot.Spectrogram.from_numpy_array(a)
    #    img = qg.QImage(n, n, qg.QImage.Format_RGB32)
    #    vptr = img.bits()
    #    vptr.setsize(int(n*n*3*8))
    #    imgarr = num.ndarray(shape=(n, n, 3), dtype=num.uint32, buffer=vptr)
    #    #imgarr = num.ndarray(shape=(30, 30, 3), dtype=num.uint32, buffer=memoryview(vptr))
    #    imgarr.setflags(write=True)
    #    imgarr = memoryview(a)
    #    print(imgarr)
    #    spec = plot.Spectrogram(img)
    #    print('stop')
    #    main_window.setCentralWidget(spec)
    #    main_window.show()
    #    main_window.repaint()
    #    img = None
    #    imgarr = None
    #    sys.exit(app.exec_())

    def test_spectrogram(self):
        app = QApplication(sys.argv)
        main_window = MainWindowQClose()
        n = 3000
        #a = num.zeros((n, n, 3), dtype=num.ubyte)
        #a = num.zeros((n, n, 3), dtype=num.uint32)
        #a = num.zeros((n, n), dtype=num.uint32)
        a = num.loadtxt('spectrogram_data.txt', dtype=num.float)
        #a = num.exp(a)
        #a += num.abs(num.min(a))
        #a = a/num.max(a)
        print(a)
        x = num.arange(n)
        y = num.arange(n)
        a = num.asarray(a, dtype=num.uint32)
        #a = num.zeros((n, n, 3))
        #for i in range(n):
        #    for j in range(n):
        #        a[j, i] = i*4+j*2
        print(a)
        print('start')
        a = num.ascontiguousarray(a)
        #a = num.require(a, num.uint8, 'C')
        plot_widget = gui.PlotWidget()
        plot_widget.setup_annotation_boxes()
        plot_widget.colormesh(x, y, a)
        #spec = plot.Spectrogram.from_numpy_array(a)
        #img = qg.QImage(n, n, qg.QImage.Format_RGB32)
        #vptr = img.bits()
        #vptr.setsize(int(n*n*3*8))
        #imgarr = num.ndarray(shape=(n, n, 3), dtype=num.uint32, buffer=memoryview(vptr))
        ##imgarr = num.ndarray(shape=(30, 30, 3), dtype=num.uint32, buffer=memoryview(vptr))
        #imgarr.setflags(write=True)
        ##imgarr[:, :, :] = a
        #imgarr = num.copy(a)
        #print(imgarr)
        #spec = plot.Spectrogram(img.copy())
        print('stop')
        main_window.setCentralWidget(plot_widget)
        main_window.show()
        main_window.repaint()
        img = None
        imgarr = None
        sys.exit(app.exec_())

    def test_asdfspectrogram(self):
        app = QApplication(sys.argv)
        main_window = MainWindowQClose()
        n = 100
        a = num.random.randint(0,256,size=(100,100,3)).astype(num.uint32)
        b = (255 << 24 | a[:,:,0] << 16 | a[:,:,1] << 8 | a[:,:,2]).flatten() # pack RGB values
        im = qg.QImage(b, 100, 100, qg.QImage.Format_RGB32)        
        
        spec = plot.Spectrogram.from_numpy_array(a)
        print('stop')
        main_window.setCentralWidget(spec)
        main_window.show()
        main_window.repaint()
        img = None
        imgarr = None
        sys.exit(app.exec_())

    def test_gauge(self):
        app = QApplication(sys.argv)
        main_window = MainWindowQClose()
        gauge = plot.GaugeWidget()
        gauge.set_ylim(-1000., 1000)
        gauge.set_data(-400.)
        main_window.setCentralWidget(gauge)

        main_window.show()
        main_window.repaint()
        sys.exit(app.exec_())

    def test_keyboard(self):
        from pytch.keyboard import KeyBoard
        app = QApplication(sys.argv)
        main_window = MainWindowQClose()

        kb = KeyBoard()
        main_window.setCentralWidget(kb)
        main_window.show()
        main_window.repaint()
        sys.exit(app.exec_())

    def test_graphicsview(self):
        from pytch.plot import Figure
        app = QApplication(sys.argv)
        main_window = MainWindowQClose()

        figure = Figure()
        figure.add_subplot()

        main_window.setCentralWidget(gauge)
        main_window.show()
        main_window.repaint()
        sys.exit(app.exec_())


if __name__=='__main__':
    #unittest.main()
    t = GUITestCase()
    #t.test_scaling()
    #t.test_PitchWidget()
    #t.test_ColormapWidget()
    #t.test_spectrogram()
    t.test_gauge()
    #t.test_graphicsview()
    #t.test_keyboard()


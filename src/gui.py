import logging
import sys
import numpy as num

from pytch.two_channel_tuner import Worker

from pytch.data import MicrophoneRecorder, getaudiodevices, sampling_rate_options, pitch_algorithms
from pytch.gui_util import AutoScaler, Projection, mean_decimation, FloatQLineEdit
from pytch.gui_util import make_QPolygonF, _color_names, _colors # noqa
from pytch.util import Profiler, smooth, consecutive, f2pitch, pitch2f
from pytch.plot import PlotWidget, GaugeWidget, MikadoWidget, AutoGrid, FixGrid

if False:
    from PyQt4 import QtCore as qc
    from PyQt4 import QtGui as qg
    from PyQt4.QtGui import QApplication, QWidget, QHBoxLayout, QLabel, QMenu
    from PyQt4.QtGui import QMainWindow, QVBoxLayout, QComboBox, QGridLayout
    from PyQt4.QtGui import QAction, QSlider, QPushButton, QDockWidget, QFrame
else:
    from PyQt5 import QtCore as qc
    from PyQt5 import QtGui as qg
    from PyQt5.QtWidgets import QApplication, QWidget, QHBoxLayout, QLabel
    from PyQt5.QtWidgets import QMainWindow, QVBoxLayout, QComboBox
    from PyQt5.QtWidgets import QAction, QSlider, QPushButton, QDockWidget
    from PyQt5.QtWidgets import QCheckBox, QSizePolicy, QFrame, QMenu
    from PyQt5.QtWidgets import QGridLayout, QSpacerItem, QDialog, QLineEdit
    from PyQt5.QtWidgets import QDialogButtonBox, QTabWidget, QActionGroup


logger = logging.getLogger(__name__)
tfollow = 3.
fmax = 2000.
_standard_frequency = 220.


class LineEditWithLabel(QWidget):
    def __init__(self, label, default=None, *args, **kwargs):
        QWidget.__init__(self, *args, **kwargs)
        layout = QHBoxLayout()
        layout.addWidget(QLabel(label))
        self.setLayout(layout)

        self.edit = QLineEdit()
        layout.addWidget(self.edit)

        if default:
            self.edit.setText(str(default))

    @property
    def value(self):
        return self.edit.text()


class DeviceMenuSetting:
    device_index = 0
    accept = True
    show_traces = True

    def set_menu(self, m):
        if isinstance(m, MenuWidget):
            m.box_show_traces.setChecked(self.show_traces)


class DeviceMenu(QDialog):
    ''' Pop up menu at program start devining basic settings'''

    def __init__(self, set_input_callback=None, *args, **kwargs):
        QDialog.__init__(self, *args, **kwargs)
        self.setModal(True)

        self.set_input_callback = set_input_callback

        layout = QVBoxLayout()
        self.setLayout(layout)

        layout.addWidget(QLabel('Select Input Device'))
        self.select_input = QComboBox()
        layout.addWidget(self.select_input)

        self.select_input.clear()
        devices = getaudiodevices()
        curr = len(devices)-1
        for idevice, device in enumerate(devices):
            self.select_input.addItem('%s: %s' % (idevice, device))
            if 'default' in device:
                curr = idevice

        self.select_input.setCurrentIndex(curr)

        self.edit_sampling_rate = LineEditWithLabel(
            'Sampling rate', default=44100)
        layout.addWidget(self.edit_sampling_rate)

        self.edit_nchannels = LineEditWithLabel(
            'Number of Channels', default=2)
        layout.addWidget(self.edit_nchannels)

        layout.addWidget(QLabel('NFFT'))
        self.nfft_choice = self.get_nfft_box()
        layout.addWidget(self.nfft_choice)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.on_ok_clicked)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def get_nfft_box(self):
        ''' Return a QSlider for modifying FFT width'''
        b = QComboBox()
        self.nfft_options = [f*1024 for f in [1, 2, 4, 8, 16]]

        for fft_factor in self.nfft_options:
            b.addItem('%s' % fft_factor)

        b.setCurrentIndex(3)
        return b

    def on_ok_clicked(self):
        fftsize = int(self.nfft_choice.currentText())
        recorder = MicrophoneRecorder(
                        chunksize=512,
                        device_no=self.select_input.currentIndex(),
                        sampling_rate=int(self.edit_sampling_rate.value),
                        fftsize=int(fftsize),
                        nchannels=int(self.edit_nchannels.value))
        self.set_input_callback(recorder)
        self.hide()

    @classmethod
    def from_device_menu_settings(cls, settings, parent, accept=False):
        '''
        :param setting: instance of :py:class:`DeviceMenuSetting`
        :param parent: parent of instance
        :param ok: accept setting
        '''
        menu = cls(parent=parent)

        if settings.device_index is not None:
            menu.select_input.setCurrentIndex(settings.device_index)

        if accept:
            qc.QTimer().singleShot(10, menu.on_ok_clicked)

        return menu


class MenuWidget(QFrame):
    ''' Contains all widget of left-side panel menu'''
    def __init__(self, settings=None, *args, **kwargs):
        QFrame.__init__(self, *args, **kwargs)
        layout = QGridLayout()
        self.setLayout(layout)

        self.input_button = QPushButton('Set Input')
        layout.addWidget(self.input_button, 0, 0)

        self.play_button = QPushButton('Play')
        layout.addWidget(self.play_button, 0, 1)

        self.pause_button = QPushButton('Pause')
        layout.addWidget(self.pause_button, 0, 2)

        layout.addWidget(QLabel('Noise Threshold'), 4, 0)
        self.noise_thresh_slider = QSlider()
        self.noise_thresh_slider.setRange(0, 2000)
        self.noise_thresh_slider.setValue(500)
        self.noise_thresh_slider.setOrientation(qc.Qt.Horizontal)
        layout.addWidget(self.noise_thresh_slider, 4, 1)

        layout.addWidget(QLabel('Gain'), 5, 0)
        self.sensitivity_slider = QSlider()
        self.sensitivity_slider.setRange(1000., 500000.)
        self.sensitivity_slider.setValue(100000.)
        self.sensitivity_slider.setOrientation(qc.Qt.Horizontal)
        layout.addWidget(self.sensitivity_slider, 5, 1)

        layout.addWidget(QLabel('Select Algorithm'), 6, 0)
        self.select_algorithm = QComboBox(self)
        layout.addWidget(self.select_algorithm, 6, 1)

        layout.addWidget(QLabel('Show traces'), 7, 0)
        self.box_show_traces = QCheckBox()
        layout.addWidget(self.box_show_traces, 7, 1)

        self.freq_box = FloatQLineEdit(self)
        layout.addWidget(QLabel('Standard Frequency'), 8, 0)
        layout.addWidget(self.freq_box, 8, 1)

        layout.addItem(QSpacerItem(40, 20), 9, 1, qc.Qt.AlignTop)

        self.setFrameStyle(QFrame.Sunken)
        self.setLineWidth(1)
        self.setFrameShape(QFrame.Box)
        self.setMinimumWidth(300)
        self.setSizePolicy(QSizePolicy.Maximum,
                           QSizePolicy.Maximum)
        self.setup_palette()
        settings.set_menu(self)

    def setup_palette(self):
        pal = self.palette()
        pal.setColor(qg.QPalette.Background, qg.QColor(*_colors['aluminium3']))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

    def set_algorithms(self, algorithms, default=None):
        ''' Query device list and set the drop down menu'''
        for alg in algorithms:
            self.select_algorithm.addItem('%s' % alg)

        if default:
            self.select_algorithm.setCurrentIndex(algorithms.index(default))

    def connect_to_noise_threshold(self, widget):
        self.noise_thresh_slider.valueChanged.connect(
            widget.on_noise_threshold_changed)

    def connect_channel_views(self, channel_views):
        self.box_show_traces.stateChanged.connect(
            channel_views.show_trace_widgets)
        channel_views.show_trace_widgets(self.box_show_traces.isChecked())
        self.sensitivity_slider.valueChanged.connect(
            channel_views.set_in_range)

        self.freq_box.accepted_value.connect(
            channel_views.on_standard_frequency_changed)

        self.freq_box.setText(str(channel_views.standard_frequency))
        channel_views.set_in_range(self.sensitivity_slider.value())

    def sizeHint(self):
        return qc.QSize(200, 200)


class ChannelViews(QWidget):
    '''
    Display all ChannelView objects in a QVBoxLayout
    '''
    def __init__(self, channel_views):
        QWidget.__init__(self)
        self.channel_views = channel_views
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.standard_frequency = _standard_frequency

        for c_view in self.channel_views:
            self.layout.addWidget(c_view)

        self.show_trace_widgets(False)

    def show_trace_widgets(self, show):
        for c_view in self.channel_views:
            c_view.show_trace_widget(show)

    def add_channel_view(self, channel_view):
        '''
        :param channel_view: ChannelView widget instance
        '''
        self.layout.addWidget(channel_view)

    def set_in_range(self, val_range):
        for c_view in self.channel_views:
            c_view.trace_widget.set_ylim(-val_range, val_range)

    @qc.pyqtSlot(float)
    def on_standard_frequency_changed(self, f):
        for cv in self.channel_views:
            cv.on_standard_frequency_changed(f)

class ChannelView(QWidget):
    def __init__(self, channel, color='red', *args, **kwargs):
        '''
        Visual representation of a Channel instance.

        :param channel: pytch.data.Channel instance
        '''
        QWidget.__init__(self, *args, **kwargs)
        self.channel = channel

        self.color = color
        self.setMouseTracking(True)

        layout = QHBoxLayout()
        self.setLayout(layout)

        self.noise_threshold = 0

        self.trace_widget = PlotWidget()
        self.trace_widget.grids = [AutoGrid(vertical=False)]
        self.trace_widget.set_ylim(-1000., 1000.)

        self.spectrum = PlotWidget()
        self.spectrum.set_xlim(0, 2000)
        self.spectrum.set_ylim(0, 20)
        self.spectrum.grids = [AutoGrid(horizontal=False)]
        self.plot_spectrum = self.spectrum.plotlog

        self.fft_smooth_factor = 4
        self.standard_frequency = _standard_frequency

        layout.addWidget(self.trace_widget)
        layout.addWidget(self.spectrum)

        self.right_click_menu = QMenu('RC', self)
        self.channel_color_menu = QMenu('Channel Color', self.right_click_menu)

        self.color_choices = []
        color_action_group = QActionGroup(self.channel_color_menu)
        color_action_group.setExclusive(True)
        for color_name in _color_names:
            color_action = QAction(color_name, self.channel_color_menu)
            color_action.triggered.connect(self.on_color_select)
            color_action.setCheckable(True)
            self.color_choices.append(color_action)
            color_action_group.addAction(color_action)
            self.channel_color_menu.addAction(color_action)
        self.right_click_menu.addMenu(self.channel_color_menu)

        self.fft_smooth_factor_menu = QMenu(
            'FFT smooth factor', self.right_click_menu)
        smooth_action_group = QActionGroup(self.fft_smooth_factor_menu)
        smooth_action_group.setExclusive(True)
        self.smooth_choices = []
        for factor in range(5):
            factor += 1
            fft_smooth_action = QAction(str(factor), self.fft_smooth_factor_menu)
            fft_smooth_action.triggered.connect(self.on_fft_smooth_select)
            fft_smooth_action.setCheckable(True)
            if factor == self.fft_smooth_factor:
                fft_smooth_action.setChecked(True)
            self.smooth_choices.append(fft_smooth_action)
            smooth_action_group.addAction(fft_smooth_action)
            self.fft_smooth_factor_menu.addAction(fft_smooth_action)
        self.right_click_menu.addMenu(self.fft_smooth_factor_menu)

        self.spectrum_type_menu = QMenu(
            'lin/log', self.right_click_menu)
        plot_action_group = QActionGroup(self.spectrum_type_menu)
        plot_action_group.setExclusive(True)
        self.spectrum_type_choices = []

        for stype in ['log', 'linear']:
            spectrum_type = QAction(stype, self.spectrum_type_menu)
            spectrum_type.triggered.connect(self.on_spectrum_type_select)
            spectrum_type.setCheckable(True)
            self.spectrum_type_choices.append(spectrum_type)
            smooth_action_group.addAction(spectrum_type)
            self.spectrum_type_menu.addAction(spectrum_type)
            if stype == 'log':
                spectrum_type.setChecked(True)

        self.right_click_menu.addMenu(self.spectrum_type_menu)
        self.on_spectrum_type_select()

    @qc.pyqtSlot()
    def on_clear(self):
        self.trace_widget.clear()
        self.spectrum.clear()

    @qc.pyqtSlot()
    def on_draw(self):
        self.draw()

    @qc.pyqtSlot(int)
    def on_noise_threshold_changed(self, threshold):
        '''
        self.channel_views_widget.
        '''
        self.noise_threshold = threshold

    @qc.pyqtSlot(float)
    def on_standard_frequency_changed(self, f=1):
        self.standard_frequency = f

    def draw(self):
        c = self.channel
        self.trace_widget.plot(*c.latest_frame(
            tfollow), ndecimate=25, color=self.color, line_width=1)
        d = c.fft.latest_frame_data(self.fft_smooth_factor)

        if d is not None:
            self.plot_spectrum(
                    c.freqs, num.mean(d, axis=0), ndecimate=2,
                    #f2pitch(c.freqs, self.standard_frequency), num.mean(d, axis=0), ndecimate=2,
                    color=self.color, ignore_nan=True)

        power = num.sum(c.fft_power.latest_frame_data(1))

        if power > self.noise_threshold:
            x = c.get_latest_pitch(self.standard_frequency)
            self.spectrum.axvline(pitch2f(x, _standard_frequency))
        self.trace_widget.update()
        self.spectrum.update()

    def show_trace_widget(self, show=True):
        self.trace_widget.setVisible(show)

    def mousePressEvent(self, mouse_ev):
        point = self.mapFromGlobal(mouse_ev.globalPos())

        if mouse_ev.button() == qc.Qt.RightButton:
            self.right_click_menu.exec_(qg.QCursor.pos())
        else:
            QWidget.mousePressEvent(mouse_ev)

    def on_spectrum_type_select(self):
        for c in self.spectrum_type_choices:
            if c.isChecked():
                if c.text() == 'log':
                    self.plot_spectrum = self.spectrum.plotlog
                    self.spectrum.set_ylim(0, 20)
                elif c.text() == 'linear':
                    self.plot_spectrum = self.spectrum.plot
                    self.spectrum.set_ylim(0, num.exp(15))
                break

    def on_fft_smooth_select(self):
        for c in self.smooth_choices:
            if c.isChecked():
                self.fft_smooth_factor = int(c.text())
                break

    def on_color_select(self, asdf=None):
        for c in self.color_choices:
            if c.isChecked():
                self.color = c.text()
                break


class PitchWidget(QWidget):
    ''' Pitches of each trace as discrete samples.'''

    def __init__(self, channel_views, *args, **kwargs):
        QWidget.__init__(self, *args, **kwargs)
        self.channel_views = channel_views
        layout = QGridLayout()
        self.setLayout(layout)
        self.figure = PlotWidget()
        self.figure.set_ylim(-1500., 1500)
        self.figure.tfollow = 10.
        self.figure.grids = [FixGrid(delta=100.)]
        layout.addWidget(self.figure)

    @qc.pyqtSlot()
    def on_draw(self):
        for cv in self.channel_views:
            x, y = cv.channel.pitch.latest_frame(
                self.figure.tfollow, clip_min=True)
            index = num.where(cv.channel.fft_power.latest_frame_data(
                len(x))>=cv.noise_threshold)
            #y = pitch2f(y, cv.standard_frequency)
            self.figure.plot(x[index], y[index], style='o', line_width=4, color=cv.color)
        self.figure.update()
        self.repaint()

    @qc.pyqtSlot()
    def on_clear(self):
        self.figure.clear()


class DifferentialPitchWidget(QWidget):
    ''' Diffs as line'''
    def __init__(self, channel_views, *args, **kwargs):
        QWidget.__init__(self, *args, **kwargs)
        self.channel_views = channel_views
        layout = QGridLayout()
        self.setLayout(layout)
        self.figure = PlotWidget()
        self.figure.set_ylim(-1500., 1500)
        self.figure.tfollow = 10
        self.figure.grids = [FixGrid(delta=100.)]
        layout.addWidget(self.figure)

    @qc.pyqtSlot()
    def on_draw(self):
        for i1, cv1 in enumerate(self.channel_views):
            x1, y1 = cv1.channel.pitch.latest_frame(
                self.figure.tfollow, clip_min=True)
            index1 = num.where(cv1.channel.fft_power.latest_frame_data(
                len(x1))>=cv1.noise_threshold)

            for i2, cv2 in enumerate(self.channel_views):
                if i1>=i2:
                    continue
                x2, y2 = cv2.channel.pitch.latest_frame(
                    self.figure.tfollow, clip_min=True)
                index2 = num.where(cv2.channel.fft_power.latest_frame_data(
                    len(x2))>=cv2.noise_threshold)
                indices = num.intersect1d(index1, index2)
                indices_grouped = consecutive(indices)
                for group in indices_grouped:
                    y = y1[group] - y2[group]
                    x = x1[group]
                    self.figure.plot(
                        x, y, style='solid', line_width=4, color=cv1.color)
                    self.figure.plot(
                        x, y, style=':', line_width=4, color=cv2.color)

        self.figure.update()
        self.repaint()

    @qc.pyqtSlot()
    def on_clear(self):
        self.figure.clear()


class PitchLevelDifferenceViews(QWidget):
    ''' The Gauge widget collection'''
    def __init__(self, channel_views, *args, **kwargs):
        QWidget.__init__(self, *args, **kwargs)
        self.channel_views = channel_views
        layout = QGridLayout()
        self.setLayout(layout)
        self.widgets = []

        for i1, cv1 in enumerate(self.channel_views):
            for i2, cv2 in enumerate(self.channel_views):
                if i1>=i2:
                    continue
                w = GaugeWidget(parent=self)
                w.set_title('Channels: %s %s' % (i1, i2))
                self.widgets.append((cv1, cv2, w))
                layout.addWidget(w, i1, i2)

    @qc.pyqtSlot()
    def on_draw(self):
        naverage = 3
        for cv1, cv2, w in self.widgets:
            power1 = num.sum(cv1.channel.fft_power.latest_frame_data(naverage))
            power2 = num.sum(cv1.channel.fft_power.latest_frame_data(naverage))
            if power1 > cv1.noise_threshold and power2>cv2.noise_threshold:
                d1 = cv1.channel.pitch.latest_frame_data(naverage)
                d2 = cv2.channel.pitch.latest_frame_data(naverage)
                w.set_data(num.mean(d1)-num.mean(d2))
            else:
                w.set_data(None)
            w.repaint()


class PitchLevelMikadoViews(QWidget):
    def __init__(self, channel_views, *args, **kwargs):
        QWidget.__init__(self, *args, **kwargs)
        self.channel_views = channel_views
        layout = QGridLayout()
        self.setLayout(layout)
        self.widgets = []

        for i1, cv1 in enumerate(self.channel_views):
            for i2, cv2 in enumerate(self.channel_views):
                if i1>=i2:
                    continue
                w = MikadoWidget()
                w.set_ylim(-1500, 1500)
                w.set_title('Channels: %s %s' % (i1, i2))
                w.tfollow = 60.
                self.widgets.append((cv1, cv2, w))
                layout.addWidget(w, i1, i2)

    @qc.pyqtSlot()
    def on_draw(self):
        for cv1, cv2, w in self.widgets:
            x1, y1 = cv1.channel.pitch.latest_frame(w.tfollow)
            x2, y2 = cv2.channel.pitch.latest_frame(w.tfollow)
            w.fill_between(x1, y1, x2, y2)
            w.repaint()


class MainWidget(QWidget):
    ''' top level widget covering the central widget in the MainWindow.'''
    signal_widgets_clear = qc.pyqtSignal()
    signal_widgets_draw = qc.pyqtSignal()

    def __init__(self, settings, *args, **kwargs):
        QWidget.__init__(self, *args, **kwargs)

        self.setMouseTracking(True)
        self.top_layout = QHBoxLayout()
        self.setLayout(self.top_layout)

        self.refresh_timer = qc.QTimer()
        self.refresh_timer.timeout.connect(self.refresh_widgets)
        self.menu = MenuWidget(settings)

        self.input_dialog = DeviceMenu.from_device_menu_settings(
            settings, accept=settings.accept, parent=self)

        self.input_dialog.set_input_callback = self.set_input

        self.data_input = None

        qc.QTimer().singleShot(0, self.set_input_dialog)

    def make_connections(self):
        menu = self.menu
        menu.input_button.clicked.connect(self.set_input_dialog)
        menu.pause_button.clicked.connect(self.data_input.stop)
        menu.play_button.clicked.connect(self.data_input.start)

        menu.set_algorithms(pitch_algorithms, default='yin')
        menu.select_algorithm.currentTextChanged.connect(
            self.on_algorithm_select)

    @qc.pyqtSlot(str)
    def on_algorithm_select(self, arg):
        for c in self.data_input.channels:
            c.pitch_algorithm = arg

    def cleanup(self):
        ''' clear all widgets. '''
        if self.data_input:
            self.data_input.stop()
            self.data_input.terminate()

        while self.top_layout.count():
            item = self.top_layout.takeAt(0)
            item.widget().deleteLater()

    def set_input_dialog(self):
        ''' Query device list and set the drop down menu'''
        self.refresh_timer.stop()
        self.input_dialog.show()
        self.input_dialog.raise_()
        self.input_dialog.activateWindow()

    def reset(self):
        dinput = self.data_input

        self.worker = Worker(dinput.channels)

        channel_views = []
        for ichannel, channel in enumerate(dinput.channels):
            cv = ChannelView(channel, color=_color_names[3+3*ichannel])
            self.signal_widgets_clear.connect(cv.on_clear)
            self.signal_widgets_draw.connect(cv.on_draw)
            self.menu.connect_to_noise_threshold(cv)
            channel_views.append(cv)

        self.channel_views_widget = ChannelViews(channel_views)
        self.top_layout.addWidget(self.channel_views_widget)

        tabbed_pitch_widget = QTabWidget()
        tabbed_pitch_widget.setSizePolicy(QSizePolicy.Minimum,
                                          QSizePolicy.Minimum)

        self.top_layout.addWidget(tabbed_pitch_widget)

        self.pitch_view = PitchWidget(channel_views)

        self.pitch_view_all_diff = DifferentialPitchWidget(channel_views)
        self.pitch_diff_view = PitchLevelDifferenceViews(channel_views)
        #self.pitch_diff_view_colorized = PitchLevelMikadoViews(channel_views)

        tabbed_pitch_widget.addTab(self.pitch_view, 'Pitches')
        tabbed_pitch_widget.addTab(self.pitch_view_all_diff, 'Differential')
        tabbed_pitch_widget.addTab(self.pitch_diff_view, 'Current')
        #tabbed_pitch_widget.addTab(self.pitch_diff_view_colorized, 'Mikado')

        self.menu.connect_channel_views(self.channel_views_widget)

        self.signal_widgets_clear.connect(self.pitch_view.on_clear)
        self.signal_widgets_clear.connect(self.pitch_view_all_diff.on_clear)

        self.signal_widgets_draw.connect(self.pitch_view.on_draw)
        self.signal_widgets_draw.connect(self.pitch_view_all_diff.on_draw)
        self.signal_widgets_draw.connect(self.pitch_diff_view.on_draw)
        #self.signal_widgets_draw.connect(self.pitch_diff_view_colorized.on_draw)

        t_wait_buffer = max(dinput.fftsizes)/dinput.sampling_rate*1500.
        qc.QTimer().singleShot(t_wait_buffer, self.start_refresh_timer)

    def start_refresh_timer(self):
        self.refresh_timer.start(58)

    def set_input(self, input):
        self.cleanup()

        self.data_input = input
        self.data_input.start_new_stream()
        self.make_connections()

        self.reset()

    @qc.pyqtSlot()
    def refresh_widgets(self):
        self.data_input.flush()
        self.worker.process()
        self.signal_widgets_clear.emit()
        self.signal_widgets_draw.emit()

    def closeEvent(self, ev):
        '''Called when application is closed.'''
        logger.info('closing')
        self.data_input.terminate()
        self.cleanup()
        QWidget.closeEvent(self, ev)


class MainWindow(QMainWindow):
    ''' Top level Window. The entry point of the gui.'''
    def __init__(self, settings, *args, **kwargs):
        QMainWindow.__init__(self, *args, **kwargs)
        self.main_widget = MainWidget(settings)
        self.setCentralWidget(self.main_widget)

        controls_dock_widget = QDockWidget()
        controls_dock_widget.setWidget(self.main_widget.menu)
        self.addDockWidget(qc.Qt.LeftDockWidgetArea, controls_dock_widget)

        self.show()

    def keyPressEvent(self, key_event):
        ''' react on keyboard keys when they are pressed.'''
        key_text = key_event.text()
        if key_text == 'q':
            self.close()

        elif key_text == 'f':
            self.showMaximized()

        QMainWindow.keyPressEvent(self, key_event)

    def sizeHint(self):
        return qc.QSize(700, 600)


def from_command_line(close_after=None, settings=None, check_opengl=False,
                      disable_opengl=False):
    ''' Start the GUI from command line'''
    if check_opengl:
        try:
            from PyQt5.QtWidgets import QOpenGLWidget
        except ImportError as e:
            logger.warning(str(e) + ' - opengl not supported')
        else:
            logger.info('opengl supported')
        finally:
            sys.exit()

    app = QApplication(sys.argv)

    if settings is None:
        settings = DeviceMenuSetting()
        settings.accept = False
    else:
        # for debugging!
        # settings file to be loaded in future
        settings = DeviceMenuSetting()
        settings.accept = True

    window = MainWindow(settings=settings)

    if close_after:
        close_timer = qc.QTimer()
        close_timer.timeout.connect(app.quit)
        close_timer.start(close_after * 1000.)

    app.exec_()


if __name__ == '__main__':
    from_command_line()

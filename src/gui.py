import logging
import sys
import numpy as num
import os

from pytch.two_channel_tuner import Worker

from pytch.data import MicrophoneRecorder, getaudiodevices, pitch_algorithms
from pytch.gui_util import FloatQLineEdit
from pytch.gui_util import make_QPolygonF, _color_names, _colors # noqa
from pytch.util import consecutive, f2cent, cent2f, index_gradient_filter
from pytch.plot import GLAxis, Axis, GaugeWidget, MikadoWidget, FixGrid
from pytch.keyboard import KeyBoard

from PyQt5 import QtCore as qc
from PyQt5 import QtGui as qg
from PyQt5.QtWidgets import QApplication, QWidget, QHBoxLayout, QLabel
from PyQt5.QtWidgets import QMainWindow, QVBoxLayout, QComboBox
from PyQt5.QtWidgets import QAction, QSlider, QPushButton, QDockWidget
from PyQt5.QtWidgets import QCheckBox, QSizePolicy, QFrame, QMenu, QWidgetAction
from PyQt5.QtWidgets import QGridLayout, QSpacerItem, QDialog, QLineEdit
from PyQt5.QtWidgets import QDialogButtonBox, QTabWidget, QActionGroup, QFileDialog


logger = logging.getLogger(__name__)
tfollow = 3.
fmax = 2000.
_standard_frequency = 220.


def draw_label(painter, center, radius, text, color):
    ''' draw white circle with colored frame and colored label'''
    painter.save()
    painter.setBrush(qc.Qt.white)
    pen = painter.pen()
    pen.setColor(qg.QColor(*_colors[color]))
    pen.setWidth(3)
    painter.setRenderHint(qg.QPainter.Antialiasing)
    painter.setPen(pen)
    painter.drawEllipse(center, radius, radius)
    painter.drawText(center, text)
    painter.restore()


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

    spectrum_type_selected = qc.pyqtSignal(str)

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
        layout.addWidget(self.pause_button, 1, 0)

        self.save_as_button = QPushButton('Save as')
        layout.addWidget(self.save_as_button, 1, 1)

        layout.addWidget(QLabel('Confidence Threshold'), 4, 0)
        self.noise_thresh_slider = QSlider()
        self.noise_thresh_slider.setRange(0, 15)
        self.noise_thresh_slider.setTickPosition(QSlider.TicksBelow)
        self.noise_thresh_slider.setOrientation(qc.Qt.Horizontal)
        self.noise_thresh_slider.valueChanged.connect(
            lambda x: self.noise_thresh_label.setText(str(x/10.))
        )
        layout.addWidget(self.noise_thresh_slider, 4, 1)

        self.noise_thresh_label = QLabel('')
        layout.addWidget(self.noise_thresh_label, 4, 2)

        layout.addWidget(QLabel('Derivative Filter'), 5, 0)
        self.derivative_filter_slider = QSlider()
        self.derivative_filter_slider.setRange(0., 10000.)
        self.derivative_filter_slider.setValue(1000.)
        self.derivative_filter_slider.setOrientation(qc.Qt.Horizontal)
        layout.addWidget(self.derivative_filter_slider, 5, 1)
        derivative_filter_label = QLabel('')
        layout.addWidget(derivative_filter_label, 5, 2)
        self.derivative_filter_slider.valueChanged.connect(
            lambda x: derivative_filter_label.setText(str(x))
        )

        layout.addWidget(QLabel('Gain'), 6, 0)
        self.sensitivity_slider = QSlider()
        self.sensitivity_slider.setRange(1000., 500000.)
        self.sensitivity_slider.setValue(100000.)
        self.sensitivity_slider.setOrientation(qc.Qt.Horizontal)
        layout.addWidget(self.sensitivity_slider, 6, 1)

        layout.addWidget(QLabel('Select Algorithm'), 7, 0)
        self.select_algorithm = QComboBox(self)
        layout.addWidget(self.select_algorithm, 7, 1)

        layout.addWidget(QLabel('Traces'), 8, 0)
        self.box_show_traces = QCheckBox()
        layout.addWidget(self.box_show_traces, 8, 1)

        layout.addWidget(QLabel('Spectrogram'), 9, 0)
        self.box_show_spectrograms = QCheckBox()
        layout.addWidget(self.box_show_spectrograms, 9, 1)

        self.freq_box = FloatQLineEdit(parent=self, default=220)
        layout.addWidget(QLabel('Standard Frequency [Hz]'), 10, 0)
        layout.addWidget(self.freq_box, 10, 1)

        self.pitch_shift_box = FloatQLineEdit(parent=self, default='0.')
        layout.addWidget(QLabel('Pitch Shift [Cent]'), 11, 0)
        layout.addWidget(self.pitch_shift_box, 11, 1)

        layout.addWidget(QLabel('Spectral type'), 12, 0)
        select_spectral_type = QComboBox(self)
        layout.addWidget(select_spectral_type, 12, 1)

        for stype in ['log', 'linear', 'pitch']:
            select_spectral_type.addItem(stype)
        select_spectral_type.currentTextChanged.connect(
            self.on_spectrum_type_select)

        layout.addItem(QSpacerItem(40, 20), 12, 1, qc.Qt.AlignTop)

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
        pal.setColor(qg.QPalette.Background, qg.QColor(*_colors['aluminium1']))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

    def set_algorithms(self, algorithms, default=None):
        ''' Query device list and set the drop down menu'''
        self.select_algorithm.clear()
        for alg in algorithms:
            self.select_algorithm.addItem('%s' % alg)

        if default:
            self.select_algorithm.setCurrentIndex(algorithms.index(default))

    @qc.pyqtSlot(str)
    def on_spectrum_type_select(self, arg):
        self.spectrum_type_selected.emit(arg)

    def connect_to_confidence_threshold(self, widget):
        self.noise_thresh_slider.valueChanged.connect(
            widget.on_confidence_threshold_changed)
        self.noise_thresh_slider.setValue(widget.confidence_threshold*10)

    def connect_channel_views(self, channel_views):
        self.box_show_traces.stateChanged.connect(
            channel_views.show_trace_widgets)
        channel_views.show_trace_widgets(
            self.box_show_traces.isChecked())

        self.box_show_spectrograms.stateChanged.connect(
            channel_views.show_spectrogram_widgets)
        self.sensitivity_slider.valueChanged.connect(
            channel_views.set_in_range)

        self.freq_box.accepted_value.connect(
            channel_views.on_standard_frequency_changed)

        self.pitch_shift_box.accepted_value.connect(
            channel_views.on_pitch_shift_changed)

        #self.freq_box.setText(str(channel_views.standard_frequency))

        for cv in channel_views.channel_views:
            self.spectrum_type_selected.connect(cv.on_spectrum_type_select)
        channel_views.set_in_range(self.sensitivity_slider.value())

    def sizeHint(self):
        return qc.QSize(200, 200)


class ChannelViews(Axis):
    '''
    Display all ChannelView objects in a QVBoxLayout
    '''
    def __init__(self, channel_views):
        Axis.__init__(self)
        self.channel_views = channel_views
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        for c_view in self.channel_views:
            self.layout.addWidget(c_view)

        self.show_trace_widgets(False)
        self.show_spectrogram_widgets(False)

    def show_trace_widgets(self, show):
        for c_view in self.channel_views:
            c_view.show_trace_widget(show)

    def show_spectrogram_widgets(self, show):
        '''
        :param show: bool to show or hide widgets
        '''
        for c_view in self.channel_views:
            c_view.show_spectrogram_widget(show)

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

    @qc.pyqtSlot(float)
    def on_pitch_shift_changed(self, f):
        for cv in self.channel_views:
            cv.on_pitch_shift_changed(f)


class SpectrogramWidget(Axis):
    def __init__(self, channel, *args, **kwargs):
        super(SpectrogramWidget, self).__init__(*args, **kwargs)

        self.ny, self.nx = 300, 680
        x = num.arange(self.nx)
        y = num.arange(self.ny)
        self.channel = channel
        fake = num.ones((self.nx, self.ny))
        self.image = self.colormesh(x, y, z=fake)

    @qc.pyqtSlot()
    def update_spectrogram(self):
        c = self.channel
        try:
            x = c.freqs[: self.ny]
            y = c.xdata[-self.nx:]
            d = c.fft.latest_frame_data(self.nx)
            self.image.set_data(x, y, d[:, :self.ny])
            self.image.set_xlim(min(x), max(x))
            self.image.set_ylim(min(y), max(y))
            self.image.update()
            self.update()
        except ValueError as e:
            logger.debug(e)
            return

class SpectrumWidget(Axis):
    def __init__(self, *args, **kwargs):
        Axis.__init__(self, *args, **kwargs)
        self.set_xlim(0, 2000)
        self.set_ylim(0, 20)
        self.left = 0.
        self.yticks = False
        self.grids = [FixGrid(delta=100., horizontal=False)]

        # TODO: migrate functionanlity from ChannelView


class ChannelView(QWidget):
    def __init__(self, channel, color='red', *args, **kwargs):
        '''
        Visual representation of a Channel instance.

        :param channel: pytch.data.Channel instance
        '''
        QWidget.__init__(self, *args, **kwargs)
        self.channel = channel
        self.setContentsMargins(-10, -10, -10, -10)

        self.color = color

        layout = QHBoxLayout()
        self.setLayout(layout)

        self.confidence_threshold = 0.9
        self.freq_keyboard = 0

        self.trace_widget = GLAxis()
        self.trace_widget.grids = []
        self.trace_widget.yticks = False
        self.trace_widget.set_ylim(-1000., 1000.)
        self.trace_widget.left = 0.

        self.spectrogram_widget = SpectrogramWidget(channel=channel)

        self.spectrum = SpectrumWidget(parent=self)

        self.plot_spectrum = self.spectrum.plotlog

        self.fft_smooth_factor = 4

        layout.addWidget(self.trace_widget)
        layout.addWidget(self.spectrum)
        layout.addWidget(self.spectrogram_widget)

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

        self.spectrogram_refresh_timer = qc.QTimer()
        self.spectrogram_refresh_timer.timeout.connect(
            self.spectrogram_widget.update_spectrogram)
        self.spectrogram_refresh_timer.start(100)

    @qc.pyqtSlot(float)
    def on_keyboard_key_pressed(self, f):
        self.freq_keyboard = f

    @qc.pyqtSlot()
    def on_clear(self):
        self.trace_widget.clear()
        self.spectrum.clear()

    @qc.pyqtSlot()
    def on_draw(self):
        c = self.channel
        self.trace_widget.plot(*c.latest_frame(
            tfollow), ndecimate=25, color=self.color, line_width=1)
        d = c.fft.latest_frame_data(self.fft_smooth_factor)
        self.plot_spectrum(
                c.freqs, num.mean(d, axis=0), ndecimate=2,
                color=self.color, ignore_nan=True)
        confidence = c.pitch_confidence.latest_frame_data(1)
        if confidence > self.confidence_threshold:
            x = c.undo_pitch_proxy(c.get_latest_pitch())
            self.spectrum.axvline(x)

        if self.freq_keyboard:
            self.spectrum.axvline(
                self.freq_keyboard, color='aluminium4', style='dashed',
                line_width=4)
        self.trace_widget.update()
        self.spectrum.update()

    @qc.pyqtSlot(int)
    def on_confidence_threshold_changed(self, threshold):
        '''
        self.channel_views_widget.
        '''
        self.confidence_threshold = threshold/10.

    @qc.pyqtSlot(float)
    def on_standard_frequency_changed(self, f):
        self.channel.standard_frequency = f

    @qc.pyqtSlot(float)
    def on_pitch_shift_changed(self, shift):
        self.channel.pitch_shift = shift

    def show_trace_widget(self, show=True):
        self.trace_widget.setVisible(show)

    def show_spectrogram_widget(self, show=True):
        self.spectrogram_widget.setVisible(show)

    @qc.pyqtSlot(qg.QMouseEvent)
    def mousePressEvent(self, mouse_ev):
        if mouse_ev.button() == qc.Qt.RightButton:
            self.right_click_menu.exec_(qg.QCursor.pos())

    @qc.pyqtSlot(str)
    def on_spectrum_type_select(self, arg):
        '''
        Slot to update the spectrum type
        '''
        if arg == 'log':
            self.plot_spectrum = self.spectrum.plotlog
            self.spectrum.set_ylim(0, 20)
            self.spectrum.set_xlim(0, 2000)
        elif arg == 'linear':
            self.plot_spectrum = self.spectrum.plot
            self.spectrum.set_ylim(0, num.exp(15))
            self.spectrum.set_xlim(0, 2000)
        elif arg == 'pitch':
            def plot_pitch(*args, **kwargs):
                f = f2cent(args[0], _standard_frequency)
                self.spectrum.plot(f, *args[1:], **kwargs)

            self.plot_spectrum = plot_pitch
            self.spectrum.set_ylim(0, 1500000)
            self.spectrum.set_xlim(-5000, 5000)

    def on_fft_smooth_select(self):
        for c in self.smooth_choices:
            if c.isChecked():
                self.fft_smooth_factor = int(c.text())
                break

    def on_color_select(self, d=None):
        for c in self.color_choices:
            if c.isChecked():
                self.color = c.text()
                break


class CheckBoxSelect(QWidget):
    check_box_toggled = qc.pyqtSignal(int)

    def __init__(self, value, parent):
        QWidget.__init__(self, parent=parent)
        self.value = value
        self.check_box = QPushButton(str(self.value), parent=self)
        self.action = QWidgetAction(self)
        self.action.setDefaultWidget(self.check_box)
        self.check_box.clicked.connect(self.on_state_changed)

    @qc.pyqtSlot()
    def on_state_changed(self):
        self.check_box_toggled.emit(self.value)

def set_tick_choices(menu, default=20):
    group = QActionGroup(menu)
    group.setExclusive(True)
    for tick_increment in [10, 20, 50, 100]:
        action = QAction(str(tick_increment), menu)
        action.setCheckable(True)
        if tick_increment == default:
            action.setChecked(True)
        group.addAction(action)
        menu.addAction(action)


class OverView(QWidget):
    highlighted_pitches = set([0.])

    def __init__(self, *args, **kwargs):
        QWidget.__init__(self, *args, **kwargs)

        layout = QGridLayout()
        self.setLayout(layout)
        self.figure = Axis()
        self.figure.xlabels = False
        self.figure.set_ylim(-1500., 1500)
        self.figure.set_grids(100.)
        layout.addWidget(self.figure)

        self.right_click_menu = QMenu('Tick Settings', self)
        self.right_click_menu.triggered.connect(
            self.figure.on_tick_increment_select)
        set_tick_choices(self.right_click_menu, default=100)
        action = QAction('Minor ticks', self.right_click_menu)
        action.setCheckable(True)
        action.setChecked(True)
        self.right_click_menu.addAction(action)
        self.attach_highlight_pitch_menu()

    def attach_highlight_pitch_menu(self):
        pmenu = QMenu('Highlight pitches', self)
        pmenu.addSeparator()
        for v in ['', 1200, 700, 500]:
            action = QWidgetAction(pmenu)
            check_box_widget = CheckBoxSelect(v, pmenu)
            check_box_widget.check_box_toggled.connect(
                self.on_check_box_widget_toggled)
            pmenu.addAction(check_box_widget.action)

        self.right_click_menu.addMenu(pmenu)

    @qc.pyqtSlot(qg.QMouseEvent)
    def mousePressEvent(self, mouse_ev):
        if mouse_ev.button() == qc.Qt.RightButton:
            self.right_click_menu.exec_(qg.QCursor.pos())
        else:
            QWidget.mousePressEvent(self, mouse_ev)

    @qc.pyqtSlot(int)
    def on_check_box_widget_toggled(self, value):
        if value in self.highlighted_pitches:
            self.highlighted_pitches.remove(value)
            self.highlighted_pitches.remove(-1*value)
        else:
            self.highlighted_pitches.add(value)
            self.highlighted_pitches.add(-1*value)


class PitchWidget(OverView):
    ''' Pitches of each trace as discrete samples.'''

    def __init__(self, channel_views, *args, **kwargs):
        OverView.__init__(self, *args, **kwargs)
        self.channel_views = channel_views

        save_as_action = QAction('Save pitches', self.right_click_menu)
        save_as_action.triggered.connect(self.on_save_as)
        self.right_click_menu.addAction(save_as_action)
        self.track_start = None
        self.tfollow = 3.
        self.setContentsMargins(-10, -10, -10, -10)

    @qc.pyqtSlot()
    def on_draw(self):
        for cv in self.channel_views:
            x, y = cv.channel.pitch.latest_frame(
                self.tfollow, clip_min=True)
            index = num.where(cv.channel.pitch_confidence.latest_frame_data(
                len(x))>=cv.confidence_threshold)[0]
            # TODO: attach filter 2000 to slider
            index_grad = index_gradient_filter(x, y, 2000)
            index = num.intersect1d(index, index_grad)
            indices_grouped = consecutive(index)
            for group in indices_grouped:
                self.figure.plot(
                    x[group], y[group], color=cv.color, line_width=4)

            xstart = num.min(x)
            self.figure.set_xlim(xstart, xstart+self.tfollow)

        for high_pitch in self.highlighted_pitches:
            self.figure.axhline(high_pitch, line_width=2)
        self.figure.update()

    @qc.pyqtSlot()
    def on_clear(self):
        self.figure.clear()

    @qc.pyqtSlot()
    def on_save_as(self):
        _fn = QFileDialog().getSaveFileName(self, 'Save as text file', '.', '')[0]
        if _fn:
            if not os.path.exists(_fn):
                os.makedirs(_fn)
            for i, cv in enumerate(self.channel_views):
                fn = os.path.join(_fn, 'channel%s.txt' %i)
                x, y = cv.channel.pitch.xdata, cv.channel.pitch.ydata
                index = num.where(cv.channel.pitch_confidence.latest_frame_data(
                    len(x))>=cv.confidence_threshold)
                num.savetxt(fn, num.vstack((x[index], y[index])).T)

    #def mouseReleaseEvent(self, mouse_event):
    #    self.track_start = None

    #def mouseMoveEvent(self, mouse_ev):
    #    ''' from pyrocko's pile viewer'''
    #    point = self.mapFromGlobal(mouse_ev.globalPos())

    #    self.change = self.tfollow
    #    if self.track_start is not None:

    #        x0, y0 = self.track_start
    #        dx = (point.x()- x0)/float(self.width())
    #        dy = (point.y() - y0)/float(self.height())
    #        #if self.ypart(y0) == 1:
    #        #dy = 0

    #        #tmin0, tmax0 = self.xlim

    #        scale = -dy*4.
    #        frac = x0/ float(self.width())

    #        #self.interrupt_following()
    #        #self.tfollow += min(max(2., 2 + self.tfollow * scale), 30)
    #        self.tfollow = min(max(2., 2 + self.tfollow * scale), 30)
    #        ymin, ymax = self.figure.get_ylim()
    #        #self.figure.set_ylim(ymin+dy*10, ymax+dy*10)
    #        self.update()

    #@qc.pyqtSlot(qg.QMouseEvent)
    #def mousePressEvent(self, mouse_ev):
    #    if mouse_ev.button() == qc.Qt.RightButton:
    #        self.right_click_menu.exec_(qg.QCursor.pos())
    #    else:
    #        try:
    #            QWidget.mousePressEvent(mouse_ev)
    #        except TypeError as e:
    #            logger.warn(e)



class DifferentialPitchWidget(OverView):
    ''' Diffs as line'''
    def __init__(self, channel_views, *args, **kwargs):
        OverView.__init__(self, *args, **kwargs)
        self.setContentsMargins(-10, -10, -10, -10)
        self.channel_views = channel_views
        self.derivative_filter = 2000    # pitch/seconds

    @qc.pyqtSlot(int)
    def on_derivative_filter_changed(self, max_derivative):
        self.derivative_filter = max_derivative

    @qc.pyqtSlot()
    def on_draw(self):
        for i1, cv1 in enumerate(self.channel_views):
            x1, y1 = cv1.channel.pitch.latest_frame(tfollow, clip_min=True)
            xstart = num.min(x1)
            index1 = num.where(cv1.channel.pitch_confidence.latest_frame_data(
                len(x1))>=cv1.confidence_threshold)
            index1_grad = index_gradient_filter(x1, y1, self.derivative_filter)
            index1 = num.intersect1d(index1, index1_grad)
            for i2, cv2 in enumerate(self.channel_views):
                if i1>=i2:
                    continue
                x2, y2 = cv2.channel.pitch.latest_frame(tfollow, clip_min=True)
                index2_grad = index_gradient_filter(x2, y2, self.derivative_filter)
                index2 = num.where(cv2.channel.pitch_confidence.latest_frame_data(
                    len(x2))>=cv2.confidence_threshold)
                index2 = num.intersect1d(index2, index2_grad)
                indices = num.intersect1d(index1, index2)
                indices_grouped = consecutive(indices)
                for group in indices_grouped:
                    y = y1[group] - y2[group]
                    x = x1[group]
                    self.figure.plot(
                        x, y, style='solid', line_width=4, color=cv1.color, antialiasing=False)
                    self.figure.plot(
                        x, y, style=':', line_width=4, color=cv2.color, antialiasing=False)

        self.figure.set_xlim(xstart, xstart+tfollow)

        for high_pitch in self.highlighted_pitches:
            self.figure.axhline(high_pitch, line_width=2)

        # update needed on OSX
        self.figure.update()

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
        self.right_click_menu = QMenu('Tick Settings', self)
        self.right_click_menu.triggered.connect(
                self.on_tick_increment_select)
        set_tick_choices(self.right_click_menu)

        # TODO add slider
        self.naverage = 7
        ylim = (-1500, 1500.)
        for i1, cv1 in enumerate(self.channel_views):
            for i2, cv2 in enumerate(self.channel_views):
                if i1>=i2:
                    continue
                w = GaugeWidget(gl=True)
                w.set_ylim(*ylim)
                w.set_title('Channels: %s | %s' % (i1+1, i2+1))
                self.widgets.append((cv1, cv2, w))
                layout.addWidget(w, i1, i2)

    @qc.pyqtSlot(QAction)
    def on_tick_increment_select(self, action):
        for cv1, cv2, widget in self.widgets:
            widget.xtick_increment = int(action.text())

    @qc.pyqtSlot()
    def on_draw(self):
        for cv1, cv2, w in self.widgets:
            confidence1 = num.where(cv1.channel.pitch_confidence.latest_frame_data(self.naverage)>cv1.confidence_threshold)
            confidence2 = num.where(cv2.channel.pitch_confidence.latest_frame_data(self.naverage)>cv2.confidence_threshold)
            confidence = num.intersect1d(confidence1, confidence2)
            if len(confidence)>1:
                d1 = cv1.channel.pitch.latest_frame_data(self.naverage)[confidence]
                d2 = cv2.channel.pitch.latest_frame_data(self.naverage)[confidence]
                w.set_data(num.median(d1-d2))
            else:
                w.set_data(None)
            w.update()

    @qc.pyqtSlot(qg.QMouseEvent)
    def mousePressEvent(self, mouse_ev):
        if mouse_ev.button() == qc.Qt.RightButton:
            self.right_click_menu.exec_(qg.QCursor.pos())
        else:
            QWidget.mousePressEvent(self, mouse_ev)


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
            w.update()


class MainWidget(QWidget):
    ''' top level widget covering the central widget in the MainWindow.'''
    signal_widgets_clear = qc.pyqtSignal()
    signal_widgets_draw = qc.pyqtSignal()

    def __init__(self, settings, *args, **kwargs):
        QWidget.__init__(self, *args, **kwargs)
        self.tabbed_pitch_widget = QTabWidget()

        pal = self.tabbed_pitch_widget.palette()
        self.tabbed_pitch_widget.setAutoFillBackground(True)
        pal.setColor(qg.QPalette.Background, qg.QColor(*_colors['white']))
        self.tabbed_pitch_widget.setPalette(pal)

        pal = self.palette()
        self.setAutoFillBackground(True)
        pal.setColor(qg.QPalette.Background, qg.QColor(*_colors['white']))
        self.setPalette(pal)

        self.tabbed_pitch_widget.setSizePolicy(QSizePolicy.Minimum,
                                          QSizePolicy.Minimum)

        self.setMouseTracking(True)
        self.top_layout = QGridLayout()
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
        menu.pause_button.clicked.connect(self.refresh_timer.stop)

        menu.save_as_button.clicked.connect(self.on_save_as)

        menu.play_button.clicked.connect(self.data_input.start)
        menu.play_button.clicked.connect(self.refresh_timer.start)

        menu.set_algorithms(pitch_algorithms, default='yin')
        menu.select_algorithm.currentTextChanged.connect(
            self.on_algorithm_select)

    @qc.pyqtSlot()
    def on_save_as(self):
        '''Write traces to wav files'''
        _fn = QFileDialog().getSaveFileName(self, 'Save as', '.', '')[0]
        if _fn:
            for i, tr in enumerate(self.channel_views_widget.channel_views):
                if not os.path.exists(_fn):
                    os.makedirs(_fn)
                fn = os.path.join(_fn, 'channel%s' %i)
                tr.channel.save_as(fn, fmt='wav')

    @qc.pyqtSlot(str)
    def on_algorithm_select(self, arg):
        '''change pitch algorithm'''
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
            self.menu.connect_to_confidence_threshold(cv)
            channel_views.append(cv)

        self.channel_views_widget = ChannelViews(channel_views)
        self.top_layout.addWidget(self.channel_views_widget, 1, 0)

        self.keyboard = KeyBoard(self)
        self.keyboard.setVisible(False)
        self.keyboard.connect_channel_views(self.channel_views_widget)
        self.top_layout.addWidget(self.keyboard, 0, 0, 1, -1)

        self.top_layout.addWidget(self.tabbed_pitch_widget, 1, 1)
        self.pitch_view = PitchWidget(channel_views)

        self.pitch_view_all_diff = DifferentialPitchWidget(channel_views)
        self.pitch_diff_view = PitchLevelDifferenceViews(channel_views)
        #self.pitch_diff_view_colorized = PitchLevelMikadoViews(channel_views)

        self.tabbed_pitch_widget.addTab(self.pitch_view, 'Pitches')
        self.tabbed_pitch_widget.addTab(self.pitch_view_all_diff, 'Differential')
        self.tabbed_pitch_widget.addTab(self.pitch_diff_view, 'Current')
        #self.tabbed_pitch_widget.addTab(self.pitch_diff_view_colorized, 'Mikado')

        self.menu.derivative_filter_slider.valueChanged.connect(
            self.pitch_view_all_diff.on_derivative_filter_changed)
        self.menu.connect_channel_views(self.channel_views_widget)

        self.signal_widgets_clear.connect(self.pitch_view.on_clear)
        self.signal_widgets_clear.connect(self.pitch_view_all_diff.on_clear)

        self.signal_widgets_draw.connect(self.pitch_view.on_draw)
        self.signal_widgets_draw.connect(self.pitch_view_all_diff.on_draw)
        self.signal_widgets_draw.connect(self.pitch_diff_view.on_draw)
        #self.signal_widgets_draw.connect(self.pitch_diff_view_colorized.on_draw)

        self.views = [
            self.pitch_view, self.pitch_view_all_diff, self.pitch_diff_view
        ]

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

    def toggle_keyboard(self):
        self.keyboard.setVisible(not self.keyboard.isVisible())


class MainWindow(QMainWindow):
    ''' Top level Window. The entry point of the gui.'''
    def __init__(self, settings, *args, **kwargs):
        #super(QMainWindow, self).__init__(*args, **kwargs)
        super().__init__(*args, **kwargs)
        self.main_widget = MainWidget(settings, )
        self.main_widget.setFocusPolicy(qc.Qt.StrongFocus)

        self.setCentralWidget(self.main_widget)

        controls_dock_widget = QDockWidget()
        controls_dock_widget.setWidget(self.main_widget.menu)

        views_dock_widget = QDockWidget()
        views_dock_widget.setWidget(self.main_widget.tabbed_pitch_widget)

        self.addDockWidget(qc.Qt.LeftDockWidgetArea, controls_dock_widget)
        self.addDockWidget(qc.Qt.RightDockWidgetArea, views_dock_widget)

        self.show()

    def sizeHint(self):
        return qc.QSize(700, 600)

    @qc.pyqtSlot(qg.QKeyEvent)
    def keyPressEvent(self, key_event):
        ''' react on keyboard keys when they are pressed.'''
        key_text = key_event.text()
        if key_text == 'q':
            self.close()

        elif key_text == 'k':
            self.main_widget.toggle_keyboard()

        elif key_text == 'f':
            self.showMaximized

        else:
            super().keyPressEvent(key_event)



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

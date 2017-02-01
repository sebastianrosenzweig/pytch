import threading
import pyaudio
from aubio import pitch
import atexit
import numpy as num
import logging

from pytch.util import DummySignal
_lock = threading.Lock()

# class taken from the scipy 2015 vispy talk opening example
# see https://github.com/vispy/vispy/pull/928

logger = logging.getLogger(__name__)


def append_to_frame(f, d):
    ''' shift data in f and append new data d to buffer f'''
    i = d.shape[0]
    #f[:-i] = f[i:]
    num.roll(f, -i)
    f[-i:] = d.T


def prepend_to_frame(f, d):
    i = d.shape[0]
    num.roll(f, i)
    f[:i] = d.T


def getaudiodevices():
    ''' returns a list of device descriptions'''
    p = pyaudio.PyAudio()
    devices = []
    for i in range(p.get_device_count()):
        devices.append(p.get_device_info_by_index(i).get('name'))
    p.terminate()
    return devices


def sampling_rate_options(device_no, audio=None):
    ''' list of supported sampling rates.'''
    candidates = [8000., 11.025, 123123123123., 16000., 22050., 32000., 37.800, 44100.,
                  48000.]
    supported_sampling_rates = []
    for c in candidates:
        if check_sampling_rate(device_no, int(c), audio=audio):
            supported_sampling_rates.append(c)

    return supported_sampling_rates


def check_sampling_rate(device_index, sampling_rate, audio=None):
    p = audio or pyaudio.PyAudio()
    devinfo = p.get_device_info_by_index(device_index)
    valid = False
    try:
        p.is_format_supported(
            sampling_rate,
            input_device=devinfo['index'],
            input_channels=devinfo['maxinputchannels'],
            input_format=pyaudio.paint16)
    except ValueError as e:
        logger.debug(e)
        valid = False

    finally:
        if not audio:
            p.terminate()
        return valid


class Buffer():

    ''' data container

    new data is prepended, so that the latest data point is in self.data[0]'''
    def __init__(self, sampling_rate, buffer_length_seconds, dtype=num.float32, tmin=0):
        self.tmin = tmin
        self.tmax = self.tmin + buffer_length_seconds
        self.sampling_rate = sampling_rate
        self.data_len = buffer_length_seconds * sampling_rate
        self.dtype = dtype
        self.empty()

        self.i_filled = 0

        self._x = num.arange(self.data_len, dtype=self.dtype) *self.delta + self.tmin

    def empty(self):
        self.data = num.empty((int(self.data_len)),
                          dtype=self.dtype)

    def dump(self):
        pass

    @property
    def t_filled(self):
        ''' the time to which the data buffer contains data.'''
        return self.tmin + self.i_filled*self.delta

    @property
    def delta(self):
        return 1./self.sampling_rate

    @property
    def xdata(self):
        return self._x

    @property
    def ydata(self):
        return self.data[:self.i_filled]

    def index_at_time(self, t):
        ''' Get the index of the sample (closest) defined by *t* '''
        return int((t-self.tmin) * self.sampling_rate)

    def latest_indices(self, seconds):
        return self.i_filled-int(min(
            seconds * self.sampling_rate, self.i_filled)), self.i_filled

    def latest_frame(self, seconds):
        ''' Return the latest *seconds* data from buffer as x and y data tuple.'''
        istart, istop = self.latest_indices(seconds)
        return (self._x[istart: istop], self.data[istart: istop])

    def latest_frame_data(self, n):
        ''' Return the latest n samples data from buffer as array.'''
        if n>self.i_filled:
            return None
        else:
            return self.data[num.arange(max(self.i_filled-n, 0), self.i_filled) %
                             self.data.size]

    def append(self, d):
        ''' Append data frame *d* to Buffer'''
        n = d.shape[0]
        if self.i_filled + n > self.data.size:
            raise Exception('data overflow')
        self.data[self.i_filled:self.i_filled+n] = d
        self.i_filled += n

    def energy(self, nsamples_total, nsamples_sum=1):
        xi = num.arange(self.i_filled-nsamples_total, self.i_filled)
        y = self.data[xi].reshape((int(len(xi)/nsamples_sum), nsamples_sum))
        y = num.sum(y**2, axis=1)
        return self._x[xi[::nsamples_sum]], y


class RingBuffer(Buffer):
    def __init__(self, *args, **kwargs):
        Buffer.__init__(self, *args, **kwargs)

    def append(self, d):
        n = d.size
        xi = (self.i_filled + num.arange(n)) % self.data.size
        self.data[xi] = d
        self.i_filled += n


class RingBuffer2D(RingBuffer):
    def __init__(self, ndimension2, *args, **kwargs):
        self.ndimension2 = ndimension2
        RingBuffer.__init__(self, *args, **kwargs)
    
    def empty(self):
        self.data = num.empty((int(self.data_len), self.ndimension2),
                          dtype=self.dtype)

    def append(self, d):
        self.data[self.i_filled, :] = d
        self.i_filled += 1


class DataProvider(object):
    ''' Base class defining common interface for data input to Worker'''
    def __init__(self):
        self.frames = []
        atexit.register(self.terminate)

    #def get_data(self):
    #    return self.frames

    def terminate(self):
        # cleanup
        pass


class SamplingRateException(Exception):
    pass


class Channel(RingBuffer):
    def __init__(self, sampling_rate, fftsize=8192):
        self.buffer_length_seconds = 100
        RingBuffer.__init__(self, sampling_rate, self.buffer_length_seconds)
        self.name = ''
        self.pitch_o = False
        self.fftsize = fftsize
        self.setup_pitch()
        self.update()

    def update(self):
        nfft = (int(self.fftsize), self.delta)
        self.freqs = num.fft.rfftfreq(*nfft)
        self.fft = RingBuffer2D(
            ndimension2=self.fftsize/2+1, sampling_rate=self.sampling_rate,
            buffer_length_seconds=self.buffer_length_seconds)
        self.pitch = RingBuffer(
            self.sampling_rate/self.fftsize,
            self.sampling_rate*self.buffer_length_seconds/self.fftsize)

    @property
    def fftsize(self):
        return self.__fftsize

    @fftsize.setter
    def fftsize(self, size):
        self.__fftsize = size
        self.update()

    def setup_pitch(self):
        tolerance = 0.8
        win_s = self.fftsize
        #self.pitch_o = pitch(self.pitch_algorithms[ialgorithm],
        self.pitch_o = pitch('yin',
          win_s, win_s, self.sampling_rate)
        self.pitch_o.set_unit("Hz")
        self.pitch_o.set_tolerance(tolerance)


class MicrophoneRecorder(DataProvider):

    def __init__(self, chunksize=512, device_no=None, sampling_rate=None, fftsize=1024,
                 nchannels=2, data_ready_signal=None):
        DataProvider.__init__(self)

        self.stream = None
        self.p = pyaudio.PyAudio()
        self.nchannels = nchannels
        default = self.p.get_default_input_device_info()

        self.device_no = device_no or default['index']
        self.sampling_rate = sampling_rate or int(default['defaultSampleRate'])

        self.channels = []
        for i in range(self.nchannels):
            c = Channel(self.sampling_rate, fftsize=fftsize)
            self.channels.append(c)

        self.chunksize = chunksize
        self.data_ready_signal = data_ready_signal or DummySignal()

    @property
    def sampling_rate_options(self):
        ''' List of supported sampling rates.'''
        return sampling_rate_options(self.device_no, audio=self.p)

    def new_frame(self, data, frame_count, time_info, status):
        data = num.asarray(num.fromstring(data, 'int16'), num.float32)

        with _lock:
            self.frames.append(data)
            if self._stop:
                return None, pyaudio.paComplete

        self.data_ready_signal.emit()

        return None, pyaudio.paContinue

    def get_frames(self):
        with _lock:
            frames = self.frames
            self.frames = []
        return frames

    def start(self):
        if self.stream is None:
            self.start_new_stream()

        self.stream.start_stream()
        self._stop = False

    @property
    def sampling_rate(self):
        return self.__sampling_rate

    @sampling_rate.setter
    def sampling_rate(self, rate):
        check_sampling_rate(self.device_no, rate, audio=self.p)
        self.__sampling_rate = rate

    def start_new_stream(self):
        self.frames = []
        self.stream = self.p.open(format=pyaudio.paInt16,
                                  channels=self.nchannels,
                                  rate=self.sampling_rate,
                                  input=True,
                                  output=False,
                                  frames_per_buffer=self.chunksize,
                                  input_device_index=self.device_no,
                                  stream_callback=self.new_frame)
        self._stop = False
        logger.debug('starting new stream: %s' % self.stream)
        self.stream.start_stream()

    def stop(self):
        with _lock:
            self._stop = True
        if self.stream is not None:
            self.stream.stop_stream()

    def close(self):
        self.stop()
        self.stream.close()

    def terminate(self):
        if self.stream:
            self.close()
        self.p.terminate()
        logger.debug('terminated stream')

    def set_device_no(self, i):
        self.close()
        self.device_no = i
        self.start_new_stream()

    @property
    def deltat(self):
        return 1./self.sampling_rate

    def flush(self):
        ''' read data and put it into channels' track_data'''
        # make this entirely numpy:
        frames = num.array(self.get_frames())
        for frame in frames:
            r = num.reshape(frame, (self.chunksize,
                                    self.nchannels)).T
            for i, channel in enumerate(self.channels):
                channel.append(r[i])



# -*- coding: utf-8 -*-

import math
from aubio import pitch
import numpy as num
import time

from pytch.util import DummySignal, f2pitch

import logging

_standard_frequency = 220.
logger = logging.getLogger(__name__)


class Worker():

    def __init__(self, channels):
        ''' Grabbing data, working on it and saving the results

        :param buffer_length: in seconds'''

        self.ndata_scale = 16*2
        self.channels = channels
        self.nchannels = len(self.channels)
        self.cross_spectra_combinations = []
        self.spectral_smoothing = False
        self.set_pitch_algorithm(0)

    def set_spectral_smoothing(self, state):
        self.spectral_smoothing = state

    def set_pitch_algorithm(self, ialgorithm):
        '''
        :param ialgorithm:
        index of desired algorithm'''

        for ic, channel in enumerate(self.channels):
            tolerance = 0.8
            win_s = channel.fftsize

    def process(self):
        ''' Do the work'''
        logger.debug('start processing')

        for ic, channel in enumerate(self.channels):
            frame_work = channel.latest_frame_data(channel.fftsize)

            amp_spec = num.abs(num.fft.rfft(frame_work))
            channel.fft.append(amp_spec)
            channel.fft_power.append_value(num.sum(amp_spec)/channel.sampling_rate)

            #total_power = num.sum(channel.fft)/len(channel.freqs)
            #new_pitch_Cent = -9999999.
            #else:
            #pitch = channel.pitch_o(frame_work.astype(num.float32))[0]
            #new_pitch_Cent = channel.pitch_o(frame_work)[0]
            channel.pitch.append_value(f2pitch(channel.pitch_o(frame_work)[0], _standard_frequency))
            #channel.pitch.append_value(channel.pitch_o(frame_work)[0])
        #    #pitch_confidence2 = pitch_o.get_confidence()

        #    self.pitchlog_vect1 = num.roll(self.pitchlog_vect1, -1)
        #    self.pitchlog_vect2 = num.roll(self.pitchlog_vect2, -1)

        #    self.new_pitch1Cent = 1200.* math.log((self.new_pitch1+.1)/120., 2)
        #    self.new_pitch2Cent = 1200.* math.log((self.new_pitch2+.1)/120., 2)

        #    self.pitchlog_vect1[-1] = self.new_pitch1Cent
        #    self.pitchlog_vect2[-1] = self.new_pitch2Cent

        #    #ivCents = abs(self.new_pitch2Cent - self.new_pitch1Cent)
        #    #if 0< ivCents <= 1200:
        #    #    plot gauge

        #    # plot self.new_pitcj1Cent - self.newptch2Cent und anders rum
        #    #self.signalReady.emit()
        #self.processingFinished.emit()

        logger.debug('finished processing')


def cross_spectrum(spec1, spec2):
    ''' Returns cross spectrum and phase of *spec1* and *spec2*'''
    cross = spec1 * spec2.conjugate()
    return num.abs(cross), num.unwrap(num.arctan2(cross.imag, cross.real))


def compute_pitch_hps(x, Fs, dF=None, Fmin=30., Fmax=900., H=5):
    # default value for dF frequency resolution
    if dF is None:
        dF = Fs / x.size

    # Hamming window apodization
    x = num.array(x, dtype=num.double, copy=True)
    x *= num.hamming(x.size)

    # number of points in FFT to reach the resolution wanted by the user
    n_fft = num.ceil(Fs / dF)

    # DFT computation
    X = num.abs(num.fft.fft(x, n=int(n_fft)))

    # limiting frequency R_max computation
    R = num.floor(1 + n_fft / 2. / H)

    # computing the indices for min and max frequency
    N_min = num.ceil(Fmin / Fs * n_fft)
    N_max = num.floor(Fmax / Fs * n_fft)
    N_max = min(N_max, R)

    # harmonic product spectrum computation
    indices = (num.arange(N_max)[:, num.newaxis] * num.arange(1, H+1)).astype(int)
    P = num.prod(X[indices.ravel()].reshape(N_max, H), axis=1)
    ix = num.argmax(P * ((num.arange(P.size) >= N_min) & (num.arange(P.size) <= N_max)))
    return dF * ix

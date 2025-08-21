import zmq
import sys
import os
import time
import argparse

import matplotlib.pyplot as plt
import numpy as np
from scipy import signal
from scipy.fft import fft, fftshift, fftfreq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low

def send_envelope_and_get_reply(socket, envelope) -> bytes:
    """
    Sends a protobuf ControlEnvelope and returns the last frame of the reply.
    Compatible with REP and ROUTER servers.
    """
    socket.send(envelope.SerializeToString())

    frames = [socket.recv()]
    while socket.getsockopt(zmq.RCVMORE):
        frames.append(socket.recv())

    return frames[-1]  # Payload is always in the last frame

parser = argparse.ArgumentParser(description="Oscilloscope.")
parser.add_argument("-ip", type=str, required=True, help="IP address of DAPHNE.")
parser.add_argument("-port", type=int, required=False, default=9000, help="Port number of DAPHNE.")
parser.add_argument("-channel", type=int, choices=range(0, 40), required=True, help="0-39.")
parser.add_argument("-L", type=int, required=True, help="Length of waveform.")
parser.add_argument("-software_trigger", action='store_true', help="Enables software trigger.")
parser.add_argument("-enable_info", action='store_true', required=False, help="Enables information display (RMS, Peak-to-Peak).")
parser.add_argument("-enable_fft", action='store_true', required=False, help="Opens a second windows for live FFT display.")
parser.add_argument("-fft_avg_waves", type=int, required=False, default=100, help="Sets the number of averaged waveforms for FFT display. Default 10.")
parser.add_argument("-fft_window_function", type=str, required=False, default="BLACKMAN-HARRIS", choices=["NONE","HANNING", "HAMMING", "BLACKMAN", "BLACKMAN-HARRIS", "TUKEY"], help="Sets the window function for FFT display. Default BLACKMAN-HARRIS.")

# Parse arguments
args = parser.parse_args()
# Setup ZMQ context once
context = zmq.Context()

# Create the figure and line once
fig, ax = plt.subplots()
x = np.arange(args.L)
y = np.zeros_like(x)
line, = ax.plot(x, y)
ax.set_ylim(5000, 10000)  # Adjust to your expected signal range
ax.grid(True)
#set title and labels
ax.set_title(f"Oscilloscope - Channel {args.channel}")
ax.set_xlabel("Samples")
ax.set_ylabel("ADC Counts")

if args.enable_info:
    rms = 0.0
    peak_to_peak = 0.0
    info_text = f"RMS: {rms:.2f}\nPeak-to-Peak: {peak_to_peak:.2f}"
    ax.text(0.02, 0.95, info_text, transform=ax.transAxes, fontsize=10,
                verticalalignment='top', bbox=dict(facecolor='white', alpha=0.5))
    ax.plot(0, 0, 'ro')
    ax.plot(0, 0, 'bo')

plt.ion()  # Turn on interactive mode
plt.show()

Fs = 62.5e6  # Sampling frequency

if args.enable_fft:
    fig_fft, ax_fft = plt.subplots()
    x_fft = fftshift(fftfreq(args.L, 1/Fs))
    # create 2d array for FFT average
    Y_mag = np.zeros((args.fft_avg_waves, args.L))
    # calculate the columwise average of the Y_mag
    Y_mag_mean = np.mean(Y_mag, axis=0)
    line_fft, = ax_fft.plot(x_fft, Y_mag_mean)
    ax_fft.set_ylim(0, 1000)  # Adjust to your expected FFT range
    ax_fft.set_xlim(Fs/args.L, Fs/2)  # Adjust x-axis limits
    # set log scale in x-axis
    ax_fft.set_xscale('log')
    ax_fft.grid(True)
    ax_fft.set_title(f"FFT - Channel {args.channel} - {args.fft_window_function} Window")
    ax_fft.set_xlabel("Frequency (Hz)")
    ax_fft.set_ylabel("Magnitude (dBFS)")
    plt.show()

socket = context.socket(zmq.DEALER)
socket.setsockopt(zmq.IDENTITY, b"client-compat")
ip_addr = "tcp://{}:{}".format(args.ip, args.port)
socket.connect(ip_addr)
channel = args.channel
length_of_waveforms = args.L
software_trigger = args.software_trigger

acquired_wave_number = 0

while True:
    # DO SOFTWARE TRIGGER
    # if(software_trigger):
    #     request = pb_low.cmd_doSoftwareTrigger()
    #     envelope = pb_high.ControlEnvelope()
    #     envelope.type = pb_high.DO_SOFTWARE_TRIGGER
    #     envelope.payload = request.SerializeToString()

    #     socket.send(envelope.SerializeToString())
    #     response_bytes = socket.recv()

    #     responseEnvelope = pb_high.ControlEnvelope()
    #     responseEnvelope.ParseFromString(response_bytes)

    #     if responseEnvelope.type == pb_high.DO_SOFTWARE_TRIGGER:
    #         response = pb_low.cmd_doSoftwareTrigger_response()
    #         response.ParseFromString(responseEnvelope.payload)
    #     # print("Success:", response.success)
    #     # print("Message:", response.message)

    # DUMP SPYBUFFER
    request = pb_high.DumpSpyBuffersRequest()
    request.channelList.append(channel)
    request.numberOfWaveforms = 1
    if software_trigger:
        request.softwareTrigger = True
    else:
        request.softwareTrigger = False
    request.numberOfSamples = length_of_waveforms

    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.DUMP_SPYBUFFER
    envelope.payload = request.SerializeToString()

    response_bytes = send_envelope_and_get_reply(socket, envelope)

    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.DUMP_SPYBUFFER:
        response = pb_high.DumpSpyBuffersResponse()
        response.ParseFromString(responseEnvelope.payload)
        # print("Success:", response.success)
        # print("Message:", response.message)

    y = np.array(response.data, dtype='uint32')

    # get max and min values for y and their indices
    max_y = np.max(y)
    min_y = np.min(y)
    max_y_index = np.argmax(y)
    min_y_index = np.argmin(y)

    if args.enable_info:
        # Calculate RMS and Peak-to-Peak
        rms = np.sqrt(np.mean(y**2))
        rms_b = np.sqrt(np.mean((y - np.mean(y))**2))
        peak_to_peak = max_y - min_y
        # get the text object to modify it
        if ax.texts:
            text = ax.texts[0]
        else:
            text = ax.text(0.02, 0.95, "", transform=ax.transAxes, fontsize=10,
                           verticalalignment='top', bbox=dict(facecolor='white', alpha=0.5))
        text.set_text(f"RMS: {rms:.2f}\nRMS-b: {rms_b:.2f}\nPeak-to-Peak: {peak_to_peak:.2f}")
        # get the red and blue points
        red_point = ax.lines[1]
        blue_point = ax.lines[2]
        # update the red point to the max value
        red_point.set_data([max_y_index], [max_y])
        # update the blue point to the min value
        blue_point.set_data([min_y_index], [min_y])


    
    line.set_ydata(y)

    if args.enable_fft:
        # Compute FFT
        if args.fft_window_function == "NONE":
            window = np.ones_like(y)
        elif args.fft_window_function == "HANNING":
            window = np.hanning(len(y))
        elif args.fft_window_function == "HAMMING":
            window = np.hamming(len(y))
        elif args.fft_window_function == "BLACKMAN":
            window = np.blackman(len(y))
        elif args.fft_window_function == "BLACKMAN-HARRIS":
            window = signal.windows.blackmanharris(len(y))
        elif args.fft_window_function == "TUKEY":
            window = signal.windows.tukey(len(y), alpha=0.1)
        
        # Apply window function
        y_windowed = y * window
        # Compute FFT with scipy
        Y = fft(y_windowed)
        Y = fftshift(Y)

        # Convert FFT to dBFS
        Y_mag_local = np.abs(Y) / (args.L/2)
        Y_mag[acquired_wave_number % args.fft_avg_waves, :] = Y_mag_local
        Y_mag_mean = np.mean(Y_mag, axis=0)
        Y_dbfs = 20 * np.log10(Y_mag_mean / 2**14)
        acquired_wave_number += 1
        line_fft.set_ydata(Y_dbfs)   
        ax_fft.set_ylim(np.min(Y_dbfs) * 1.1, np.max(Y_dbfs) * 1.1)
        fig_fft.canvas.draw()
        fig_fft.canvas.flush_events()
        

    # Optionally adjust y-limits dynamically:
    # ax.set_ylim(y.min(), y.max())

    fig.canvas.draw()
    fig.canvas.flush_events()

    time.sleep(0.001)  # Slow down update rate if needed


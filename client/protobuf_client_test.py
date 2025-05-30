import zmq
import json
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low

with open('../srcs/protobuf/np02-daphne-running.json') as file:
    np02_config = json.load(file)

config_file_keys = np02_config.keys()
devices_list = []
for file_key in config_file_keys:
    devices_list.append(np02_config[file_key])

# Prepare request
for device in devices_list:
    request = pb_high.ConfigureRequest()
    request.daphne_address = "192.168.0.10"
    request.slot = device['slot']
    request.timeout_ms = 500
    request.biasctrl = device['bias_ctrl']
    request.self_trigger_threshold = device['self_trigger_threshold']
    request.self_trigger_xcorr = device['self_trigger_xcorr']
    request.tp_conf = device['tp_conf']
    request.compensator = device['compensator']
    request.inverters = device['inverter']

    # adding channels
    
    channels_ids = device['channel_analog_conf']['ids']
    channels_gains = device['channel_analog_conf']['gains']
    channels_offsets = device['channel_analog_conf']['offsets']
    channels_trims = device['channel_analog_conf']['trims']

    for i in range(0, len(channels_ids)):
        channel = request.channels.add()
        channel.id = channels_ids[i]
        channel.trim = channels_trims[i]
        channel.offset = channels_offsets[i]
        channel.gain = channels_gains[i]

    afe_ids = device['afes']['ids']
    afe_attenuators = device['afes']['attenuators']
    afe_vbiases = device['afes']['v_biases']
    afe_adcs = device['afes']['adcs']
    afe_pgas = device['afes']['pgas']
    afe_lnas = device['afes']['lnas']
    
    afe_adcs_resolutions = afe_adcs['resolution']
    afe_adcs_output_format = afe_adcs['output_format']
    afe_adcs_SB_first = afe_adcs['SB_first']

    afe_pgas_lpf_cut_frequency = afe_pgas['lpf_cut_frequency']
    afe_pgas_integrator_disable = afe_pgas['integrator_disable']
    afe_pgas_gains = afe_pgas['gain']

    afe_lnas_clamp = afe_lnas['clamp']
    afe_lnas_integrator_disable = afe_lnas['integrator_disable']
    afe_lnas_gains = afe_lnas['gain']

    for i in range(0, len(afe_ids)):
        afe = request.afes.add()
        afe.id = afe_ids[i]
        afe.attenuators = afe_attenuators[i]
        afe.v_bias = afe_vbiases[i]
        afe_adc = afe.adc
        afe_pga = afe.pga
        afe_lna = afe.lna
        afe_adc.resolution = afe_adcs_resolutions[i]
        afe_adc.output_format = afe_adcs_output_format[i]
        afe_adc.SB_first = afe_adcs_SB_first[i]
        afe_pga.lpf_cut_frequency = afe_pgas_lpf_cut_frequency[i]
        afe_pga.integrator_disable = afe_pgas_integrator_disable[i]
        afe_pga.gain = afe_pgas_gains[i]
        afe_lna.clamp = afe_lnas_clamp[i]
        afe_lna.integrator_disable = afe_lnas_integrator_disable[i]
        afe_lna.gain = afe_lnas_gains[i]

    #print(request)

    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.CONFIGURE_FE
    envelope.payload = request.SerializeToString()

    # Serialize
    serialized_request = envelope.SerializeToString()

    # Send via ZMQ
#     context = zmq.Context()
#     socket = context.socket(zmq.REQ)
#     socket.connect("tcp://193.206.157.36:9000")
#     socket.send(serialized_request)

#     # Receive response
#     response_bytes = socket.recv()
#     responseEnvelope = pb_high.ControlEnvelope()
#     responseEnvelope.ParseFromString(response_bytes)

#     print(responseEnvelope)

#     if(responseEnvelope.type == pb_high.CONFIGURE_FE):
#         response = pb_high.ConfigureResponse()
#         response.ParseFromString(responseEnvelope.payload)
#     elif(responseEnvelope.type == pb_high.CONFIGURE_CLKS):
#         response = pb_high.ConfigureCLKsResponse()
#         response.ParseFromString(responseEnvelope.payload)
#     # Print response
#     print("Success:", response.success)
#     print("Message:", response.message)
# socket.close()

# request = pb_low.cmd_writeAFEReg()
# request.afeBlock = 0
# request.regAddress = 51
# request.regValue = 0b11010
# envelope = pb_high.ControlEnvelope()
# envelope.type = pb_high.WRITE_AFE_REG
# envelope.payload = request.SerializeToString()

# # Send via ZMQ
# context = zmq.Context()
# socket = context.socket(zmq.REQ)
# socket.connect("tcp://193.206.157.36:9000")
# socket.send(envelope.SerializeToString())

# # Receive response
# response_bytes = socket.recv()
# responseEnvelope = pb_high.ControlEnvelope()
# responseEnvelope.ParseFromString(response_bytes)

# if responseEnvelope.type == pb_high.WRITE_AFE_REG:
#     response = pb_low.cmd_writeAFEReg_response()
#     response.ParseFromString(responseEnvelope.payload)
#     print("Success:", response.success)
#     print("Message:", response.message)
# socket.close()

# request = pb_low.cmd_writeAFEVGAIN()
# request.afeBlock = 0
# request.vgainValue = 1330
# envelope = pb_high.ControlEnvelope()
# envelope.type = pb_high.WRITE_AFE_VGAIN
# envelope.payload = request.SerializeToString()

# # Send via ZMQ
# context = zmq.Context()
# socket = context.socket(zmq.REQ)
# socket.connect("tcp://193.206.157.36:9000")
# socket.send(envelope.SerializeToString())

# # Receive response
# response_bytes = socket.recv()
# responseEnvelope = pb_high.ControlEnvelope()
# responseEnvelope.ParseFromString(response_bytes)

# if responseEnvelope.type == pb_high.WRITE_AFE_VGAIN:
#     response = pb_low.cmd_writeAFEReg_response()
#     response.ParseFromString(responseEnvelope.payload)
#     print("Success:", response.success)
#     print("Message:", response.message)
# socket.close()

# request = pb_low.cmd_writeVbiasControl()
# request.vBiasControlValue = 1300
# envelope = pb_high.ControlEnvelope()
# envelope.type = pb_high.WRITE_VBIAS_CONTROL
# envelope.payload = request.SerializeToString()

# # Send via ZMQ
# context = zmq.Context()
# socket = context.socket(zmq.REQ)
# socket.connect("tcp://193.206.157.36:9000")
# socket.send(envelope.SerializeToString())

# # Receive response
# response_bytes = socket.recv()
# responseEnvelope = pb_high.ControlEnvelope()
# responseEnvelope.ParseFromString(response_bytes)

# if responseEnvelope.type == pb_high.WRITE_VBIAS_CONTROL:
#     response = pb_low.cmd_writeVbiasControl_response()
#     response.ParseFromString(responseEnvelope.payload)
#     print("Success:", response.success)
#     print("Message:", response.message)
# socket.close()

request = pb_low.cmd_writeTrim_singleChannel()
request.trimChannel = 8
request.trimValue = 1500
request.trimGain = False
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.WRITE_TRIM_CH
envelope.payload = request.SerializeToString()

# Send via ZMQ
context = zmq.Context()
socket = context.socket(zmq.REQ)
socket.connect("tcp://193.206.157.36:9000")
socket.send(envelope.SerializeToString())

# Receive response
response_bytes = socket.recv()
responseEnvelope = pb_high.ControlEnvelope()
responseEnvelope.ParseFromString(response_bytes)

if responseEnvelope.type == pb_high.WRITE_TRIM_CH:
    response = pb_low.cmd_writeTrim_singleChannel_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)
socket.close()
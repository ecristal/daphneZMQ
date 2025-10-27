# tools/read_trigger_counters_v2.py
import zmq, struct
from daphneV3_low_level_confs_pb2 import ControlEnvelopeV2, ReadTriggerCountersRequest, MT2_READ_TRIGGER_COUNTERS_REQ, DIR_REQUEST

ctx = zmq.Context.instance()
s = ctx.socket(zmq.REQ)
s.connect("tcp://10.73.137.161:40001")

req = ControlEnvelopeV2()
req.version = 2
req.dir = DIR_REQUEST
req.type = MT2_READ_TRIGGER_COUNTERS_REQ
req.msg_id = 1000
req.task_id = 1000

payload = ReadTriggerCountersRequest()   # empty = all channels
req.payload = payload.SerializeToString()

s.send(req.SerializeToString())
resp = ControlEnvelopeV2()
resp.ParseFromString(s.recv())

from daphneV3_low_level_confs_pb2 import ReadTriggerCountersResponse
out = ReadTriggerCountersResponse()
out.ParseFromString(resp.payload)
for s in out.snapshots:
    print(f"ch {s.channel:2d} thr={s.threshold:4d} rec={s.record_count} bsy={s.busy_count} ful={s.full_count}")
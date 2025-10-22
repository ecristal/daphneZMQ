# /Users/marroyav/daphneZMQ/client/waveparse.py
import numpy as np

def parse_dump_response(resp):
    """
    Parse a DumpSpyBuffersResponse into a shaped int32 array.

    Returns
    -------
    y : np.ndarray
        Shape (W, K, N) with dtype=int32, where:
          W = numberOfWaveforms
          K = len(channelList)
          N = numberOfSamples
    meta : dict
        {'W': W, 'K': K, 'N': N, 'channels': list(resp.channelList), 'success': resp.success, 'message': resp.message}
    """
    K = len(resp.channelList)
    N = int(resp.numberOfSamples)
    W = int(resp.numberOfWaveforms) if hasattr(resp, "numberOfWaveforms") and resp.numberOfWaveforms else 1
    expected = W * K * N

    # Cast server's uint32 payload to signed int32 without copying twice
    u = np.asarray(resp.data, dtype=np.uint32)
    if u.size < expected:
        raise ValueError(f"Payload too short: {u.size} < expected {expected} (W={W}, K={K}, N={N})")
    y = u.view(np.int32)[:expected].reshape(W, K, N)

    return y, {"W": W, "K": K, "N": N, "channels": list(resp.channelList), "success": resp.success, "message": resp.message}

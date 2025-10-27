// ============================================================================
// Includes
// ============================================================================

// --- Standard Library ---
#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <exception>
#include <functional>
#include <iostream>
#include <mutex>
#include <optional>
#include <queue>
#include <sstream>
#include <thread>
#include <unordered_map>
#include <vector>
#include <numeric>   // for std::iota

// --- System / POSIX ---
#include <arpa/inet.h>

// --- Third-Party Libraries ---
#include <zmq.hpp>
#include "CLI/CLI.hpp"

// --- Project Headers ---
#include "Daphne.hpp"
#include "defines.hpp"
#include "FpgaRegDict.hpp"
#include "MezzCommon.hpp"
#include "daphneV3_high_level_confs.pb.h"
#include "daphneV3_low_level_confs.pb.h"
#include "reg.hpp"

// ============================================================================
// Namespace shortcuts
// ============================================================================
using namespace daphne;
using daphne::MessageType;
using daphne::ControlEnvelope;
using daphne::ConfigureRequest;
using daphne::ConfigureResponse;
using daphne::DumpSpyBuffersRequest;
using daphne::DumpSpyBuffersResponse;
using daphne::DumpSpyBuffersChunkRequest;
using daphne::DumpSpyBuffersChunkResponse;

// Commands
using daphne::cmd_alignAFEs;
using daphne::cmd_alignAFEs_response;
using daphne::cmd_doSoftwareTrigger;
using daphne::cmd_doSoftwareTrigger_response;
using daphne::cmd_writeAFEFunction;
using daphne::cmd_writeAFEFunction_response;
using daphne::cmd_writeAFEVGAIN;
using daphne::cmd_writeAFEVGAIN_response;
using daphne::cmd_writeAFEReg;
using daphne::cmd_writeAFEReg_response;
using daphne::cmd_writeAFEBiasSet;
using daphne::cmd_writeAFEBiasSet_response;
using daphne::cmd_writeAFEAttenuation;
using daphne::cmd_writeAFEAttenuation_response;
using daphne::cmd_writeTRIM_allChannels;
using daphne::cmd_writeTRIM_allChannels_response;
using daphne::cmd_writeTrim_allAFE;
using daphne::cmd_writeTrim_allAFE_response;
using daphne::cmd_writeTrim_singleChannel;
using daphne::cmd_writeTrim_singleChannel_response;
using daphne::cmd_writeOFFSET_allChannels;
using daphne::cmd_writeOFFSET_allChannels_response;
using daphne::cmd_writeOFFSET_allAFE;
using daphne::cmd_writeOFFSET_allAFE_response;
using daphne::cmd_writeOFFSET_singleChannel;
using daphne::cmd_writeOFFSET_singleChannel_response;
using daphne::cmd_writeVbiasControl;
using daphne::cmd_writeVbiasControl_response;
using daphne::cmd_readAFEReg;
using daphne::cmd_readAFEReg_response;
using daphne::cmd_readAFEVgain;
using daphne::cmd_readAFEVgain_response;
using daphne::cmd_readAFEBiasSet;
using daphne::cmd_readAFEBiasSet_response;
using daphne::cmd_readTrim_allChannels;
using daphne::cmd_readTrim_allChannels_response;
using daphne::cmd_readTrim_allAFE;
using daphne::cmd_readTrim_allAFE_response;
using daphne::cmd_readTrim_singleChannel;
using daphne::cmd_readTrim_singleChannel_response;
using daphne::cmd_readOffset_allChannels;
using daphne::cmd_readOffset_allChannels_response;
using daphne::cmd_readOffset_allAFE;
using daphne::cmd_readOffset_allAFE_response;
using daphne::cmd_readOffset_singleChannel;
using daphne::cmd_readOffset_singleChannel_response;
using daphne::cmd_readVbiasControl;
using daphne::cmd_readVbiasControl_response;
using daphne::cmd_readCurrentMonitor;
using daphne::cmd_readCurrentMonitor_response;
using daphne::cmd_readBiasVoltageMonitor;
using daphne::cmd_readBiasVoltageMonitor_response;





static std::string decode_clk_status(uint32_t v) {
  bool mmcm0 = (v & (1u<<0)) != 0;
  bool mmcm1 = (v & (1u<<1)) != 0;
  std::ostringstream os;
  os << "MMCM0:" << (mmcm0 ? "LOCKED" : "UNLOCKED")
     << " MMCM1:" << (mmcm1 ? "LOCKED" : "UNLOCKED");
  return os.str();
}


// ---- Trigger regs (base 0xA0010000) ---------------------------------
namespace trigregs {
    constexpr uint32_t PHYS_BASE   = 0xA0010000u;
    constexpr uint32_t STRIDE      = 0x20u; // 32 bytes per channel
    constexpr uint32_t OFF_THR     = 0x00u; // 32-bit (we mask 10b)
    constexpr uint32_t OFF_REC_LO  = 0x04u, OFF_REC_HI = 0x08u;
    constexpr uint32_t OFF_BSY_LO  = 0x0Cu, OFF_BSY_HI = 0x10u;
    constexpr uint32_t OFF_FUL_LO  = 0x14u, OFF_FUL_HI = 0x18u;
    constexpr uint32_t MASK_10BIT  = 0x3FFu;
  
    struct Reader {
      uint32_t     phys_base;
      FpgaRegDict  dict;
      reg          r;
  
      // Map the 0x8000_0000 BAR the same way FpgaReg does
      Reader(uint32_t base = PHYS_BASE)
        : phys_base(base),
          dict(),
          r(0x80000000ULL, 0x7FFFFFFFULL, dict) {}
  
      // ReadBitsFast expects a BYTE offset from 0x8000_0000
      inline uint32_t u32(uint32_t phys_addr) {
        uint32_t byte_off = phys_addr - 0x80000000u;
        return r.ReadBitsFast(byte_off, /*bitEndianess*/false);
      }
  
      inline uint64_t u64(uint32_t phys_lo, uint32_t phys_hi) {
        uint32_t lo = u32(phys_lo);
        uint32_t hi = u32(phys_hi);
        return (static_cast<uint64_t>(hi) << 32) | lo;
      }
  
      inline uint32_t base_ch(uint32_t ch) const { return phys_base + ch*STRIDE; }
  
      uint32_t read_thr(uint32_t ch) {
        auto v = u32(base_ch(ch) + OFF_THR);
        return (v & MASK_10BIT);
      }
      uint64_t read_rec(uint32_t ch) {
        auto b = base_ch(ch);
        return u64(b + OFF_REC_LO, b + OFF_REC_HI);
      }
      uint64_t read_bsy(uint32_t ch) {
        auto b = base_ch(ch);
        return u64(b + OFF_BSY_LO, b + OFF_BSY_HI);
      }
      uint64_t read_ful(uint32_t ch) {
        auto b = base_ch(ch);
        return u64(b + OFF_FUL_LO, b + OFF_FUL_HI);
      }
    };
  }

// Small RAII for mapped register access (we reuse your reg + FpgaRegDict)
struct EpRegs {
  FpgaRegDict dict;
  reg r;
  EpRegs() : dict(), r(/*BaseAddr*/0, /*MemLen*/0x200000, dict) {}
};

static bool set_clock_source_and_mmcm_reset(bool use_endpoint_clk,
                                            bool pulse_mmcm1_reset,
                                            std::string& msg,
                                            int timeout_ms=500)
{
  EpRegs ep;
  // CLOCK_SOURCE bit: 0=local, 1=endpoint
  uint32_t clk_src = use_endpoint_clk ? 1u : 0u;

  // Select clock source
  ep.r.WriteBits("endpointClockControl", "CLOCK_SOURCE", clk_src);

  // Optional MMCM1 reset pulse
  if (pulse_mmcm1_reset) {
    ep.r.WriteBits("endpointClockControl", "MMCM_RESET", 1);
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
    ep.r.WriteBits("endpointClockControl", "MMCM_RESET", 0);
  }

  // Wait for locks (best-effort)
  auto t0 = std::chrono::steady_clock::now();
  while (true) {
    uint32_t s = ep.r.ReadRegister("endpointClockStatus");
    if ((s & 0x3u) == 0x3u) { // both bits 0..1 set
      msg += "Clock status: " + decode_clk_status(s) + "\n";
      return true;
    }
    if (std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - t0).count() > timeout_ms) {
      msg += "Clock status (timeout): " + decode_clk_status(ep.r.ReadRegister("endpointClockStatus")) + "\n";
      return false;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
}

// Set endpoint 16-bit address and pulse EP reset
static bool set_endpoint_addr_and_reset(uint16_t ep_addr,
                                        bool pulse_ep_reset,
                                        std::string& msg,
                                        int timeout_ms=800)
{
  EpRegs ep;
  // Program address
  ep.r.WriteBits("endpointControl","ADDRESS", ep_addr);

  if (pulse_ep_reset) {
    ep.r.WriteBits("endpointControl","RESET", 1);
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
    ep.r.WriteBits("endpointControl","RESET", 0);
  }

  // Wait for endpoint state READY (FSM_STATUS == 8) and TIMESTAMP_OK (bit4)
  auto t0 = std::chrono::steady_clock::now();
  while (true) {
    uint32_t s = ep.r.ReadRegister("endpointStatus");
    uint32_t fsm = (s & 0xF);
    bool ts_ok = (s & (1u<<4)) != 0;
    if (fsm == 8 && ts_ok) {
      std::ostringstream os;
      os << "Endpoint READY; status=0x" << std::hex << s;
      msg += os.str() + "\n";
      return true;
    }
    if (std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - t0).count() > timeout_ms) {
      std::ostringstream os;
      os << "Endpoint not ready (timeout); status=0x" << std::hex << s;
      msg += os.str() + "\n";
      return false;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
}
// ---- extra V2 forward declarations (auto-inserted) ----
namespace daphne {
  struct cmd_writeOFFSET_singleChannel;        struct cmd_writeOFFSET_singleChannel_response;
  struct cmd_writeAFEVGAIN;                    struct cmd_writeAFEVGAIN_response;
  struct cmd_doAFEReset;                       struct cmd_doAFEReset_response;
  struct cmd_setAFEPowerState;                 struct cmd_setAFEPowerState_response;
}

// Implemented below in this file:
bool writeChannelOffset(const daphne::cmd_writeOFFSET_singleChannel &request,
                        Daphne &daphne, std::string &response_str, uint32_t &returned_value);

bool writeAFEVgain(const daphne::cmd_writeAFEVGAIN &request,
                   Daphne &daphne, std::string &response_str, uint32_t &returned_value);

bool doAFEReset(const daphne::cmd_doAFEReset &request,
                daphne::cmd_doAFEReset_response &response,
                Daphne &daphne, std::string &response_str);

bool setAFEPowerState(const daphne::cmd_setAFEPowerState &request,
                      daphne::cmd_setAFEPowerState_response &response,
                      Daphne &daphne, std::string &response_str);

// ---- V2 forward declarations (auto-inserted) ----
namespace daphne {
  struct ConfigureRequest;          struct ConfigureResponse;
  struct DumpSpyBuffersRequest;     struct DumpSpyBuffersResponse;
  struct DumpSpyBuffersChunkRequest;
  struct cmd_alignAFEs;             struct cmd_alignAFEs_response;
  struct cmd_writeAFEFunction;      struct cmd_writeAFEFunction_response;
  class  ControlEnvelopeV2;
}

// Implemented below in this file:
bool configureDaphne(const daphne::ConfigureRequest &requested_cfg,
                     Daphne &daphne, std::string &response_str);

bool alignAFE(const daphne::cmd_alignAFEs &request,
              daphne::cmd_alignAFEs_response &response,
              Daphne &daphne, std::string &response_str);

bool writeAFEFunction(const daphne::cmd_writeAFEFunction &request,
                      daphne::cmd_writeAFEFunction_response &response,
                      Daphne &daphne, std::string &response_str);

bool dumpSpybuffer(const daphne::DumpSpyBuffersRequest &request,
                   daphne::DumpSpyBuffersResponse &response,
                   Daphne &daphne, std::string &response_str);

// V2 chunking helper (declared here; its body is below)
static void dumpSpyBufferChunkV2(const daphne::DumpSpyBuffersChunkRequest &request,
                                 const daphne::ControlEnvelopeV2 &v2req,
                                 Daphne &daphne,
                                 zmq::socket_t &router,
                                 const zmq::message_t &client_id);


// Signature each handler will implement:
//   bool handler(const bytes& in, std::string& out_payload, Daphne& daphne, std::string& err)
using V2Handler = std::function<bool(const std::string&, std::string&, Daphne&, std::string&)>;

static std::unordered_map<daphne::MessageTypeV2, V2Handler> g_v2_handlers;



// ---------- V2 helpers (CONFIGURE_FE only) ----------
static inline uint64_t now_ns() {
  using namespace std::chrono;
  return duration_cast<std::chrono::nanoseconds>(
           std::chrono::steady_clock::now().time_since_epoch()
         ).count();

}

static inline bool parse_v2(const void* data, int size, daphne::ControlEnvelopeV2& out) {
  return out.ParseFromArray(data, size);
}

static inline daphne::ControlEnvelopeV2 make_v2_response_for_configure(
    const daphne::ControlEnvelopeV2& req_env,
    const daphne::ConfigureResponse& resp_msg)
{
  daphne::ControlEnvelopeV2 out;
  out.set_version(2);
  out.set_dir(daphne::DIR_RESPONSE);
  out.set_type(daphne::MT2_CONFIGURE_FE_RESP);
  out.set_task_id(req_env.task_id());
  out.set_correl_id(req_env.msg_id());
  out.set_msg_id(req_env.msg_id() + 1);
  out.set_timestamp_ns(now_ns());

  std::string payload;
  resp_msg.SerializeToString(&payload);
  out.set_payload(std::move(payload));
  return out;
}



static void init_v2_handlers() {
  using namespace daphne;
    // Monitoring trigger counters
  g_v2_handlers[daphne::MT2_READ_TRIGGER_COUNTERS_REQ] =
  [](const std::string& in, std::string& out, Daphne& /*d*/, std::string& err) -> bool {
    daphne::ReadTriggerCountersRequest req;
    daphne::ReadTriggerCountersResponse resp;

    if (!req.ParseFromString(in)) {
      err = "Bad ReadTriggerCountersRequest";
      resp.set_success(false);
      resp.set_message(err);
      out.resize(resp.ByteSizeLong());
      resp.SerializeToArray(out.data(), (int)out.size());
      return false;
    }

    // Channel list: default all
    std::vector<uint32_t> chs;
    if (req.channels_size() == 0) {
      chs.resize(40); std::iota(chs.begin(), chs.end(), 0);
    } else {
      chs.assign(req.channels().begin(), req.channels().end());
    }

    // (Optional) override base for debugging
    uint32_t base = (req.base_addr() != 0) ? req.base_addr() : trigregs::PHYS_BASE;
    if (base != trigregs::PHYS_BASE) {
      // accept override by shadowing PHYS_BASE via local arithmetic
      // we just add (base - trigregs::PHYS_BASE) when computing addresses
    }

    // Read
    try {
        trigregs::Reader rd(base);
      for (auto ch : chs) {
        if (ch >= 40) continue;
        uint32_t thr = rd.read_thr(ch);
        uint64_t rc  = rd.read_rec(ch);
        uint64_t bc  = rd.read_bsy(ch);
        uint64_t fc  = rd.read_ful(ch);

        auto* snap = resp.add_snapshots();
        snap->set_channel(ch);
        snap->set_threshold(thr);
        snap->set_record_count(rc);
        snap->set_busy_count(bc);
        snap->set_full_count(fc);
      }
      resp.set_success(true);
      resp.set_message("OK");
    } catch (const std::exception& e) {
      resp.set_success(false);
      resp.set_message(std::string("Exception: ") + e.what());
    }

    out.resize(resp.ByteSizeLong());
    resp.SerializeToArray(out.data(), (int)out.size());
    return resp.success();
  };
  // --- added: READ_TEST_REG (V2) ---
  g_v2_handlers[daphne::MT2_READ_TEST_REG_REQ] =
    [](const std::string& /*in*/, std::string& out, Daphne& /*d*/, std::string& /*err*/)->bool {
      daphne::TestRegResponse resp;
      resp.set_value(0xDEADBEEF);
      resp.set_message("ok");
      out.resize(resp.ByteSizeLong());
      resp.SerializeToArray(out.data(), static_cast<int>(out.size()));
      return true;
    };
  // CONFIGURE_FE
  g_v2_handlers[MT2_CONFIGURE_FE_REQ] =
    [](const std::string& in, std::string& out, Daphne& d, std::string& err) -> bool {
      ConfigureRequest req; ConfigureResponse resp;
      if (!req.ParseFromString(in)) { err = "Bad ConfigureRequest"; return false; }
      std::string msg; bool ok = configureDaphne(req, d, msg);
      if (ok) {
        cmd_alignAFEs a_req; cmd_alignAFEs_response a_resp; std::string align_msg;
        bool ok_align = alignAFE(a_req, a_resp, d, align_msg);
        msg += "\n\n[ALIGN_AFE]\n" + align_msg;
        ok = ok && ok_align;
      }
      resp.set_success(ok); resp.set_message(std::move(msg));
      out.resize(resp.ByteSizeLong());
      resp.SerializeToArray(out.data(), static_cast<int>(out.size()));
      return true;
    };

  // WRITE_AFE_FUNCTION (example low-level)
  g_v2_handlers[MT2_WRITE_AFE_FUNCTION_REQ] =
    [](const std::string& in, std::string& out, Daphne& d, std::string& err) -> bool {
      cmd_writeAFEFunction req; cmd_writeAFEFunction_response resp;
      if (!req.ParseFromString(in)) { err = "Bad cmd_writeAFEFunction"; return false; }
      std::string msg; bool ok = writeAFEFunction(req, resp, d, msg);
      resp.set_success(ok); resp.set_message(msg);
      out.resize(resp.ByteSizeLong());
      resp.SerializeToArray(out.data(), static_cast<int>(out.size()));
      return true;
    };

  // DUMP_SPYBUFFER (single-shot variant)
  g_v2_handlers[MT2_DUMP_SPYBUFFER_REQ] =
    [](const std::string& in, std::string& out, Daphne& d, std::string& err) -> bool {
      DumpSpyBuffersRequest req; DumpSpyBuffersResponse resp;
      if (!req.ParseFromString(in)) { err = "Bad DumpSpyBuffersRequest"; return false; }
      std::string msg; bool ok = dumpSpybuffer(req, resp, d, msg);
      resp.set_success(ok); resp.set_message(msg);
      out.resize(resp.ByteSizeLong());
      resp.SerializeToArray(out.data(), static_cast<int>(out.size()));
      return true;
    };

  // TODO: add the rest in the same pattern:
  // --- added: OFFSET(single channel) ---
  g_v2_handlers[daphne::MT2_WRITE_OFFSET_CH_REQ] =
    [](const std::string& in, std::string& out, Daphne& d, std::string& err)->bool {
      daphne::cmd_writeOFFSET_singleChannel req; daphne::cmd_writeOFFSET_singleChannel_response resp;
      if (!req.ParseFromString(in)) { err="Bad cmd_writeOFFSET_singleChannel"; return false; }
      std::string msg; uint32_t rb=0; bool ok = writeChannelOffset(req, d, msg, rb);
      resp.set_success(ok); resp.set_message(msg);
      resp.set_offsetchannel(req.offsetchannel()); resp.set_offsetvalue(rb); resp.set_offsetgain(req.offsetgain());
      out.resize(resp.ByteSizeLong()); resp.SerializeToArray(out.data(), static_cast<int>(out.size()));
      return true;
    };

  // --- added: AFE VGAIN ---
  g_v2_handlers[daphne::MT2_WRITE_AFE_VGAIN_REQ] =
    [](const std::string& in, std::string& out, Daphne& d, std::string& err)->bool {
      daphne::cmd_writeAFEVGAIN req; daphne::cmd_writeAFEVGAIN_response resp;
      if (!req.ParseFromString(in)) { err="Bad cmd_writeAFEVGAIN"; return false; }
      std::string msg; uint32_t rb=0; bool ok = writeAFEVgain(req, d, msg, rb);
      resp.set_success(ok); resp.set_message(msg); resp.set_afeblock(req.afeblock()); resp.set_vgainvalue(rb);
      out.resize(resp.ByteSizeLong()); resp.SerializeToArray(out.data(), static_cast<int>(out.size()));
      return true;
    };

  // --- added: DO_AFE_RESET ---
  g_v2_handlers[daphne::MT2_DO_AFE_RESET_REQ] =
    [](const std::string& in, std::string& out, Daphne& d, std::string& err)->bool {
      daphne::cmd_doAFEReset req; daphne::cmd_doAFEReset_response resp;
      if (!req.ParseFromString(in)) { err="Bad cmd_doAFEReset"; return false; }
      std::string msg; bool ok = doAFEReset(req, resp, d, msg);
      resp.set_success(ok); resp.set_message(msg);
      out.resize(resp.ByteSizeLong()); resp.SerializeToArray(out.data(), static_cast<int>(out.size()));
      return true;
    };

  // --- added: SET_AFE_POWERSTATE ---
  g_v2_handlers[daphne::MT2_SET_AFE_POWERSTATE_REQ] =
    [](const std::string& in, std::string& out, Daphne& d, std::string& err)->bool {
      daphne::cmd_setAFEPowerState req; daphne::cmd_setAFEPowerState_response resp;
      if (!req.ParseFromString(in)) { err="Bad cmd_setAFEPowerState"; return false; }
      std::string msg; bool ok = setAFEPowerState(req, resp, d, msg);
      resp.set_success(ok); resp.set_message(msg);
      out.resize(resp.ByteSizeLong()); resp.SerializeToArray(out.data(), static_cast<int>(out.size()));
      return true;
    };

  // --- added: ALIGN_AFE (for -align_afes flag in your client) ---
  g_v2_handlers[daphne::MT2_ALIGN_AFE_REQ] =
    [](const std::string& in, std::string& out, Daphne& d, std::string& err)->bool {
            daphne::cmd_alignAFEs req; daphne::cmd_alignAFEs_response resp;
      if (!req.ParseFromString(in)) { err="Bad cmd_alignAFEs"; return false; }
      std::string msg; bool ok = alignAFE(req, resp, d, msg);
      // ensure the textual report is in resp.message as well
      resp.set_message(msg);
      resp.set_success(ok);
      out.resize(resp.ByteSizeLong());
      resp.SerializeToArray(out.data(), static_cast<int>(out.size()));
      return true;

    };
  //  - MT2_WRITE_AFE_REG_REQ           -> writeAFERegister
  //  - MT2_WRITE_AFE_VGAIN_REQ         -> writeAFEVgain
  //  - MT2_WRITE_AFE_BIAS_SET_REQ      -> writeAFEBiasVoltage
  //  - MT2_WRITE_TRIM_* / MT2_WRITE_OFFSET_* -> your trim/offset helpers
  //  - MT2_WRITE_VBIAS_CONTROL_REQ     -> writeBiasVoltageControl
  //  - MT2_WRITE_AFE_ATTENUATION_REQ   -> writeAFEAttenuation
  //  - MT2_ALIGN_AFE_REQ               -> alignAFE
  //  - MT2_SET_AFE_RESET_REQ / MT2_DO_AFE_RESET_REQ / MT2_SET_AFE_POWERSTATE_REQ
  //  - Read commands MT2_READ_*        -> your read helpers
  // CONFIGURE_CLKS (V2)
  g_v2_handlers[daphne::MT2_CONFIGURE_CLKS_REQ] =
    [](const std::string& in, std::string& out, Daphne&, std::string& err)->bool {
      daphne::ConfigureCLKsRequest req; daphne::ConfigureCLKsResponse resp;
      if (!req.ParseFromString(in)) { err="Bad ConfigureCLKsRequest"; return false; }

      std::string info;
      bool ok_clk = set_clock_source_and_mmcm_reset(
        req.ctrl_ep_clk(), req.reset_mmcm1(), info);
      bool ok_ep = set_endpoint_addr_and_reset(
        static_cast<uint16_t>(req.id()), req.reset_endpoint(), info);

      resp.set_success(ok_clk && ok_ep);
      resp.set_message(info);

      out.resize(resp.ByteSizeLong());
      resp.SerializeToArray(out.data(), static_cast<int>(out.size()));
      return true;
    };
}



template <typename payloadMsg> void fill_zmq_message(payloadMsg& payload_message, MessageType message_type, ControlEnvelope& response_envelope, zmq::message_t& zmq_response){
    std::string payload;
    payload.resize(payload_message.ByteSizeLong());
    payload_message.SerializeToArray(payload.data(), payload.size());
    response_envelope.set_type(message_type);
    response_envelope.set_payload(std::move(payload));

    size_t envelope_size = response_envelope.ByteSizeLong();
    zmq_response.rebuild(envelope_size);
    response_envelope.SerializeToArray(zmq_response.data(), envelope_size);

}

static void send_enveloped_over_router(zmq::socket_t &router, const zmq::message_t &client_id, const google::protobuf::Message &payload_msg, MessageType type) {
    // keep replies compatible with legacy clients.
    // ROUTER must send: [id][payload] (NO empty delimiter), so REQ receives a single frame.
    ControlEnvelope env;
    env.set_type(type);
    std::string payload;
    payload_msg.SerializeToString(&payload);
    env.set_payload(std::move(payload));


    std::string env_bytes;
    env.SerializeToString(&env_bytes);


    // multipart: [id][payload] — identity consumed by ROUTER; peer sees only [payload]
    router.send(zmq::buffer(client_id.data(), client_id.size()), zmq::send_flags::sndmore);
    router.send(zmq::buffer(env_bytes), zmq::send_flags::none);
}

static bool is_valid_ip(const std::string& s) {
    sockaddr_in  v4{};
    sockaddr_in6 v6{};
    return inet_pton(AF_INET, s.c_str(), &v4.sin_addr) == 1 ||
           inet_pton(AF_INET6, s.c_str(), &v6.sin6_addr) == 1;
}

// this tempalte class is a bounded queue that is used to 
// store waveforms in a thread-safe manner
// and pipeline them to send them in chuncks
template <class T>
class BoundedQueue {
private:
    std::mutex mutex_;
    std::condition_variable cv_not_empty_, cv_not_full_;
    size_t capacity;
    std::queue<T> queue_;
    bool closed_ = false;
public:
    explicit BoundedQueue(size_t capacity) : capacity(capacity){}

    void push(T item){
        std::unique_lock<std::mutex> lk(mutex_);
        cv_not_full_.wait(lk, [&]{
            return (queue_.size() < (capacity)) || closed_;
        });
        if (closed_) return;
        queue_.push(std::move(item));
        cv_not_empty_.notify_one();
    }

    bool pop(T& item){
        std::unique_lock<std::mutex> lk(mutex_);
        cv_not_empty_.wait(lk, [&]{
            return !queue_.empty() || closed_;
        });
        if (closed_ && queue_.empty()) return false;
        item = std::move(queue_.front());
        queue_.pop();
        cv_not_full_.notify_one();
        return true;
    }

    void close() {
        std::lock_guard<std::mutex> lk(mutex_);
        closed_ = true;
        cv_not_empty_.notify_all();
        cv_not_full_.notify_all();
    }
};

bool configureDaphne(const ConfigureRequest &requested_cfg, Daphne &daphne, std::string &response_str) {
    try {
        std::ostringstream out;

        // --- Reset + power on before writes (as you already did)
        daphne.getAfe()->doReset();
        daphne.getAfe()->setPowerState(1);

        // --- Per-channel TRIM & OFFSET with echoed lines like the client prints
        // (We keep TRIM too; set to whatever is in the request; echo both if you like.
        //  If you only want OFFSET lines, just comment out the TRIM echo.)
        for (const ChannelConfig &ch_config : requested_cfg.channels()) {
            const uint32_t ch = ch_config.id();
            if (ch > 39) throw std::invalid_argument("Channel out of range (0..39): " + std::to_string(ch));
            const uint32_t afe_board = ch / 8;
            const uint32_t afe_pl    = afe_definitions::AFE_board2PL_map.at(afe_board);
            const uint32_t idx       = ch % 8;

            // TRIM
            daphne.getDac()->setDacTrim(afe_pl, idx, ch_config.trim(), false, false);
            daphne.setChTrimDictValue(ch, ch_config.trim());
            const uint32_t trim_rb = daphne.getChTrimDictValue(ch);
            out << "Trim value written successfully for Channel " << ch
                << ". Trim value: " << ch_config.trim()
                << ". Returned value: " << trim_rb << ".\n";

            // OFFSET
            daphne.getDac()->setDacOffset(afe_pl, idx, ch_config.offset(), false, false);
            daphne.setChOffsetDictValue(ch, ch_config.offset());
            const uint32_t off_rb = daphne.getChOffsetDictValue(ch);
            out << "Offset value written successfully for Channel " << ch
                << ". Offset value: " << ch_config.offset()
                << ". Returned value: " << off_rb << ".\n";
        }

        // --- Bias control (from ConfigureRequest.biasctrl). We'll enable output (true).
        //     Mirrors the message format in writeBiasVoltageControl().
        {
            const uint32_t ctrl = requested_cfg.biasctrl();
            if (ctrl <= 4095) {
                uint32_t returnedControlValue = daphne.getDac()->setDacHvBias(ctrl, false, false);
                uint32_t returnedBiasEnable   = daphne.getDac()->setBiasEnable(true);
                daphne.setBiasControlDictValue(ctrl);
                out << "Bias Control value written successfully. Bias Control value: "
                    << ctrl << " and Enable: " << returnedBiasEnable
                    << " Returned value: " << returnedControlValue << ".\n";
            } else {
                out << "Warning: Bias Control value " << ctrl << " out of range (0..4095). Skipping.\n";
            }
        }

        // --- Per-AFE VGAIN/attenuators with the same mapping and echo format as WRITE_AFE_VGAIN
        for (const AFEConfig &afe_config : requested_cfg.afes()){
            const uint32_t afe_board = afe_config.id();                    // 0..4 (board)
            const uint32_t afe_pl    = afe_definitions::AFE_board2PL_map.at(afe_board);

            // Program attenuation/VGAIN DAC
            const uint32_t v = afe_config.attenuators();
            if (v > 4095) throw std::invalid_argument("VGAIN out of range for AFE " + std::to_string(afe_board));
            daphne.getDac()->setDacGain(afe_pl, v);
            daphne.setAfeAttenuationDictValue(afe_pl, v);
            const uint32_t v_rb = daphne.getAfeAttenuationDictValue(afe_pl);

            // Echo line identical in spirit to client
            out << "AFE VGAIN written successfully for AFE " << afe_board
                << ". VGAIN: " << v << ". Returned value: " << v_rb << ".\n";

            // --- ADC / PGA / LNA function writes (unchanged behavior + echo)
            uint32_t r = 0;
            r = daphne.getAfe()->setAFEFunction(afe_pl, "SERIALIZED_DATA_RATE", 1);
            out << "Function SERIALIZED_DATA_RATE in AFE " << afe_board << " configured correctly.\nReturned value: " << r << "\n";
            r = daphne.getAfe()->setAFEFunction(afe_pl, "ADC_OUTPUT_FORMAT", afe_config.adc().output_format() ? 1u : 0u);
            out << "Function ADC_OUTPUT_FORMAT in AFE " << afe_board << " configured correctly.\nReturned value: " << r << "\n";
            r = daphne.getAfe()->setAFEFunction(afe_pl, "LSB_MSB_FIRST", afe_config.adc().sb_first() ? 1u : 0u);
            out << "Function LSB_MSB_FIRST in AFE " << afe_board << " configured correctly.\nReturned value: " << r << "\n";

            r = daphne.getAfe()->setAFEFunction(afe_pl, "LPF_PROGRAMMABILITY", afe_config.pga().lpf_cut_frequency());
            out << "Function LPF_PROGRAMMABILITY in AFE " << afe_board << " configured correctly.\nReturned value: " << r << "\n";
            r = daphne.getAfe()->setAFEFunction(afe_pl, "PGA_INTEGRATOR_DISABLE", afe_config.pga().integrator_disable() ? 1u : 0u);
            out << "Function PGA_INTEGRATOR_DISABLE in AFE " << afe_board << " configured correctly.\nReturned value: " << r << "\n";
            // If you want to use cfg.pga().gain() mapping, plug it here; many runs use fixed code = 2
            r = daphne.getAfe()->setAFEFunction(afe_pl, "PGA_CLAMP_LEVEL", 2u);
            out << "Function PGA_CLAMP_LEVEL in AFE " << afe_board << " configured correctly.\nReturned value: " << r << "\n";
            r = daphne.getAfe()->setAFEFunction(afe_pl, "ACTIVE_TERMINATION_ENABLE", 0u);
            out << "Function ACTIVE_TERMINATION_ENABLE in AFE " << afe_board << " configured correctly.\nReturned value: " << r << "\n";

            r = daphne.getAfe()->setAFEFunction(afe_pl, "LNA_INPUT_CLAMP_SETTING", afe_config.lna().clamp());
            out << "Function LNA_INPUT_CLAMP_SETTING in AFE " << afe_board << " configured correctly.\nReturned value: " << r << "\n";
            r = daphne.getAfe()->setAFEFunction(afe_pl, "LNA_GAIN", afe_config.lna().gain());
            out << "Function LNA_GAIN in AFE " << afe_board << " configured correctly.\nReturned value: " << r << "\n";
            r = daphne.getAfe()->setAFEFunction(afe_pl, "LNA_INTEGRATOR_DISABLE", afe_config.lna().integrator_disable() ? 1u : 0u);
            out << "Function LNA_INTEGRATOR_DISABLE in AFE " << afe_board << " configured correctly.\nReturned value: " << r << "\n";
        }

        // Reinforce power ON (you already do this elsewhere too)
        daphne.getAfe()->setPowerState(1);

        response_str = out.str();
        return true;
    } catch (std::exception &e) {
        response_str = std::string("Caught Exception:\n") + e.what();
        return false;
    }
}


bool writeAFERegister(const cmd_writeAFEReg &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value) {
    try {
        uint32_t afeBlock = request.afeblock();
        afeBlock = afe_definitions::AFE_board2PL_map.at(afeBlock);
        uint32_t regAddr = request.regaddress();
        uint32_t regValue = request.regvalue();
        returned_value = daphne.getAfe()->setRegister(afeBlock, regAddr, regValue);
        response_str = "AFE Register " + std::to_string(regAddr) 
                       + " written with value " + std::to_string(regValue) 
                       + " for AFE " + std::to_string(afe_definitions::AFE_PL2board_map.at(afeBlock)) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
        daphne.setAfeRegDictValue(afeBlock, regAddr, returned_value);
    } catch (std::exception &e) {
        response_str = "Error writting AFE Register: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeAFEVgain(const cmd_writeAFEVGAIN &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value) {
    try {
        uint32_t afeBlock = request.afeblock();
        afeBlock = afe_definitions::AFE_board2PL_map.at(afeBlock);
        uint32_t vgain = request.vgainvalue();
        if(vgain > 4095) throw std::invalid_argument("The VGAIN value " + std::to_string(vgain) + " is out of range. Expected range 0-4095");
        daphne.getDac()->setDacGain(afeBlock, vgain);
        daphne.setAfeAttenuationDictValue(afeBlock,vgain);
        returned_value = daphne.getAfeAttenuationDictValue(afeBlock);
        response_str = "AFE VGAIN written successfully for AFE " + std::to_string(afe_definitions::AFE_PL2board_map.at(afeBlock)) 
                       + ". VGAIN: " + std::to_string(vgain) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
    } catch (std::exception &e) {
        response_str = "Error writting AFE VGAIN: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeAFEAttenuation(const cmd_writeAFEAttenuation &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value) {
    try {
        uint32_t afeBlock = request.afeblock();
        afeBlock = afe_definitions::AFE_board2PL_map.at(afeBlock);
        uint32_t attenuation = request.attenuation();
        if(attenuation > 4095) throw std::invalid_argument("The attenuation value " + std::to_string(attenuation) + " is out of range. Range 0-4095");
        daphne.getDac()->setDacGain(afeBlock, attenuation);
        daphne.setAfeAttenuationDictValue(afeBlock,attenuation);
        returned_value = daphne.getAfeAttenuationDictValue(afeBlock);
        response_str = "AFE Attenuation written successfully for AFE " 
                       + std::to_string(afe_definitions::AFE_PL2board_map.at(afeBlock)) 
                       + ". Attenuation: " + std::to_string(attenuation) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
    } catch (std::exception &e) {
        response_str = "Error writting AFE Attenuation: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeAFEBiasVoltage(const cmd_writeAFEBiasSet &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value){
    try {
        uint32_t afeBlock = request.afeblock();
        afeBlock = afe_definitions::AFE_board2PL_map.at(afeBlock);
        uint32_t biasValue = request.biasvalue();
        if(biasValue > 4095) throw std::invalid_argument("The BIAS value " + std::to_string(biasValue) + " is out of range. Range 0-4095");
        daphne.getDac()->setDacBias(afeBlock, biasValue);
        daphne.setBiasVoltageDictValue(afeBlock, biasValue);
        returned_value = daphne.getBiasVoltageDictValue(afeBlock);
        response_str = "AFE bias value written successfully for AFE " 
                       + std::to_string(afe_definitions::AFE_PL2board_map.at(afeBlock)) 
                       + ". Bias value: " + std::to_string(biasValue) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
    } catch (std::exception &e) {
        response_str = "Error writting AFE Bias value: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeChannelTrim(const cmd_writeTrim_singleChannel &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value){
    try {
        uint32_t trimCh = request.trimchannel();
        uint32_t trimValue = request.trimvalue();
        uint32_t trimGain = request.trimgain();
        if(trimValue > 4095) throw std::invalid_argument("The Trim value " + std::to_string(trimValue) + " is out of range. Range 0-4095");
        if(trimCh > 39) throw std::invalid_argument("The Channel value " + std::to_string(trimCh) + " is out of range. Range 0-39");
        uint32_t afeBlock = afe_definitions::AFE_board2PL_map.at(trimCh / 8);
        daphne.getDac()->setDacTrim(afeBlock, trimCh % 8, trimValue, trimGain, false);
        daphne.setChTrimDictValue(trimCh, trimValue);
        returned_value = daphne.getChTrimDictValue(trimCh);
        response_str = "Trim value written successfully for Channel " + std::to_string(trimCh) + ". Trim value: " + std::to_string(trimValue) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
    } catch (std::exception &e) {
        response_str = "Error writting Channel Trim value: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeChannelOffset(const cmd_writeOFFSET_singleChannel &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value){
    try {
        uint32_t offsetCh = request.offsetchannel();
        uint32_t offsetValue = request.offsetvalue();
        uint32_t offsetGain = request.offsetgain();
        if(offsetValue > 4095) throw std::invalid_argument("The Offset value " + std::to_string(offsetValue) + " is out of range. Range 0-4095");
        if(offsetCh > 39) throw std::invalid_argument("The Channel value " + std::to_string(offsetCh) + " is out of range. Range 0-39");
        uint32_t afeBlock = afe_definitions::AFE_board2PL_map.at(offsetCh / 8);
        daphne.getDac()->setDacOffset(afeBlock, offsetCh % 8, offsetValue, offsetGain, false);
        daphne.setChOffsetDictValue(offsetCh, offsetValue);
        returned_value = daphne.getChOffsetDictValue(offsetCh);
        response_str = "Offset value written successfully for Channel " + std::to_string(offsetCh) + ". Offset value: " + std::to_string(offsetValue) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
    } catch (std::exception &e) {
        response_str = "Error writting Channel Offset value: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeBiasVoltageControl(const cmd_writeVbiasControl &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value){
    try {
        uint32_t controlValue = request.vbiascontrolvalue();
        bool biasEnable = request.enable();
        if(controlValue > 4095) throw std::invalid_argument("The Bias Control value " + std::to_string(controlValue) + " is out of range. Range 0-4095");
        uint32_t returnedControlValue = daphne.getDac()->setDacHvBias(controlValue, false, false);
        uint32_t returnedBiasEnable = daphne.getDac()->setBiasEnable(biasEnable);
        daphne.setBiasControlDictValue(controlValue);
        returned_value = returnedControlValue;
        response_str = "Bias Control value written successfully. Bias Control value: " + std::to_string(controlValue)
                       + " and Enable: " + std::to_string(returnedBiasEnable);
        response_str += " Returned value: " + std::to_string(returnedControlValue) + ".";
    } catch (std::exception &e) {
        response_str = "Error writting Bias Control value: " + std::string(e.what());
        return false;
    }
    return true;
}

bool dumpSpybuffer(const DumpSpyBuffersRequest &request, DumpSpyBuffersResponse &response, Daphne &daphne, std::string &response_str){
    try {
        
        uint32_t numberOfSamples = request.numberofsamples();
        uint32_t numberOfWaveforms = request.numberofwaveforms();
        auto channelList = request.channellist();

        for(int i=0; i<channelList.size(); ++i){
            if(channelList[i] > 39) throw std::invalid_argument("The channel value " + std::to_string(channelList[i]) + " is out of range. Range 0-39");
        }

        bool softwareTrigger = request.softwaretrigger();
        if(numberOfSamples > 2048 || numberOfSamples < 1) throw std::invalid_argument("The number of samples value " + std::to_string(numberOfSamples) + " is out of range. Range 1-4096");
        
        auto* spyBuffer = daphne.getSpyBuffer();
        auto* frontEnd = daphne.getFrontEnd();

        response.mutable_data()->Resize(numberOfSamples*numberOfWaveforms*channelList.size(), 0);
        google::protobuf::RepeatedField<uint32_t>* data_field = response.mutable_data();
        uint32_t* data_ptr = data_field->mutable_data();
        
        //daphne.getSpyBuffer()->setCurrentMappedChannelIndex(channel);
        // Let's calculate how much does it take to exxecute
        // the software trigger
        //std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
        if (channelList.size() == 1) {
        // No parallel, process channel sequentially
        uint32_t channel = channelList[0];
        uint32_t afeBlock = afe_definitions::AFE_board2PL_map.at(channel / 8);
        uint32_t afe_channel = channel % 8;
        channel = afeBlock * 8 + afe_channel; // Map to PL channel index
        for (int j = 0; j < numberOfWaveforms; ++j) {
            if (softwareTrigger) frontEnd->doTrigger();
            uint32_t* waveform_start = data_ptr + numberOfSamples * j;
            spyBuffer->extractMappedDataBulkSIMD(waveform_start, numberOfSamples, channel);
        }
        } else {
            // Parallelize across channels for each waveform
            // First, we need to map the channels to their PL indices
            std::vector<uint32_t> mappedChannels;
            for (const auto& channel : channelList) {
                uint32_t afeBlock = afe_definitions::AFE_board2PL_map.at(channel / 8);
                uint32_t afe_channel = channel % 8;
                mappedChannels.push_back(afeBlock * 8 + afe_channel); // Map to PL channel index
            }
            for (int j = 0; j < numberOfWaveforms; ++j) {
                if (softwareTrigger) frontEnd->doTrigger();
                //#pragma omp parallel for
                for (int i = 0; i < mappedChannels.size(); ++i) {
                    uint32_t channel = mappedChannels[i];
                    uint32_t* waveform_start = data_ptr + numberOfSamples * (j * mappedChannels.size() + i);
                    spyBuffer->extractMappedDataBulkSIMD(waveform_start, numberOfSamples, channel);
                }
            }
        }
        //std::chrono::steady_clock::time_point end = std::chrono::steady_clock::now();
        //std::chrono::duration<double> elapsed = end - start;
        //std::cout << "Time taken to dump spybuffer: " << elapsed.count() << " seconds." << std::endl;
        auto* resp_channel_list = response.mutable_channellist();
        resp_channel_list->Clear(); // ensure it's empty
        resp_channel_list->Reserve(channelList.size()); // reserve space for speed (optional)
        for(int i = 0; i < channelList.size(); ++i){
            resp_channel_list->Add(channelList[i]);
        }
        
        response.set_numberofsamples(numberOfSamples);
        response.set_numberofwaveforms(numberOfWaveforms);
        //response_str = "Spybuffer channel " + std::to_string(channel) + " dumped correctly."
        //               + " Number of samples: " + std::to_string(numberOfSamples);
        response_str = "OK";
    } catch (std::exception &e) {
        response_str = "Error dumping spybuffer: " + std::string(e.what());
        return false;
    }
    return true;
}

// this function handles the unique dumpSpybuffer in chunk mode,
// i.e. a pipelined approach to send waveforms in chunks to avoid
// memory issues when sending large number of waveforms
// ---- unified spybuffer chunk producer/consumer ----
static void for_each_spybuffer_chunk(
    const daphne::DumpSpyBuffersChunkRequest &request,
    Daphne &daphne,
    const std::function<void(const daphne::DumpSpyBuffersChunkResponse&)>& on_chunk)
{
    using namespace daphne;

    const auto &channelList    = request.channellist();
    uint32_t numberOfSamples   = request.numberofsamples();
    uint32_t numberOfWaveforms = request.numberofwaveforms();
    bool     softwareTrigger   = request.softwaretrigger();
    std::string requestId      = request.requestid();
    uint32_t chunkSize         = request.chunksize();

    if (channelList.empty())                           throw std::invalid_argument("Channel list is empty.");
    if (numberOfSamples == 0 || numberOfSamples > 2048) throw std::invalid_argument("Invalid numberOfSamples");
    if (numberOfWaveforms == 0)                        throw std::invalid_argument("Invalid numberOfWaveforms");
    if (chunkSize == 0 || chunkSize > 1024)            throw std::invalid_argument("Invalid chunkSize");

    for (int i=0; i<channelList.size(); ++i)
        if (channelList[i] > 39) throw std::invalid_argument("Channel out of range (0..39)");

    // Map requested channels to PL indices
    std::vector<uint32_t> mappedChannels;
    mappedChannels.reserve(channelList.size());
    for (auto ch : channelList) {
        uint32_t afeBlock  = afe_definitions::AFE_board2PL_map.at(ch / 8);
        uint32_t afe_chan  = ch % 8;
        mappedChannels.push_back(afeBlock * 8 + afe_chan);
    }

    struct ChunkPacket {
        uint32_t seq;
        uint32_t wf_start;
        uint32_t wf_count;
        std::vector<uint32_t> data;
    };

    BoundedQueue<ChunkPacket> queue(2);
    std::atomic<bool> had_error(false);

    auto* spyBuffer = daphne.getSpyBuffer();
    auto* frontEnd  = daphne.getFrontEnd();

    // Producer
    std::thread producer([&]{
        try {
            uint32_t seq = 0;
            for (uint32_t wf_start = 0; wf_start < numberOfWaveforms; wf_start += chunkSize) {
                uint32_t wf_count = std::min(chunkSize, numberOfWaveforms - wf_start);
                ChunkPacket p;
                p.seq      = seq++;
                p.wf_start = wf_start;
                p.wf_count = wf_count;
                p.data.resize(wf_count * numberOfSamples * mappedChannels.size(), 0);

                for (uint32_t i = 0; i < wf_count; ++i) {
                    if (softwareTrigger) frontEnd->doTrigger();
                    for (size_t j = 0; j < mappedChannels.size(); ++j) {
                        uint32_t chan = mappedChannels[j];
                        uint32_t* dst = p.data.data() + (i * mappedChannels.size() + j) * numberOfSamples;
                        spyBuffer->extractMappedDataBulkSIMD(dst, numberOfSamples, chan);
                    }
                }
                queue.push(std::move(p));
            }
        } catch (...) {
            had_error = true;
        }
        queue.close();
    });

    // Consumer -> convert to proto and call on_chunk
    ChunkPacket pack;
    while (queue.pop(pack)) {
        DumpSpyBuffersChunkResponse resp;
        resp.set_success(!had_error);
        resp.set_requestid(requestId);
        resp.set_chunkseq(pack.seq);
        resp.set_isfinal((pack.wf_start + pack.wf_count) >= numberOfWaveforms);
        resp.set_waveformstart(pack.wf_start);
        resp.set_waveformcount(pack.wf_count);
        resp.set_requesttotalwaveforms(numberOfWaveforms);
        resp.set_numberofsamples(numberOfSamples);

        auto *out_chl = resp.mutable_channellist();
        out_chl->Clear(); out_chl->Reserve(channelList.size());
        for (auto ch : channelList) out_chl->Add(ch);

        auto *out_data = resp.mutable_data();
        out_data->Add(pack.data.data(), pack.data.data() + pack.data.size());

        on_chunk(resp);
    }

    if (producer.joinable()) producer.join();
}
static void dumpSpyBufferChunk(const DumpSpyBuffersChunkRequest &request, Daphne &daphne, zmq::socket_t &router, const zmq::message_t &client_id){
for_each_spybuffer_chunk(request, daphne, [&](const daphne::DumpSpyBuffersChunkResponse& resp){
        send_enveloped_over_router(router, client_id, resp, daphne::DUMP_SPYBUFFER_CHUNK);
    });
    return;
}

// ==== V2 chunked sender: same logic as dumpSpyBufferChunk, but sends EnvelopeV2 ====
static void dumpSpyBufferChunkV2(const daphne::DumpSpyBuffersChunkRequest &request,
                                 const daphne::ControlEnvelopeV2 &v2req,
                                 Daphne &daphne,
                                 zmq::socket_t &router,
                                 const zmq::message_t &client_id)
{
for_each_spybuffer_chunk(request, daphne, [&](const daphne::DumpSpyBuffersChunkResponse& resp){
        std::string pay; resp.SerializeToString(&pay);
        auto v2out = mezz::make_v2_resp(v2req, daphne::MT2_DUMP_SPYBUFFER_CHUNK_RESP, pay);
        std::string bytes; v2out.SerializeToString(&bytes);
        router.send(zmq::buffer(client_id.data(), client_id.size()), zmq::send_flags::sndmore);
        router.send(zmq::buffer(bytes), zmq::send_flags::none);
    });
    return;
}


bool alignAFE(const cmd_alignAFEs &request, cmd_alignAFEs_response &response, Daphne &daphne, std::string &response_str){
    try {
        uint32_t afeNum = 5;
        std::vector<uint32_t> delay = {0, 0, 0, 0, 0};
        std::vector<uint32_t> bitslip = {0, 0, 0, 0, 0};
        std::string response_str_ = "";
        //if(afeBlock > 4) throw std::invalid_argument("The AFE value " + std::to_string(afeBlock) + " is out of range. Range 0-4");
        daphne.getFrontEnd()->resetDelayCtrlValues();
        daphne.getFrontEnd()->doResetDelayCtrl();
        daphne.getFrontEnd()->doResetSerDesCtrl();
        daphne.getFrontEnd()->setEnableDelayVtc(0);
        for(int afeBlock = 0; afeBlock < afeNum; afeBlock++){
            daphne.setBestDelay(afeBlock);
            daphne.setBestBitslip(afeBlock);
        }
        for(int afeBlock = 0; afeBlock < afeNum; afeBlock++){
            delay[afeBlock] = daphne.getFrontEnd()->getDelay(afeBlock);
            bitslip[afeBlock] = daphne.getFrontEnd()->getBitslip(afeBlock);
            response_str_ = response_str_ +
                            "AFE_" + std::to_string(afeBlock) + "\n" 
                            "DELAY: " + std::to_string(delay[afeBlock]) + "\n" + 
                            "BITSLIP: " + std::to_string(bitslip[afeBlock]) + "\n";
        }
        daphne.getFrontEnd()->setEnableDelayVtc(1);
        //response.set_delay(delay);
        //response.set_bitslip(bitslip);
        response_str = "AFEs alignAFE command executed correctly.\n" + response_str_;
    } catch (std::exception &e) {
        response_str = "Error aligning AFE: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeAFEFunction(const cmd_writeAFEFunction &request, cmd_writeAFEFunction_response &response, Daphne &daphne, std::string &response_str){
    try {
        uint32_t afeBlock = request.afeblock();
        afeBlock = afe_definitions::AFE_board2PL_map.at(afeBlock);
        if(afeBlock > 4) throw std::invalid_argument("The AFE value " + std::to_string(afeBlock) + " is out of range. Range 0-4");
        std::string afeFunctionName = request.function();
        uint32_t confValue = request.configvalue();
        uint32_t returnedConfValue = daphne.getAfe()->setAFEFunction(afeBlock, afeFunctionName, confValue);
        response.set_function(afeFunctionName);
        response.set_configvalue(returnedConfValue);
        response.set_afeblock(afeBlock);
        response_str = "Function " + afeFunctionName + " in AFE " + std::to_string(afe_definitions::AFE_PL2board_map.at(afeBlock)) + " configured correctly.\n"
                       + "Returned value: " + std::to_string(returnedConfValue);
    } catch (std::exception &e) {
        response_str = "Error writting AFE function: " + std::string(e.what());
        return false;
    }
    return true;
}

bool setAFEReset(const cmd_setAFEReset &request, cmd_setAFEReset_response &response, Daphne &daphne, std::string &response_str){
    try{
        bool resetValue = request.resetvalue();
        uint32_t returnedResetValue = daphne.getAfe()->setReset((uint32_t)resetValue);
        response.set_resetvalue(returnedResetValue);
        response_str = "AFEs reset register with value " + std::to_string(resetValue) + ".\n"
                     + "Returned value: " + std::to_string(returnedResetValue);
    }catch(std::exception &e){
        response_str = "Error reseting AFEs: " + std::string(e.what());
        return false;
    }
    return true;
}

bool doAFEReset(const cmd_doAFEReset &request, cmd_doAFEReset_response &response, Daphne &daphne, std::string &response_str){
    try{
        uint32_t returnedResetValue = daphne.getAfe()->doReset();
        response_str = "AFEs doreset command successful.\n";
    }catch(std::exception &e){
        response_str = "Error reseting AFEs: " + std::string(e.what());
        return false;
    }
    return true;
}

bool setAFEPowerState(const cmd_setAFEPowerState &request, cmd_setAFEPowerState_response &response, Daphne &daphne, std::string &response_str){
    try{
        bool powerStateValue = request.powerstate();
        uint32_t returnedPowerStateValue = daphne.getAfe()->setPowerState((uint32_t)powerStateValue);
        response.set_powerstate(returnedPowerStateValue);
        response_str = "AFEs powerstate register with value " + std::to_string(powerStateValue) + ".\n"
                     + "Returned value: " + std::to_string(returnedPowerStateValue);
    }catch(std::exception &e){
        response_str = "Error setting AFEs power state: " + std::string(e.what());
        return false;
    }
    return true;
}

bool doSoftwareTrigger(const cmd_doSoftwareTrigger &request, cmd_doSoftwareTrigger_response &response, Daphne &daphne, std::string &response_str){
    try{
        daphne.getFrontEnd()->doTrigger();
        response_str = "Software doSoftwareTrigger command successful.\n";
    }catch(std::exception &e){
        response_str = "Error reseting AFEs: " + std::string(e.what());
        return false;
    }
    return true;
}

void process_request(const std::string& request_str, zmq::message_t& zmq_response, Daphne &daphne) {
    // Identify the message type
    // Here the not equal to std::npos is used to check if the string contains the substring
    // so the issue is to see if it really contains the substring. 
    // Apparently it does not!!!
    ControlEnvelope request_envelope, response_envelope;

    if(!request_envelope.ParseFromString(request_str)){
        return;
    }

    switch(request_envelope.type()){
	case READ_TEST_REG: {
    daphne::TestRegRequest  cmd_request;
    daphne::TestRegResponse cmd_response;
    // empty payload is valid; ParseFromString optional
    cmd_response.set_value(0xDEADBEEF);
    cmd_response.set_message("ok");
    fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
    return;
}
        case CONFIGURE_CLKS: {
  ConfigureCLKsRequest cmd_request;
  ConfigureCLKsResponse cmd_response;
  if (cmd_request.ParseFromString(request_envelope.payload())) {
    std::string info;

    bool ok_clk = set_clock_source_and_mmcm_reset(
        cmd_request.ctrl_ep_clk(), cmd_request.reset_mmcm1(), info);

    bool ok_ep  = set_endpoint_addr_and_reset(
        static_cast<uint16_t>(cmd_request.id()),
        cmd_request.reset_endpoint(), info);

    cmd_response.set_success(ok_clk && ok_ep);
    cmd_response.set_message(info);
  } else {
    cmd_response.set_success(false);
    cmd_response.set_message("Payload not recognized");
  }
  fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
  return;
}
        case CONFIGURE_FE: {
            ConfigureRequest cmd_request;
            ConfigureResponse cmd_response;
            //std::cout << "The request is a ConfigureRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = configureDaphne(cmd_request, daphne, configure_message);
		      if (is_success) {
		          cmd_alignAFEs a_req;
		          cmd_alignAFEs_response a_resp;
		          std::string align_msg;
		          bool ok_align = alignAFE(a_req, a_resp, daphne, align_msg);
		          // Append the alignment report into the returned message
		          configure_message += "\n\n[ALIGN_AFE]\n" + align_msg;
		          is_success = is_success && ok_align;
		      }
		      
		      cmd_response.set_success(is_success);
		      cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_AFE_REG: {
            cmd_writeAFEReg cmd_request;
            cmd_writeAFEReg_response cmd_response;
            //std::cout << "The request is a WriteAfeRegRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeAFERegister(cmd_request, daphne, configure_message, returned_value);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
                cmd_response.set_afeblock(cmd_request.afeblock());
                cmd_response.set_regaddress(cmd_request.regaddress());
                cmd_response.set_regvalue(returned_value);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_AFE_VGAIN: {
            cmd_writeAFEVGAIN cmd_request;
            cmd_writeAFEVGAIN_response cmd_response;
            //std::cout << "The request is a WriteAfeVgainRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeAFEVgain(cmd_request, daphne, configure_message, returned_value);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
                cmd_response.set_afeblock(cmd_request.afeblock());
                cmd_response.set_vgainvalue(returned_value);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_AFE_BIAS_SET: {
            cmd_writeAFEBiasSet cmd_request;
            cmd_writeAFEBiasSet_response cmd_response;
            //std::cout << "The request is a WriteAfeBiasSetRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeAFEBiasVoltage(cmd_request, daphne, configure_message, returned_value);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
                cmd_response.set_afeblock(cmd_request.afeblock());
                cmd_response.set_biasvalue(returned_value);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_TRIM_ALL_CH: { // to be implemented
            cmd_writeTRIM_allChannels cmd_request;
            cmd_writeTRIM_allChannels_response cmd_response;
            //std::cout << "The request is a WriteTrimAllChannelsRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All channel trims written successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_TRIM_ALL_AFE: { // to be implemented
            cmd_writeTrim_allAFE cmd_request;
            cmd_writeTrim_allAFE_response cmd_response;
            //std::cout << "The request is a WriteTrimAllAfeRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All AFE trims written successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_TRIM_CH: { //Verified in DAPHNE V3
            cmd_writeTrim_singleChannel cmd_request;
            cmd_writeTrim_singleChannel_response cmd_response;
            //std::cout << "The request is a WriteTrimSingleChannelRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeChannelTrim(cmd_request, daphne, configure_message, returned_value);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
                cmd_response.set_trimchannel(cmd_request.trimchannel());
                cmd_response.set_trimvalue(returned_value);
                cmd_response.set_trimgain(cmd_request.trimgain());
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_OFFSET_ALL_CH: { // to be implemented
            cmd_writeOFFSET_allChannels cmd_request;
            cmd_writeOFFSET_allChannels_response cmd_response;
            //std::cout << "The request is a WriteOffsetAllChannelsRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All channel offsets written successfully");
                return;
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
                return;
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_OFFSET_ALL_AFE: { // to be implemented
            cmd_writeOFFSET_allAFE cmd_request;
            cmd_writeOFFSET_allAFE_response cmd_response;
            //std::cout << "The request is a WriteOffsetAllAfeRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All AFE offsets written successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
        }
        case WRITE_OFFSET_CH: { //Verified in DAPHNE V3
            cmd_writeOFFSET_singleChannel cmd_request;
            cmd_writeOFFSET_singleChannel_response cmd_response;
            //std::cout << "The request is a WriteOffsetSingleChannelRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeChannelOffset(cmd_request, daphne, configure_message, returned_value);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
                cmd_response.set_offsetchannel(cmd_request.offsetchannel());
                cmd_response.set_offsetvalue(returned_value);
                cmd_response.set_offsetgain(cmd_request.offsetgain());
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_VBIAS_CONTROL: {
            cmd_writeVbiasControl cmd_request;
            cmd_writeVbiasControl_response cmd_response;
            //std::cout << "The request is a WriteVbiasControlRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeBiasVoltageControl(cmd_request, daphne, configure_message, returned_value);
                cmd_response.set_vbiascontrolvalue(returned_value);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_AFE_REG: { // to be implemented
            cmd_readAFEReg cmd_request;
            cmd_readAFEReg_response cmd_response;
            //std::cout << "The request is a ReadAfeRegRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("AFE register read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_AFE_VGAIN: { // to be implemented
            cmd_readAFEVgain cmd_request;
            cmd_readAFEVgain_response cmd_response;
            //std::cout << "The request is a ReadAfeVgainRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("AFE VGAIN read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_AFE_BIAS_SET: { // to be implemented
            cmd_readAFEBiasSet cmd_request;
            cmd_readAFEBiasSet_response cmd_response;
            //std::cout << "The request is a ReadAfeBiasSetRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("AFE Bias Set read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_TRIM_ALL_CH: { // to be implemented
            cmd_readTrim_allChannels cmd_request;
            cmd_readTrim_allChannels_response cmd_response;
            //std::cout << "The request is a ReadTrimAllChannelsRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All channel trims read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_TRIM_ALL_AFE: { // to be implemented
            cmd_readTrim_allAFE cmd_request;
            cmd_readTrim_allAFE_response cmd_response;
            //std::cout << "The request is a ReadTrimAllAfeRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All AFE trims read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_TRIM_CH: { // to be implemented
            cmd_readTrim_singleChannel cmd_request;
            cmd_readTrim_singleChannel_response cmd_response;
            //std::cout << "The request is a ReadTrimSingleChannelRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("Single channel trim read successfully");
                return;
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_OFFSET_ALL_CH: { // to be implemented
            cmd_readOffset_allChannels cmd_request;
            cmd_readOffset_allChannels_response cmd_response;
            //std::cout << "The request is a ReadOffsetAllChannelsRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All channel offsets read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_OFFSET_ALL_AFE: { // to be implemented
            cmd_readOffset_allAFE cmd_request;
            cmd_readOffset_allAFE_response cmd_response;
            //std::cout << "The request is a ReadOffsetAllAfeRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All AFE offsets read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_OFFSET_CH: { // to be implemented
            cmd_readOffset_singleChannel cmd_request;
            cmd_readOffset_singleChannel_response cmd_response;
            //std::cout << "The request is a ReadOffsetSingleChannelRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("Single channel offset read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_VBIAS_CONTROL: { // to be implemented
            cmd_readVbiasControl cmd_request;
            cmd_readVbiasControl_response cmd_response;
            //std::cout << "The request is a ReadVbiasControlRequest" << std::endl;
            if(cmd_response.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("Vbias control read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_CURRENT_MONITOR: { // to be implemented
            cmd_readCurrentMonitor cmd_request;
            cmd_readCurrentMonitor_response cmd_response;
            //std::cout << "The request is a ReadCurrentMonitorRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("Current monitor read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_BIAS_VOLTAGE_MONITOR: { // to be implemented
            cmd_readBiasVoltageMonitor cmd_request;
            cmd_readBiasVoltageMonitor_response cmd_response;
            //std::cout << "The request is a ReadBiasVoltageMonitorRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("Bias voltage monitor read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case SET_AFE_RESET: {
            cmd_setAFEReset cmd_request;
            cmd_setAFEReset_response cmd_response;
            //std::cout << "The request is a SetAfeResetRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = setAFEReset(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case DO_AFE_RESET: {
            cmd_doAFEReset cmd_request;
            cmd_doAFEReset_response cmd_response;
            //std::cout << "The request is a DoAfeResetRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_succes = doAFEReset(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_succes);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case SET_AFE_POWERSTATE: { // to be implemented
            cmd_setAFEPowerState cmd_request;
            cmd_setAFEPowerState_response cmd_response;
            //std::cout << "The request is a SetAfePowerStateRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = setAFEPowerState(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }

        case DUMP_SPYBUFFER: {
            DumpSpyBuffersRequest cmd_request;
            DumpSpyBuffersResponse cmd_response;
            //std::cout << "The request is a DumpSpyBuffersRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = dumpSpybuffer(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }

        case ALIGN_AFE: {
            cmd_alignAFEs cmd_request;
            cmd_alignAFEs_response cmd_response;
            //std::cout << "The request is a cmd_alignAFEs" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = alignAFE(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }

        case WRITE_AFE_FUNCTION: {
            cmd_writeAFEFunction cmd_request;
            cmd_writeAFEFunction_response cmd_response;
            //std::cout << "The request is a cmd_writeAFEFunction" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = writeAFEFunction(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }

        case DO_SOFTWARE_TRIGGER: {
            cmd_doSoftwareTrigger cmd_request;
            cmd_doSoftwareTrigger_response cmd_response;
            //std::cout << "The request is a DoSoftwareTriggerRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = doSoftwareTrigger(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }

        default: {
            return;
        }
    }
}

static bool recv_multipart_compat(zmq::socket_t &sock, std::vector<zmq::message_t> &frames) {
    frames.clear();
    while (true) {
        zmq::message_t part;
        if (!sock.recv(part, zmq::recv_flags::none)) return false;
        frames.emplace_back(std::move(part));
        bool more = sock.get(zmq::sockopt::rcvmore);
        if (!more) break;
    }
    return true;
}

static void server_loop_router(zmq::context_t &ctx, const std::string &bind_endpoint, Daphne &daphne) {
    zmq::socket_t router(ctx, ZMQ_ROUTER);

    int sndhwm = 20000; 
    router.set(zmq::sockopt::sndhwm, sndhwm);
    int sndbuf = 4*1024*1024;  
    router.set(zmq::sockopt::sndbuf, sndbuf);
    int immediate = 1; 
    router.set(zmq::sockopt::immediate, immediate);
    router.bind(bind_endpoint);

    while (true) {
        
        std::vector<zmq::message_t> frames;
        if (!recv_multipart_compat(router, frames)) continue;
        if (frames.size() < 2) continue; 

        zmq::message_t &id = frames[0];
        
	zmq::message_t &payload = frames.back();
	

    // --- V2 transport gateway (handle V2 before legacy) ---
    static bool v2_inited = (init_v2_handlers(), true);
    (void)v2_inited;

    daphne::ControlEnvelopeV2 v2req;
    if (v2req.ParseFromArray(payload.data(), static_cast<int>(payload.size()))) {

      // --- Chunked streaming in V2 ---
      if (v2req.dir() == daphne::DIR_REQUEST &&
          v2req.type() == daphne::MT2_DUMP_SPYBUFFER_CHUNK_REQ) {

        daphne::DumpSpyBuffersChunkRequest creq;
        if (!creq.ParseFromString(v2req.payload())) {
          daphne::DumpSpyBuffersChunkResponse err;
          err.set_success(false); err.set_isfinal(true); err.set_message("Bad DumpSpyBuffersChunkRequest");
          std::string pay; err.SerializeToString(&pay);
          auto e = mezz::make_v2_resp(v2req, daphne::MT2_DUMP_SPYBUFFER_CHUNK_RESP, pay);
          std::string bytes; e.SerializeToString(&bytes);
          router.send(zmq::buffer(id.data(), id.size()), zmq::send_flags::sndmore);
          router.send(zmq::buffer(bytes), zmq::send_flags::none);
          continue;
        }

        // V2-wrapped streaming (see patch in section 2)
        dumpSpyBufferChunkV2(creq, v2req, daphne, router, id);
        continue;
      }

      // --- Single-reply handlers via registry ---
      auto it = g_v2_handlers.find(v2req.type());
      if (v2req.dir() == daphne::DIR_REQUEST && it != g_v2_handlers.end()) {
        std::string out_payload, err;
        bool ok = it->second(v2req.payload(), out_payload, daphne, err);

        if (!ok && out_payload.empty()) {
          daphne::DumpSpyBuffersChunkResponse tiny;
          tiny.set_success(false);
          tiny.set_message(err.empty() ? "Handler failed" : err);
          out_payload.resize(tiny.ByteSizeLong());
          tiny.SerializeToArray(out_payload.data(), static_cast<int>(out_payload.size()));
        }

        auto v2resp = mezz::make_v2_resp(v2req, mezz::resp_type(v2req.type()), out_payload);
        std::string bytes; v2resp.SerializeToString(&bytes);
        router.send(zmq::buffer(id.data(), id.size()), zmq::send_flags::sndmore);
        router.send(zmq::buffer(bytes), zmq::send_flags::none);
        continue; // don't hit legacy path
      }

      // Unknown V2 → fall through to legacy for now
    }
    // --- end V2 gateway ---

        ControlEnvelope req_env;
        if (!req_env.ParseFromArray(payload.data(), static_cast<int>(payload.size()))) {
            DumpSpyBuffersChunkResponse err; 
            err.set_success(false);
            err.set_message("Bad envelope");
            err.set_isfinal(true);
            send_enveloped_over_router(router, id, err, DUMP_SPYBUFFER_CHUNK);
            continue;
        }

        if (req_env.type() == DUMP_SPYBUFFER_CHUNK) {
            DumpSpyBuffersChunkRequest req;
            if (!req.ParseFromString(req_env.payload())) {
                DumpSpyBuffersChunkResponse err;
                err.set_success(false);
                err.set_message("Bad payload");
                err.set_isfinal(true);
                send_enveloped_over_router(router, id, err, DUMP_SPYBUFFER_CHUNK);
                continue;
            }
            dumpSpyBufferChunk(req, daphne, router, id);
            continue;
        }

        zmq::message_t one_reply;
        process_request(std::string(static_cast<char*>(payload.data()), payload.size()), one_reply, daphne);
        
        router.send(zmq::buffer(id.data(), id.size()), zmq::send_flags::sndmore);
        router.send(std::move(one_reply), zmq::send_flags::none);
        
    }
}

void I2C_2_monitorThread(Daphne &daphne){
    //auto start = std::chrono::high_resolution_clock::now();
    //daphne.getHDMezzDriver()->enableAfeBlock(4, true);
    //daphne.getHDMezzDriver()->configureHdMezzAfeBlock(4); //testing purposes
    while(true){
        try{
            if(!daphne.isI2C_2_device_configuring.load()){
                if(daphne.getHDMezzDriver()->isAfeBlockEnabled(4)){
                    daphne.HDMezz_5V_voltage_afe4.store(daphne.getHDMezzDriver()->readRailVoltage5V(4));
                    daphne.HDMezz_5V_current_afe4.store(daphne.getHDMezzDriver()->readRailCurrent5V(4));
                    daphne.HDMezz_3V3_voltage_afe4.store(daphne.getHDMezzDriver()->readRailVoltage3V3(4));
                    daphne.HDMezz_3V3_current_afe4.store(daphne.getHDMezzDriver()->readRailCurrent3V3(4));
                    daphne.HDMezz_5V_power_afe4.store(daphne.getHDMezzDriver()->readRailPower5V(4));
                    daphne.HDMezz_3V3_power_afe4.store(daphne.getHDMezzDriver()->readRailPower3V3(4));
                }

                if(daphne.getHDMezzDriver()->isAfeBlockEnabled(3)){
                    daphne.HDMezz_5V_voltage_afe3.store(daphne.getHDMezzDriver()->readRailVoltage5V(3));
                    daphne.HDMezz_5V_current_afe3.store(daphne.getHDMezzDriver()->readRailCurrent5V(3));
                    daphne.HDMezz_3V3_voltage_afe3.store(daphne.getHDMezzDriver()->readRailVoltage3V3(3));
                    daphne.HDMezz_3V3_current_afe3.store(daphne.getHDMezzDriver()->readRailCurrent3V3(3));
                    daphne.HDMezz_5V_power_afe3.store(daphne.getHDMezzDriver()->readRailPower5V(3));
                    daphne.HDMezz_3V3_power_afe3.store(daphne.getHDMezzDriver()->readRailPower3V3(3));
                }

                if(daphne.getHDMezzDriver()->isAfeBlockEnabled(2)){
                    daphne.HDMezz_5V_voltage_afe2.store(daphne.getHDMezzDriver()->readRailVoltage5V(2));
                    daphne.HDMezz_5V_current_afe2.store(daphne.getHDMezzDriver()->readRailCurrent5V(2));
                    daphne.HDMezz_3V3_voltage_afe2.store(daphne.getHDMezzDriver()->readRailVoltage3V3(2));
                    daphne.HDMezz_3V3_current_afe2.store(daphne.getHDMezzDriver()->readRailCurrent3V3(2));
                    daphne.HDMezz_5V_power_afe2.store(daphne.getHDMezzDriver()->readRailPower5V(2));
                    daphne.HDMezz_3V3_power_afe2.store(daphne.getHDMezzDriver()->readRailPower3V3(2));
                }
                
                if(daphne.getHDMezzDriver()->isAfeBlockEnabled(1)){
                    daphne.HDMezz_5V_voltage_afe1.store(daphne.getHDMezzDriver()->readRailVoltage5V(1));
                    daphne.HDMezz_5V_current_afe1.store(daphne.getHDMezzDriver()->readRailCurrent5V(1));
                    daphne.HDMezz_3V3_voltage_afe1.store(daphne.getHDMezzDriver()->readRailVoltage3V3(1));
                    daphne.HDMezz_3V3_current_afe1.store(daphne.getHDMezzDriver()->readRailCurrent3V3(1));
                    daphne.HDMezz_5V_power_afe1.store(daphne.getHDMezzDriver()->readRailPower5V(1));
                    daphne.HDMezz_3V3_power_afe1.store(daphne.getHDMezzDriver()->readRailPower3V3(1));
                }

                if(daphne.getHDMezzDriver()->isAfeBlockEnabled(0)){
                    daphne.HDMezz_5V_voltage_afe0.store(daphne.getHDMezzDriver()->readRailVoltage5V(0));
                    daphne.HDMezz_5V_current_afe0.store(daphne.getHDMezzDriver()->readRailCurrent5V(0));
                    daphne.HDMezz_3V3_voltage_afe0.store(daphne.getHDMezzDriver()->readRailVoltage3V3(0));
                    daphne.HDMezz_3V3_current_afe0.store(daphne.getHDMezzDriver()->readRailCurrent3V3(0));
                    daphne.HDMezz_5V_power_afe0.store(daphne.getHDMezzDriver()->readRailPower5V(0));
                    daphne.HDMezz_3V3_power_afe0.store(daphne.getHDMezzDriver()->readRailPower3V3(0));
                }
            }

            //Meassure time
            //auto end = std::chrono::high_resolution_clock::now();
            //std::chrono::duration<double> elapsed = end - start;
            //std::cout << "Time since last reading: " << elapsed.count() << " seconds" << std::endl;
            //std::cout << "5V  : " << daphne.HDMezz_5V_voltage_afe4.load() << " V, " << daphne.HDMezz_5V_current_afe4.load() << " mA, " << daphne.HDMezz_5V_power_afe4.load() << " mW" << std::endl;
            //std::cout << "3.3V: " << daphne.HDMezz_3V3_voltage_afe4.load() << " V, " << daphne.HDMezz_3V3_current_afe4.load() << " mA, " << daphne.HDMezz_3V3_power_afe4.load() << " mW" << std::endl;
            //std::this_thread::sleep_for(std::chrono::seconds(2));
        }catch(std::exception &e){
            std::cerr << "Error in monitor thread: " << e.what() << std::endl;
        }
    }
}

void I2C_1_monitorThread(Daphne &daphne){
    //auto start = std::chrono::high_resolution_clock::now();
    while(true){
        try{
            
            if(!daphne.isI2C_1_device_configuring.load() && !daphne.user_vbias_voltage_request.load()){
                daphne.is_vbias_voltage_monitor_reading.store(true);
                std::vector<double> adc_values_0x10 = daphne.getADS7138_Driver_addr_0x10()->readData(7);
                std::vector<double> adc_values_0x17 = daphne.getADS7138_Driver_addr_0x17()->readData(3);
                daphne.is_vbias_voltage_monitor_reading.store(false);
                
                daphne._3V3PDS_voltage.store(adc_values_0x10[0]*2.0);
                daphne._1V8PDS_voltage.store(adc_values_0x10[1]*2.0);
                daphne._VBIAS_0_voltage.store(adc_values_0x10[2]*39.314);
                daphne._VBIAS_1_voltage.store(adc_values_0x10[3]*39.314);
                daphne._VBIAS_2_voltage.store(adc_values_0x10[4]*39.314);
                daphne._VBIAS_3_voltage.store(adc_values_0x10[5]*39.314);
                daphne._VBIAS_4_voltage.store(adc_values_0x10[6]*39.314);

                daphne._1V8A_voltage.store(adc_values_0x17[0]*2.0);
                daphne._3V3A_voltage.store(adc_values_0x17[1]*2.0);
                daphne._n5VA_voltage.store(adc_values_0x17[2]*(-2.0));
            }
            
            
            //Meassure time
            //auto end = std::chrono::high_resolution_clock::now();
            //std::chrono::duration<double> elapsed = end - start;
            //ADC readout
            //std::cout << "ADC readout." << std::endl;
            //std::cout << "3V3PDS : " << daphne._3V3PDS_voltage.load() << " V, 1V8PDS : " << daphne._1V8PDS_voltage.load() << " V." << std::endl;
            //std::cout << "3V3A : " << daphne._3V3A_voltage.load() << " V, 1V8A : " << daphne._1V8A_voltage.load() << " V, -5VA :" << daphne._n5VA_voltage.load() << " V." <<std::endl;
            //std::cout << "BIAS 0 : " << daphne._VBIAS_0_voltage.load() << " V." << std::endl;
            //std::cout << "BIAS 1 : " << daphne._VBIAS_1_voltage.load() << " V." << std::endl;
            //std::cout << "BIAS 2 : " << daphne._VBIAS_2_voltage.load() << " V." << std::endl;
            //std::cout << "BIAS 3 : " << daphne._VBIAS_3_voltage.load() << " V." << std::endl;
            //std::cout << "BIAS 4 : " << daphne._VBIAS_4_voltage.load() << " V." << std::endl;
            //std::this_thread::sleep_for(std::chrono::seconds(2));
        }catch(std::exception &e){
            std::cerr << "Error in monitor thread: " << e.what() << std::endl;
        }
    }
}

int main(int argc, char* argv[]) {

    CLI::App app{"Daphne Slow Controller"};

    std::optional<std::string> ip_address;
    std::optional<uint16_t> port;
    std::optional<std::string> config_file;

    app.add_option("-i,--ip", ip_address, "DAPHNE device IPv4 address.")
       ->check([](const std::string& s) {
            return is_valid_ip(s) ? std::string() : std::string("Invalid IP address");
       });
    app.add_option("--port", port, "Port number of the DAPHNE device.")
        ->check(CLI::Range(1, 65535));
    app.add_option("--config_file", config_file, "Path to the configuration file (not yet implemented).")
        ->check(CLI::ExistingFile);


    app.callback([&](){
        bool mode_config = config_file.has_value();
        bool mode_ipport = ip_address.has_value() || port.has_value();

        if (mode_config && mode_ipport) {
            throw CLI::ValidationError("Use either --config-file or (--ip AND --port), not both.");
        }
        if (!mode_config && !mode_ipport) {
            throw CLI::ValidationError("Missing parameters. Use --config-file or (--ip --port).");
        }
        if (mode_ipport && (!ip_address || !port)) {
            throw CLI::ValidationError("Both --ip and --port are required for IP mode.");
        }
    });

    try {
        app.parse(argc, argv);
        bool config_mode = config_file.has_value();
        bool ip_port_mode = ip_address.has_value() || port.has_value();

        if(config_mode && ip_port_mode) {
            throw CLI::ValidationError("Use either --config_file or (--ip AND --port), not both.");
        }else if(!config_mode && !ip_port_mode) {
            throw CLI::ValidationError("Missing parameters. Use --config_file or (--ip and --port).");
        }else if(ip_port_mode && (!ip_address || !port)) {
            throw CLI::ValidationError("Both --ip and --port are required for IP mode.");
        }
    } catch (const CLI::CallForHelp& e) {
        // --help was requested
        std::cout << app.help() << "\n";
        return 0;
    } catch (const CLI::ParseError &e) {
        return app.exit(e);
    }

    zmq::context_t context(1);
    std::string endpoint = "tcp://" + *ip_address + ":" + std::to_string(*port);


    try {
        std::cout << "DAPHNE V3/Mezz Slow Controls V0_01_30\n";
        std::cout << "ZMQ ROUTER server binding on " << endpoint << "\n";
    } catch (const std::exception &e) {
        std::cerr << "Initialization error: " << e.what() << "\n";
        return 1;
    }


    Daphne daphne;

    std::thread monitor1_thread(I2C_1_monitorThread, std::ref(daphne));
    std::thread monitor2_thread(I2C_2_monitorThread, std::ref(daphne));
    // Enters the ROUTER-based server loop. This function binds the ROUTER
    // and handles both legacy single-reply and new chunked streaming.
    server_loop_router(context, endpoint, daphne);
    
    if (monitor1_thread.joinable()) {
        monitor1_thread.join();
    }
    if (monitor2_thread.joinable()) {
        monitor2_thread.join();
    }
    return 0;
}

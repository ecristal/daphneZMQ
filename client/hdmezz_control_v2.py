#!/usr/bin/env python3
"""
Exercise HD mezzanine EnvelopeV2 RPCs exposed by daphneServer.

Supported operations:
  - set-block-enable
  - configure-block
  - read-block-config
  - set-power-states
  - read-status
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from typing import Tuple

import zmq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low


DEFAULT_R_SHUNT_5V = 36e-3
DEFAULT_R_SHUNT_3V3 = 0.3
DEFAULT_MAX_CURRENT_5V_SCALE = 200e-3
DEFAULT_MAX_CURRENT_3V3_SCALE = 200e-3
DEFAULT_MAX_CURRENT_5V_SHUTDOWN = 120e-3
DEFAULT_MAX_CURRENT_3V3_SHUTDOWN = 10e-3


def next_ids() -> Tuple[int, int]:
    now_ns = time.time_ns()
    mask = (1 << 63) - 1
    return ((now_ns << 16) ^ random.randrange(1 << 16)) & mask, ((now_ns << 1) ^ random.randrange(1 << 16)) & mask


def v2_rpc(
    sock: zmq.Socket,
    req_type: int,
    req_msg,
    resp_type: int,
    resp_factory,
    *,
    route: str,
    timeout_ms: int,
):
    env = pb_high.ControlEnvelopeV2()
    env.version = 2
    env.dir = pb_high.DIR_REQUEST
    env.type = req_type
    env.payload = req_msg.SerializeToString()
    env.task_id, env.msg_id = next_ids()
    env.timestamp_ns = time.time_ns()
    if route:
        env.route = route

    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
    sock.send(env.SerializeToString())

    frames = [sock.recv()]
    while sock.getsockopt(zmq.RCVMORE):
        frames.append(sock.recv())

    rep = pb_high.ControlEnvelopeV2()
    if not rep.ParseFromString(frames[-1]):
        raise RuntimeError("Failed to parse ControlEnvelopeV2 reply")
    if rep.type != resp_type:
        raise RuntimeError(f"Unexpected response type {rep.type}, expected {resp_type}")
    if rep.correl_id and rep.correl_id != env.msg_id:
        raise RuntimeError(f"Correlation mismatch (got {rep.correl_id}, expected {env.msg_id})")

    resp = resp_factory()
    if not resp.ParseFromString(rep.payload):
        raise RuntimeError("Failed to parse response payload")
    return resp


def add_common_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--ip", default="127.0.0.1", help="Server IP")
    ap.add_argument("--port", type=int, default=9876, help="Server port")
    ap.add_argument("--route", default="mezz/0", help="EnvelopeV2 route")
    ap.add_argument("--identity", default="hdmezz-client", help="ZMQ identity")
    ap.add_argument("--timeout", type=int, default=5000, help="Per-request timeout (ms)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="HD mezzanine client for daphneServer (EnvelopeV2).")
    ap.add_argument("--visual", action="store_true", help="Open the Qt control window instead of using CLI subcommands")
    add_common_args(ap)
    sub = ap.add_subparsers(dest="command")

    p = sub.add_parser("set-block-enable", help="Enable or disable one HD mezzanine block")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")
    p.add_argument("--enable", choices=["0", "1"], required=True, help="0=disable, 1=enable")

    p = sub.add_parser("configure-block", help="Configure one HD mezzanine block")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")
    p.add_argument("--rshunt-5v", type=float, default=DEFAULT_R_SHUNT_5V, help="5V shunt resistor value")
    p.add_argument("--rshunt-3v3", type=float, default=DEFAULT_R_SHUNT_3V3, help="3V3 shunt resistor value")
    p.add_argument(
        "--max-current-5v-scale",
        type=float,
        default=DEFAULT_MAX_CURRENT_5V_SCALE,
        help="5V full-scale current",
    )
    p.add_argument(
        "--max-current-3v3-scale",
        type=float,
        default=DEFAULT_MAX_CURRENT_3V3_SCALE,
        help="3V3 full-scale current",
    )
    p.add_argument(
        "--max-current-5v-shutdown",
        type=float,
        default=DEFAULT_MAX_CURRENT_5V_SHUTDOWN,
        help="5V shutdown current",
    )
    p.add_argument(
        "--max-current-3v3-shutdown",
        type=float,
        default=DEFAULT_MAX_CURRENT_3V3_SHUTDOWN,
        help="3V3 shutdown current",
    )

    p = sub.add_parser("read-block-config", help="Read one HD mezzanine block configuration")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")

    p = sub.add_parser("set-power-states", help="Set 5V and 3V3 power states for one block")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")
    p.add_argument("--power-5v", choices=["0", "1"], required=True, help="0=off, 1=on")
    p.add_argument("--power-3v3", choices=["0", "1"], required=True, help="0=off, 1=on")

    p = sub.add_parser("read-status", help="Read cached HD mezzanine monitoring status")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")

    return ap


def print_config_response(resp) -> None:
    print(f"success={resp.success} afe={resp.afeBlock} message='{resp.message}'")
    print(f"r_shunt_5V={resp.r_shunt_5V} ohm")
    print(f"r_shunt_3V3={resp.r_shunt_3V3} ohm")
    print(f"max_current_5V_scale={resp.max_current_5V_scale} A")
    print(f"max_current_3V3_scale={resp.max_current_3V3_scale} A")
    print(f"max_current_5V_shutdown={resp.max_current_5V_shutdown} A")
    print(f"max_current_3V3_shutdown={resp.max_current_3V3_shutdown} A")
    if hasattr(resp, "max_power_5V"):
        print(f"max_power_5V={resp.max_power_5V} W")
        print(f"max_power_3V3={resp.max_power_3V3} W")
        print(f"current_lsb_5V={resp.current_lsb_5V} A/LSB")
        print(f"current_lsb_3V3={resp.current_lsb_3V3} A/LSB")
        print(f"shunt_cal_5V={resp.shunt_cal_5V}")
        print(f"shunt_cal_3V3={resp.shunt_cal_3V3}")


def print_status_response(resp) -> None:
    print(f"success={resp.success} afe={resp.afeBlock} message='{resp.message}'")
    print(f"power_5V={int(resp.power5V)}")
    print(f"power_3V3={int(resp.power3V3)}")
    print(f"alert_5V={int(resp.alert_5V)}")
    print(f"alert_3V3={int(resp.alert_3V3)}")
    print(f"measured_voltage_5V={resp.measured_voltage5V:.6f} V")
    print(f"measured_voltage_3V3={resp.measured_voltage3V3:.6f} V")
    print(f"measured_current_5V={resp.measured_current5V:.6f} mA")
    print(f"measured_current_3V3={resp.measured_current3V3:.6f} mA")
    print(f"measured_power_5V={resp.measured_power5V:.6f} mW")
    print(f"measured_power_3V3={resp.measured_power3V3:.6f} mW")


class HDMezzClient:
    def __init__(self, *, ip: str, port: int, route: str, identity: str, timeout_ms: int):
        self.ip = ip
        self.port = port
        self.route = route
        self.timeout_ms = timeout_ms
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.DEALER)
        self.sock.setsockopt(zmq.IDENTITY, identity.encode())
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.connect(f"tcp://{ip}:{port}")

    def close(self) -> None:
        self.sock.close()

    def set_block_enable(self, afe: int, enable: bool):
        req = pb_low.cmd_setHDMezzBlockEnable(id=0, afeBlock=afe, enable=enable)
        return v2_rpc(
            self.sock,
            pb_high.MT2_SET_HDMEZZ_BLOCK_ENABLE_REQ,
            req,
            pb_high.MT2_SET_HDMEZZ_BLOCK_ENABLE_RESP,
            pb_low.cmd_setHDMezzBlockEnable_response,
            route=self.route,
            timeout_ms=self.timeout_ms,
        )

    def configure_block(
        self,
        afe: int,
        *,
        r_shunt_5v: float,
        r_shunt_3v3: float,
        max_current_5v_scale: float,
        max_current_3v3_scale: float,
        max_current_5v_shutdown: float,
        max_current_3v3_shutdown: float,
    ):
        req = pb_low.cmd_configureHDMezzBlock(
            id=0,
            afeBlock=afe,
            r_shunt_5V=r_shunt_5v,
            r_shunt_3V3=r_shunt_3v3,
            max_current_5V_scale=max_current_5v_scale,
            max_current_3V3_scale=max_current_3v3_scale,
            max_current_5V_shutdown=max_current_5v_shutdown,
            max_current_3V3_shutdown=max_current_3v3_shutdown,
        )
        return v2_rpc(
            self.sock,
            pb_high.MT2_CONFIGURE_HDMEZZ_BLOCK_REQ,
            req,
            pb_high.MT2_CONFIGURE_HDMEZZ_BLOCK_RESP,
            pb_low.cmd_configureHDMezzBlock_response,
            route=self.route,
            timeout_ms=self.timeout_ms,
        )

    def read_block_config(self, afe: int):
        req = pb_low.cmd_readHDMezzBlockConfig(id=0, afeBlock=afe)
        return v2_rpc(
            self.sock,
            pb_high.MT2_READ_HDMEZZ_BLOCK_CONFIG_REQ,
            req,
            pb_high.MT2_READ_HDMEZZ_BLOCK_CONFIG_RESP,
            pb_low.cmd_readHDMezzBlockConfig_response,
            route=self.route,
            timeout_ms=self.timeout_ms,
        )

    def set_power_states(self, afe: int, *, power_5v: bool, power_3v3: bool):
        req = pb_low.cmd_setHDMezzPowerStates(id=0, afeBlock=afe, power5V=power_5v, power3V3=power_3v3)
        return v2_rpc(
            self.sock,
            pb_high.MT2_SET_HDMEZZ_POWER_STATES_REQ,
            req,
            pb_high.MT2_SET_HDMEZZ_POWER_STATES_RESP,
            pb_low.cmd_setHDMezzPowerStates_response,
            route=self.route,
            timeout_ms=self.timeout_ms,
        )

    def read_status(self, afe: int):
        req = pb_low.cmd_readHDMezzStatus(id=0, afeBlock=afe)
        return v2_rpc(
            self.sock,
            pb_high.MT2_READ_HDMEZZ_STATUS_REQ,
            req,
            pb_high.MT2_READ_HDMEZZ_STATUS_RESP,
            pb_low.cmd_readHDMezzStatus_response,
            route=self.route,
            timeout_ms=self.timeout_ms,
        )


def run_visual(args) -> int:
    from PyQt6 import QtCore, QtGui, QtWidgets

    console_style = """
    QWidget {
        background: #07131d;
        color: #d9f6ff;
        font-family: "Segoe UI", "Trebuchet MS", sans-serif;
        font-size: 11pt;
    }
    QGroupBox {
        border: 1px solid #2c5d74;
        border-radius: 10px;
        margin-top: 14px;
        padding-top: 18px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0c1d2c, stop:1 #08131d);
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 8px 0 8px;
        color: #8ff0ff;
        font-weight: 700;
        letter-spacing: 1px;
    }
    QLabel[role="section"] {
        color: #f9c66f;
        font-size: 10pt;
        font-weight: 700;
        letter-spacing: 1px;
    }
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1a5167, stop:1 #103346);
        border: 1px solid #59b2c9;
        border-radius: 8px;
        min-height: 28px;
        padding: 6px 12px;
        color: #f0fbff;
        font-weight: 600;
    }
    QPushButton:hover {
        border-color: #8ff0ff;
        background: #1f6884;
    }
    QPushButton:pressed {
        background: #0d2937;
    }
    QCheckBox {
        spacing: 10px;
        color: #e2fbff;
        font-weight: 600;
    }
    QCheckBox::indicator {
        width: 48px;
        height: 24px;
        border-radius: 12px;
        background: #1a2331;
        border: 1px solid #446071;
    }
    QCheckBox::indicator:checked {
        background: #24d08c;
        border: 1px solid #78ffd1;
    }
    QCheckBox::indicator:unchecked {
        background: #5c1a2b;
        border: 1px solid #cd567d;
    }
    QDoubleSpinBox, QPlainTextEdit {
        background: #051018;
        border: 1px solid #31556d;
        border-radius: 7px;
        padding: 4px 6px;
        selection-background-color: #1f6884;
    }
    QDial {
        background: transparent;
    }
    QScrollArea {
        border: none;
    }
    """

    class StatusLamp(QtWidgets.QFrame):
        def __init__(self, label: str, *, on_color: str, off_color: str):
            super().__init__()
            self.on_color = on_color
            self.off_color = off_color
            self._is_on = False

            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(6, 6, 6, 6)
            layout.setSpacing(4)

            self.bulb = QtWidgets.QLabel()
            self.bulb.setFixedSize(26, 26)
            self.bulb.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.bulb, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

            title = QtWidgets.QLabel(label)
            title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet("color: #dceff5; font-size: 9pt; font-weight: 700;")
            layout.addWidget(title)

            self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
            self.setStyleSheet("QFrame { border: 1px solid #31556d; border-radius: 9px; background: #08131d; }")
            self.set_on(False)

        def set_on(self, is_on: bool) -> None:
            self._is_on = bool(is_on)
            color = self.on_color if self._is_on else self.off_color
            glow = color if self._is_on else "#0d1117"
            self.bulb.setStyleSheet(
                f"QLabel {{"
                f"background: qradialgradient(cx:0.45, cy:0.35, radius:0.8, stop:0 #f7fbff, stop:0.18 {color}, stop:1 #11151b);"
                f"border: 1px solid #50606d;"
                f"border-radius: 13px;"
                f"box-shadow: 0 0 12px {glow};"
                f"}}"
            )

    class KnobSpin(QtWidgets.QWidget):
        def __init__(self, title: str, value: float, min_v: float, max_v: float, decimals: int, step: float):
            super().__init__()
            self._min = min_v
            self._max = max_v
            self._steps = 1000
            self._syncing = False

            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(4)

            label = QtWidgets.QLabel(title)
            label.setProperty("role", "section")
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)

            self.dial = QtWidgets.QDial()
            self.dial.setNotchesVisible(True)
            self.dial.setRange(0, self._steps)
            self.dial.setWrapping(False)
            self.dial.setFixedSize(92, 92)
            layout.addWidget(self.dial, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

            self.spin = QtWidgets.QDoubleSpinBox()
            self.spin.setRange(min_v, max_v)
            self.spin.setDecimals(decimals)
            self.spin.setSingleStep(step)
            self.spin.setValue(value)
            self.spin.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.spin)

            self.dial.valueChanged.connect(self._dial_to_spin)
            self.spin.valueChanged.connect(self._spin_to_dial)
            self._spin_to_dial(value)

        def _dial_to_spin(self, pos: int) -> None:
            if self._syncing:
                return
            self._syncing = True
            value = self._min + (self._max - self._min) * (pos / self._steps)
            self.spin.setValue(value)
            self._syncing = False

        def _spin_to_dial(self, value: float) -> None:
            if self._syncing:
                return
            self._syncing = True
            if self._max <= self._min:
                pos = 0
            else:
                pos = round((value - self._min) / (self._max - self._min) * self._steps)
            self.dial.setValue(max(0, min(self._steps, pos)))
            self._syncing = False

        def value(self) -> float:
            return float(self.spin.value())

        def setValue(self, value: float) -> None:
            self.spin.setValue(value)

    class TelemetryDisplay(QtWidgets.QFrame):
        def __init__(self, label: str, unit: str, digits: int = 8):
            super().__init__()
            self.unit = unit
            self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
            self.setStyleSheet("QFrame { border: 1px solid #31556d; border-radius: 9px; background: #02070a; }")

            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(4)

            title = QtWidgets.QLabel(label)
            title.setProperty("role", "section")
            title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title)

            self.lcd = QtWidgets.QLCDNumber()
            self.lcd.setDigitCount(digits)
            self.lcd.setSegmentStyle(QtWidgets.QLCDNumber.SegmentStyle.Flat)
            self.lcd.setSmallDecimalPoint(True)
            self.lcd.display("0.000")
            self.lcd.setStyleSheet(
                "QLCDNumber { background: #02070a; color: #7dff8d; border: 1px solid #173526; border-radius: 6px; }"
            )
            layout.addWidget(self.lcd)

            unit_label = QtWidgets.QLabel(unit)
            unit_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            unit_label.setStyleSheet("color: #8ff0ff; font-size: 9pt;")
            layout.addWidget(unit_label)

        def set_value(self, value: float) -> None:
            self.lcd.display(f"{value:0.3f}")

    class AFEPanel(QtWidgets.QGroupBox):
        def __init__(self, afe: int, client: HDMezzClient, log_fn):
            super().__init__(f"AFE BLOCK {afe}")
            self.afe = afe
            self.client = client
            self.log = log_fn

            shell = QtWidgets.QHBoxLayout(self)
            shell.setContentsMargins(12, 16, 12, 12)
            shell.setSpacing(14)

            left = QtWidgets.QVBoxLayout()
            left.setSpacing(10)
            left.addWidget(self._section_label("SWITCHES"))

            self.enable_check = QtWidgets.QCheckBox("AFT BUS ENABLE")
            self.power_5v = QtWidgets.QCheckBox("5V RAIL")
            self.power_3v3 = QtWidgets.QCheckBox("3V3 RAIL")
            left.addWidget(self.enable_check)
            left.addWidget(self.power_5v)
            left.addWidget(self.power_3v3)

            lamp_grid = QtWidgets.QGridLayout()
            lamp_grid.setHorizontalSpacing(8)
            lamp_grid.setVerticalSpacing(8)
            self.power_5v_lamp = StatusLamp("5V POWER", on_color="#39f07f", off_color="#153324")
            self.power_3v3_lamp = StatusLamp("3V3 POWER", on_color="#39f07f", off_color="#153324")
            self.alert_5v_lamp = StatusLamp("5V ALERT", on_color="#ff4d4d", off_color="#34161b")
            self.alert_3v3_lamp = StatusLamp("3V3 ALERT", on_color="#ff4d4d", off_color="#34161b")
            lamp_grid.addWidget(self.power_5v_lamp, 0, 0)
            lamp_grid.addWidget(self.power_3v3_lamp, 0, 1)
            lamp_grid.addWidget(self.alert_5v_lamp, 1, 0)
            lamp_grid.addWidget(self.alert_3v3_lamp, 1, 1)
            left.addLayout(lamp_grid)

            self.enable_button = QtWidgets.QPushButton("Commit Enable")
            self.enable_button.clicked.connect(self.apply_enable)
            self.power_button = QtWidgets.QPushButton("Commit Power")
            self.power_button.clicked.connect(self.apply_power)
            self.read_status_button = QtWidgets.QPushButton("Scan Telemetry")
            self.read_status_button.clicked.connect(self.read_status)
            self.read_config_button = QtWidgets.QPushButton("Recall Config")
            self.read_config_button.clicked.connect(self.read_config)
            self.configure_button = QtWidgets.QPushButton("Program Block")
            self.configure_button.clicked.connect(self.configure)
            for button in (
                self.enable_button,
                self.power_button,
                self.read_status_button,
                self.read_config_button,
                self.configure_button,
            ):
                left.addWidget(button)
            left.addStretch(1)
            shell.addLayout(left, 0)

            middle = QtWidgets.QVBoxLayout()
            middle.setSpacing(8)
            middle.addWidget(self._section_label("KNOBS"))

            knobs_grid = QtWidgets.QGridLayout()
            knobs_grid.setHorizontalSpacing(10)
            knobs_grid.setVerticalSpacing(10)
            self.r_shunt_5v = KnobSpin("R SHUNT 5V", DEFAULT_R_SHUNT_5V, 0.0, 1.0, 6, 0.001)
            self.r_shunt_3v3 = KnobSpin("R SHUNT 3V3", DEFAULT_R_SHUNT_3V3, 0.0, 1.0, 6, 0.001)
            self.max_current_5v_scale = KnobSpin("I SCALE 5V", DEFAULT_MAX_CURRENT_5V_SCALE, 0.0, 1.0, 6, 0.001)
            self.max_current_3v3_scale = KnobSpin("I SCALE 3V3", DEFAULT_MAX_CURRENT_3V3_SCALE, 0.0, 1.0, 6, 0.001)
            self.max_current_5v_shutdown = KnobSpin("I CUT 5V", DEFAULT_MAX_CURRENT_5V_SHUTDOWN, 0.0, 1.0, 6, 0.001)
            self.max_current_3v3_shutdown = KnobSpin("I CUT 3V3", DEFAULT_MAX_CURRENT_3V3_SHUTDOWN, 0.0, 1.0, 6, 0.001)
            knob_widgets = [
                self.r_shunt_5v,
                self.r_shunt_3v3,
                self.max_current_5v_scale,
                self.max_current_3v3_scale,
                self.max_current_5v_shutdown,
                self.max_current_3v3_shutdown,
            ]
            for idx, widget in enumerate(knob_widgets):
                knobs_grid.addWidget(widget, idx // 3, idx % 3)
            middle.addLayout(knobs_grid)
            shell.addLayout(middle, 1)

            right = QtWidgets.QVBoxLayout()
            right.setSpacing(8)
            right.addWidget(self._section_label("SEVEN-SEG TELEMETRY"))

            telemetry_grid = QtWidgets.QGridLayout()
            telemetry_grid.setHorizontalSpacing(10)
            telemetry_grid.setVerticalSpacing(10)
            self.v5_display = TelemetryDisplay("BUS 5V", "V")
            self.v3_display = TelemetryDisplay("BUS 3V3", "V")
            self.i5_display = TelemetryDisplay("LOAD 5V", "mA")
            self.i3_display = TelemetryDisplay("LOAD 3V3", "mA")
            self.p5_display = TelemetryDisplay("POWER 5V", "mW")
            self.p3_display = TelemetryDisplay("POWER 3V3", "mW")
            displays = [
                self.v5_display,
                self.v3_display,
                self.i5_display,
                self.i3_display,
                self.p5_display,
                self.p3_display,
            ]
            for idx, widget in enumerate(displays):
                telemetry_grid.addWidget(widget, idx // 2, idx % 2)
            right.addLayout(telemetry_grid)
            right.addStretch(1)
            shell.addLayout(right, 1)

        @staticmethod
        def _section_label(text: str) -> QtWidgets.QLabel:
            label = QtWidgets.QLabel(text)
            label.setProperty("role", "section")
            return label

        def _run(self, label: str, fn):
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.BusyCursor)
            try:
                resp = fn()
                self.log(f"[AFE {self.afe}] {label}: success={resp.success} message='{resp.message}'")
                return resp
            except Exception as exc:
                self.log(f"[AFE {self.afe}] {label}: ERROR {exc}")
                return None
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()

        def apply_enable(self):
            resp = self._run("SET_BLOCK_ENABLE", lambda: self.client.set_block_enable(self.afe, self.enable_check.isChecked()))
            if resp is not None:
                self.enable_check.setChecked(bool(resp.enable))

        def configure(self):
            self._run(
                "CONFIGURE_BLOCK",
                lambda: self.client.configure_block(
                    self.afe,
                    r_shunt_5v=self.r_shunt_5v.value(),
                    r_shunt_3v3=self.r_shunt_3v3.value(),
                    max_current_5v_scale=self.max_current_5v_scale.value(),
                    max_current_3v3_scale=self.max_current_3v3_scale.value(),
                    max_current_5v_shutdown=self.max_current_5v_shutdown.value(),
                    max_current_3v3_shutdown=self.max_current_3v3_shutdown.value(),
                ),
            )

        def read_config(self):
            resp = self._run("READ_BLOCK_CONFIG", lambda: self.client.read_block_config(self.afe))
            if resp is None:
                return
            self.r_shunt_5v.setValue(resp.r_shunt_5V)
            self.r_shunt_3v3.setValue(resp.r_shunt_3V3)
            self.max_current_5v_scale.setValue(resp.max_current_5V_scale)
            self.max_current_3v3_scale.setValue(resp.max_current_3V3_scale)
            self.max_current_5v_shutdown.setValue(resp.max_current_5V_shutdown)
            self.max_current_3v3_shutdown.setValue(resp.max_current_3V3_shutdown)
            self.log(
                f"[AFE {self.afe}] CONFIG values: "
                f"r5={resp.r_shunt_5V:.6f} r3={resp.r_shunt_3V3:.6f} "
                f"i5s={resp.max_current_5V_scale:.6f} i3s={resp.max_current_3V3_scale:.6f}"
            )

        def apply_power(self):
            self._run(
                "SET_POWER_STATES",
                lambda: self.client.set_power_states(
                    self.afe,
                    power_5v=self.power_5v.isChecked(),
                    power_3v3=self.power_3v3.isChecked(),
                ),
            )

        def read_status(self):
            resp = self._run("READ_STATUS", lambda: self.client.read_status(self.afe))
            if resp is None:
                return
            self.power_5v.setChecked(bool(resp.power5V))
            self.power_3v3.setChecked(bool(resp.power3V3))
            self.power_5v_lamp.set_on(bool(resp.power5V))
            self.power_3v3_lamp.set_on(bool(resp.power3V3))
            self.alert_5v_lamp.set_on(bool(resp.alert_5V))
            self.alert_3v3_lamp.set_on(bool(resp.alert_3V3))
            self.v5_display.set_value(resp.measured_voltage5V)
            self.v3_display.set_value(resp.measured_voltage3V3)
            self.i5_display.set_value(resp.measured_current5V)
            self.i3_display.set_value(resp.measured_current3V3)
            self.p5_display.set_value(resp.measured_power5V)
            self.p3_display.set_value(resp.measured_power3V3)
            self.log(
                f"[AFE {self.afe}] STATUS: "
                f"V5={resp.measured_voltage5V:.4f} V "
                f"V3={resp.measured_voltage3V3:.4f} V "
                f"I5={resp.measured_current5V:.4f} mA "
                f"I3={resp.measured_current3V3:.4f} mA "
                f"P5={resp.measured_power5V:.4f} mW "
                f"P3={resp.measured_power3V3:.4f} mW "
                f"PW5={int(resp.power5V)} PW3={int(resp.power3V3)} "
                f"AL5={int(resp.alert_5V)} AL3={int(resp.alert_3V3)}"
            )

    class HDMezzControlApp(QtWidgets.QWidget):
        def __init__(self, client: HDMezzClient):
            super().__init__()
            self.client = client
            self.setWindowTitle("HD MEZZANINE CONTROL PANEL")
            self.resize(1600, 980)
            self.setStyleSheet(console_style)

            root = QtWidgets.QVBoxLayout(self)
            root.setContentsMargins(16, 16, 16, 16)
            root.setSpacing(12)

            banner = QtWidgets.QFrame()
            banner.setStyleSheet("QFrame { border: 1px solid #31556d; border-radius: 12px; background: #091823; }")
            banner_layout = QtWidgets.QHBoxLayout(banner)
            title = QtWidgets.QLabel("HD MEZZANINE CONTROL PANEL")
            title.setStyleSheet("font-size: 22pt; font-weight: 800; letter-spacing: 2px; color: #8ff0ff;")
            subtitle = QtWidgets.QLabel(f"LINK tcp://{client.ip}:{client.port}   ROUTE {client.route}")
            subtitle.setStyleSheet("color: #f9c66f; font-size: 10pt;")
            title_stack = QtWidgets.QVBoxLayout()
            title_stack.addWidget(title)
            title_stack.addWidget(subtitle)
            banner_layout.addLayout(title_stack)
            banner_layout.addStretch(1)
            root.addWidget(banner)

            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll_host = QtWidgets.QWidget()
            scroll_layout = QtWidgets.QVBoxLayout(scroll_host)
            scroll_layout.setSpacing(12)
            for afe in range(5):
                scroll_layout.addWidget(AFEPanel(afe, client, self.append_log))
            scroll_layout.addStretch(1)
            scroll.setWidget(scroll_host)
            root.addWidget(scroll, 1)

            self.log = QtWidgets.QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setMaximumBlockCount(500)
            self.log.setPlaceholderText("Console traffic and telemetry scans will appear here.")
            self.log.setFixedHeight(160)
            root.addWidget(self.log)

            QtWidgets.QApplication.instance().aboutToQuit.connect(self.client.close)

        def append_log(self, text: str) -> None:
            ts = QtCore.QDateTime.currentDateTime().toString("HH:mm:ss")
            self.log.appendPlainText(f"{ts}  {text}")

    client = HDMezzClient(
        ip=args.ip,
        port=args.port,
        route=args.route,
        identity=args.identity,
        timeout_ms=args.timeout,
    )
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setApplicationName("HD MEZZANINE CONTROL PANEL")
    app.setWindowIcon(QtGui.QIcon())
    win = HDMezzControlApp(client)
    win.show()
    return app.exec()


def main() -> int:
    args = build_parser().parse_args()

    if args.visual:
        return run_visual(args)

    if not args.command:
        build_parser().error("a subcommand is required unless --visual is used")

    client = HDMezzClient(
        ip=args.ip,
        port=args.port,
        route=args.route,
        identity=args.identity,
        timeout_ms=args.timeout,
    )

    try:
        if args.command == "set-block-enable":
            resp = client.set_block_enable(args.afe, bool(int(args.enable)))
            print(f"success={resp.success} afe={resp.afeBlock} enable={int(resp.enable)} message='{resp.message}'")
            return 0 if resp.success else 2

        if args.command == "configure-block":
            resp = client.configure_block(
                args.afe,
                r_shunt_5v=args.rshunt_5v,
                r_shunt_3v3=args.rshunt_3v3,
                max_current_5v_scale=args.max_current_5v_scale,
                max_current_3v3_scale=args.max_current_3v3_scale,
                max_current_5v_shutdown=args.max_current_5v_shutdown,
                max_current_3v3_shutdown=args.max_current_3v3_shutdown,
            )
            print_config_response(resp)
            return 0 if resp.success else 2

        if args.command == "read-block-config":
            resp = client.read_block_config(args.afe)
            print_config_response(resp)
            return 0 if resp.success else 2

        if args.command == "set-power-states":
            resp = client.set_power_states(args.afe, power_5v=bool(int(args.power_5v)), power_3v3=bool(int(args.power_3v3)))
            print(
                f"success={resp.success} afe={resp.afeBlock} power5V={int(resp.power5V)} "
                f"power3V3={int(resp.power3V3)} message='{resp.message}'"
            )
            return 0 if resp.success else 2

        if args.command == "read-status":
            resp = client.read_status(args.afe)
            print_status_response(resp)
            return 0 if resp.success else 2

        raise RuntimeError(f"Unhandled command {args.command}")
    except zmq.Again:
        print("[timeout] no reply")
        return 2
    except Exception as exc:
        print(f"[error] {exc}")
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

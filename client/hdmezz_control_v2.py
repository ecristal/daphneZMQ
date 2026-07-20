#!/usr/bin/env python3
"""
Exercise HD mezzanine EnvelopeV2 RPCs exposed by daphneServer.

Supported operations:
  - set-block-enable
  - configure-block
  - read-block-config
  - set-power-states
  - read-status
  - clear-alert-flag
"""

from __future__ import annotations

import argparse
from collections import deque
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
DEFAULT_R_SHUNT_CE = 0.3
DEFAULT_MAX_CURRENT_5V_SCALE = 200e-3
DEFAULT_MAX_CURRENT_CE_SCALE = 200e-3
DEFAULT_MAX_CURRENT_5V_SHUTDOWN = 120e-3
DEFAULT_MAX_CURRENT_CE_SHUTDOWN = 50e-3


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
    p.add_argument("--rshunt-ce", "--rshunt-3v3", dest="rshunt_ce", type=float, default=DEFAULT_R_SHUNT_CE, help="CE shunt resistor value")
    p.add_argument(
        "--max-current-5v-scale",
        type=float,
        default=DEFAULT_MAX_CURRENT_5V_SCALE,
        help="5V full-scale current",
    )
    p.add_argument(
        "--max-current-ce-scale", "--max-current-3v3-scale", dest="max_current_ce_scale",
        type=float,
        default=DEFAULT_MAX_CURRENT_CE_SCALE,
        help="CE full-scale current",
    )
    p.add_argument(
        "--max-current-5v-shutdown",
        type=float,
        default=DEFAULT_MAX_CURRENT_5V_SHUTDOWN,
        help="5V shutdown current",
    )
    p.add_argument(
        "--max-current-ce-shutdown", "--max-current-3v3-shutdown", dest="max_current_ce_shutdown",
        type=float,
        default=DEFAULT_MAX_CURRENT_CE_SHUTDOWN,
        help="CE shutdown current",
    )

    p = sub.add_parser("read-block-config", help="Read one HD mezzanine block configuration")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")

    p = sub.add_parser("set-power-states", help="Set 5V and CE power states for one block")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")
    p.add_argument("--power-5v", choices=["0", "1"], required=True, help="0=off, 1=on")
    p.add_argument("--power-ce", "--power-3v3", dest="power_ce", choices=["0", "1"], required=True, help="0=off, 1=on")

    p = sub.add_parser("read-status", help="Read cached HD mezzanine monitoring status")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")

    p = sub.add_parser("clear-alert-flag", help="Clear HD mezzanine alert flags for one block")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")

    return ap


def print_config_response(resp) -> None:
    print(f"success={resp.success} afe={resp.afeBlock} message='{resp.message}'")
    print(f"r_shunt_5V={resp.r_shunt_5V} ohm")
    print(f"r_shunt_CE={resp.r_shunt_3V3} ohm")
    print(f"max_current_5V_scale={resp.max_current_5V_scale} A")
    print(f"max_current_CE_scale={resp.max_current_3V3_scale} A")
    print(f"max_current_5V_shutdown={resp.max_current_5V_shutdown} A")
    print(f"max_current_CE_shutdown={resp.max_current_3V3_shutdown} A")
    if hasattr(resp, "max_power_5V"):
        print(f"max_power_5V={resp.max_power_5V} W")
        print(f"max_power_CE={resp.max_power_3V3} W")
        print(f"current_lsb_5V={resp.current_lsb_5V} A/LSB")
        print(f"current_lsb_CE={resp.current_lsb_3V3} A/LSB")
        print(f"shunt_cal_5V={resp.shunt_cal_5V}")
        print(f"shunt_cal_CE={resp.shunt_cal_3V3}")


def print_status_response(resp) -> None:
    print(f"success={resp.success} afe={resp.afeBlock} message='{resp.message}'")
    print(f"power_5V={int(resp.power5V)}")
    print(f"power_CE={int(resp.power3V3)}")
    print(f"alert_5V={int(resp.alert_5V)}")
    print(f"alert_CE={int(resp.alert_3V3)}")
    print(f"measured_voltage_5V={resp.measured_voltage5V:.6f} V")
    print(f"measured_voltage_CE={resp.measured_voltage3V3:.6f} V")
    print(f"measured_current_5V={resp.measured_current5V:.6f} mA")
    print(f"measured_current_CE={resp.measured_current3V3:.6f} mA")
    print(f"measured_power_5V={resp.measured_power5V:.6f} mW")
    print(f"measured_power_CE={resp.measured_power3V3:.6f} mW")


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

    def clear_alert_flag(self, afe: int):
        req = pb_low.cmd_clearHDMezzAlertFlag(id=0, afeBlock=afe)
        return v2_rpc(
            self.sock,
            pb_high.MT2_CLEAR_HDMEZZ_ALERT_FLAG_REQ,
            req,
            pb_high.MT2_CLEAR_HDMEZZ_ALERT_FLAG_RESP,
            pb_low.cmd_clearHDMezzAlertFlag_response,
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
            self.bulb.setFixedSize(38, 38)
            self.bulb.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.bulb, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

            title = QtWidgets.QLabel(label)
            title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet("color: #dceff5; font-size: 9pt; font-weight: 700;")
            layout.addWidget(title)

            self.setMinimumHeight(82)
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
                f"border-radius: 19px;"
                f"box-shadow: 0 0 12px {glow};"
                f"}}"
            )

    class VerticalConfigControl(QtWidgets.QWidget):
        def __init__(self, title: str, unit: str, value: float, min_v: float,
                     max_v: float, decimals: int, step: float):
            super().__init__()
            self._min = min_v
            self._max = max_v
            self._steps = 1000
            self._syncing = False
            self.setMinimumWidth(125)

            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(6, 4, 6, 4)
            layout.setSpacing(5)
            label = QtWidgets.QLabel(title)
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            label.setStyleSheet("color: #f9c66f; font-weight: 700; font-size: 9pt;")
            layout.addWidget(label)

            slider_row = QtWidgets.QHBoxLayout()
            self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
            self.slider.setRange(0, self._steps)
            self.slider.setMinimumHeight(145)
            self.slider.setTickPosition(QtWidgets.QSlider.TickPosition.TicksBothSides)
            self.slider.setTickInterval(250)
            limits = QtWidgets.QVBoxLayout()
            max_label = QtWidgets.QLabel(f"{max_v:g}")
            min_label = QtWidgets.QLabel(f"{min_v:g}")
            for item in (max_label, min_label):
                item.setStyleSheet("color: #7ea5b7; font-size: 8pt;")
            limits.addWidget(max_label)
            limits.addStretch(1)
            limits.addWidget(min_label)
            slider_row.addStretch(1)
            slider_row.addWidget(self.slider)
            slider_row.addLayout(limits)
            slider_row.addStretch(1)
            layout.addLayout(slider_row, 1)

            self.spin = QtWidgets.QDoubleSpinBox()
            self.spin.setRange(min_v, max_v)
            self.spin.setDecimals(decimals)
            self.spin.setSingleStep(step)
            self.spin.setSuffix(f" {unit}")
            self.spin.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.spin)
            self.slider.valueChanged.connect(self._slider_to_spin)
            self.spin.valueChanged.connect(self._spin_to_slider)
            self.setValue(value)

        def _slider_to_spin(self, pos: int) -> None:
            if self._syncing:
                return
            self._syncing = True
            self.spin.setValue(self._min + (self._max - self._min) * pos / self._steps)
            self._syncing = False

        def _spin_to_slider(self, value: float) -> None:
            if self._syncing:
                return
            self._syncing = True
            pos = round((value - self._min) / (self._max - self._min) * self._steps)
            self.slider.setValue(max(0, min(self._steps, pos)))
            self._syncing = False

        def value(self) -> float:
            return float(self.spin.value())

        def setValue(self, value: float) -> None:
            self.spin.setValue(value)
            self._spin_to_slider(value)

    class ConfigurationDialog(QtWidgets.QDialog):
        SPECS = (
            ("r_shunt_5v", "R SHUNT 5V", "ohm", 0.001, 0.100, 6, 0.001),
            ("r_shunt_ce", "R SHUNT CE", "ohm", 0.010, 1.000, 6, 0.010),
            ("max_current_5v_scale", "I SCALE 5V", "A", 0.010, 0.500, 3, 0.010),
            ("max_current_ce_scale", "I SCALE CE", "A", 0.010, 0.250, 3, 0.005),
            ("max_current_5v_shutdown", "I CUT 5V", "A", 0.005, 0.200, 3, 0.005),
            ("max_current_ce_shutdown", "I CUT CE", "A", 0.001, 0.200, 3, 0.005),
        )

        def __init__(self, afe: int, values: dict, parent=None):
            super().__init__(parent)
            self.setWindowTitle(f"AFE {afe} Hardware Configuration")
            self.setModal(True)
            self.setMinimumSize(900, 430)
            root = QtWidgets.QVBoxLayout(self)
            heading = QtWidgets.QLabel(f"AFE BLOCK {afe} - CURRENT MONITOR CONFIGURATION")
            heading.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            heading.setStyleSheet("font-size: 13pt; font-weight: 800; color: #8ff0ff;")
            root.addWidget(heading)
            note = QtWidgets.QLabel("Adjust with the sliders or enter exact values. Applying configuration forces both rail requests off.")
            note.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            note.setStyleSheet("color: #a7c8d6;")
            root.addWidget(note)

            controls = QtWidgets.QHBoxLayout()
            controls.setSpacing(10)
            self.controls = {}
            for key, label, unit, minimum, maximum, decimals, step in self.SPECS:
                control = VerticalConfigControl(label, unit, values[key], minimum, maximum, decimals, step)
                self.controls[key] = control
                controls.addWidget(control, 1)
            root.addLayout(controls, 1)

            buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.StandardButton.Cancel |
                QtWidgets.QDialogButtonBox.StandardButton.Apply)
            defaults = buttons.addButton("Restore Defaults", QtWidgets.QDialogButtonBox.ButtonRole.ResetRole)
            defaults.clicked.connect(self.restore_defaults)
            buttons.rejected.connect(self.reject)
            buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Apply).clicked.connect(self._validate_and_accept)
            root.addWidget(buttons)

        def restore_defaults(self) -> None:
            defaults = {
                "r_shunt_5v": DEFAULT_R_SHUNT_5V,
                "r_shunt_ce": DEFAULT_R_SHUNT_CE,
                "max_current_5v_scale": DEFAULT_MAX_CURRENT_5V_SCALE,
                "max_current_ce_scale": DEFAULT_MAX_CURRENT_CE_SCALE,
                "max_current_5v_shutdown": DEFAULT_MAX_CURRENT_5V_SHUTDOWN,
                "max_current_ce_shutdown": DEFAULT_MAX_CURRENT_CE_SHUTDOWN,
            }
            for key, value in defaults.items():
                self.controls[key].setValue(value)

        def values(self) -> dict:
            return {key: control.value() for key, control in self.controls.items()}

        def _validate_and_accept(self) -> None:
            values = self.values()
            if values["max_current_5v_shutdown"] > values["max_current_5v_scale"]:
                QtWidgets.QMessageBox.warning(self, "Invalid 5V configuration", "5V cutoff current cannot exceed the 5V measurement scale.")
                return
            if values["max_current_ce_shutdown"] > values["max_current_ce_scale"]:
                QtWidgets.QMessageBox.warning(self, "Invalid CE configuration", "CE cutoff current cannot exceed the CE measurement scale.")
                return
            self.accept()

    class TelemetryDisplay(QtWidgets.QFrame):
        def __init__(self, label: str, unit: str, digits: int = 8):
            super().__init__()
            self.unit = unit
            self.setMinimumHeight(92)
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
            self.lcd.setMinimumHeight(38)
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

    class SectionBay(QtWidgets.QFrame):
        def __init__(self, title: str):
            super().__init__()
            self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
            self.setStyleSheet(
                "QFrame { border: 1px solid #31556d; border-radius: 10px; background: #08131d; }"
            )
            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(10, 8, 10, 10)
            layout.setSpacing(8)

            title_label = QtWidgets.QLabel(title)
            title_label.setProperty("role", "section")
            title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            title_label.setStyleSheet("color: #f9c66f; font-size: 9pt; font-weight: 700; letter-spacing: 1px;")
            layout.addWidget(title_label, 0, QtCore.Qt.AlignmentFlag.AlignTop)
            self.body = QtWidgets.QVBoxLayout()
            self.body.setContentsMargins(0, 0, 0, 0)
            self.body.setSpacing(8)
            layout.addLayout(self.body, 1)

    class TrendGraph(QtWidgets.QFrame):
        def __init__(self, title: str, unit: str, series_specs, history_len: int = 90):
            super().__init__()
            self.unit = unit
            self.history_len = history_len
            self.series_specs = series_specs
            self.history = {name: deque(maxlen=history_len) for name, _label, _color in series_specs}
            self._y_min, self._y_max = -1.0, 1.0
            self.legend_chips = {}

            self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
            self.setStyleSheet("QFrame { border: 1px solid #31556d; border-radius: 9px; background: #02070a; }")

            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(4)

            title_label = QtWidgets.QLabel(title)
            title_label.setProperty("role", "section")
            title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            title_label.setStyleSheet("color: #f9c66f; font-size: 9pt; font-weight: 700; letter-spacing: 1px;")
            layout.addWidget(title_label)

            legend = QtWidgets.QHBoxLayout()
            legend.setSpacing(10)
            legend.addStretch(1)
            for name, label, color in series_specs:
                chip = QtWidgets.QLabel(f"{label}: -- {unit}")
                self.legend_chips[name] = (chip, label)
                chip.setStyleSheet(
                    f"QLabel {{ color: {color}; font-size: 8pt; font-weight: 700; padding: 0 2px; }}"
                )
                legend.addWidget(chip)
            legend.addStretch(1)
            layout.addLayout(legend)

            self.canvas = QtWidgets.QWidget()
            self.setMinimumWidth(300)
            self.canvas.setMinimumHeight(210)
            self.canvas.paintEvent = self._paint_canvas
            layout.addWidget(self.canvas)

            self.scale_label = QtWidgets.QLabel(f"Y max: 0.000 {unit}   X: newest at right")
            self.scale_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            self.scale_label.setStyleSheet("color: #8ff0ff; font-size: 7.5pt;")
            layout.addWidget(self.scale_label)

        def append_values(self, values: dict) -> None:
            for name, _label, color in self.series_specs:
                value = float(values.get(name, 0.0))
                self.history[name].append(value)
                chip, label = self.legend_chips[name]
                chip.setText(f"{label}: {value:.3f} {self.unit}")
            visible = [v for series in self.history.values() for v in series]
            if visible:
                raw_min, raw_max = min(visible), max(visible)
                raw_min, raw_max = min(raw_min, 0.0), max(raw_max, 0.0)
                spread = raw_max - raw_min
                padding = max(abs(raw_max), abs(raw_min), 1.0) * 0.08 if spread == 0 else spread * 0.10
                self._y_min, self._y_max = raw_min - padding, raw_max + padding
            self.scale_label.setText(
                f"Range: {self._y_min:.3f} to {self._y_max:.3f} {self.unit} | {self.history_len} samples")
            self.canvas.update()

        def _paint_canvas(self, _event) -> None:
            painter = QtGui.QPainter(self.canvas)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            rect = self.canvas.rect().adjusted(34, 10, -14, -24)
            painter.fillRect(rect, QtGui.QColor("#02070a"))

            grid_pen = QtGui.QPen(QtGui.QColor("#173526"))
            grid_pen.setWidth(1)
            painter.setPen(grid_pen)
            for frac in (0.25, 0.5, 0.75):
                y = rect.top() + int(rect.height() * frac)
                painter.drawLine(rect.left(), y, rect.right(), y)

            axis_pen = QtGui.QPen(QtGui.QColor("#8ff0ff"))
            axis_pen.setWidth(1)
            painter.setPen(axis_pen)
            painter.drawLine(rect.left(), rect.top(), rect.left(), rect.bottom())
            painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

            tick_pen = QtGui.QPen(QtGui.QColor("#6baec4"))
            tick_pen.setWidth(1)
            painter.setPen(tick_pen)
            for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                y = rect.bottom() - int(rect.height() * frac)
                painter.drawLine(rect.left() - 4, y, rect.left(), y)
            for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                x = rect.left() + int(rect.width() * frac)
                painter.drawLine(x, rect.bottom(), x, rect.bottom() + 4)

            all_values = [v for series in self.history.values() for v in series]
            axis_label_pen = QtGui.QPen(QtGui.QColor("#8ff0ff"))
            painter.setPen(axis_label_pen)
            axis_font = painter.font()
            axis_font.setPointSizeF(7.0)
            painter.setFont(axis_font)
            painter.drawText(rect.left(), rect.bottom() + 6, 36, 12, int(QtCore.Qt.AlignmentFlag.AlignLeft), "old")
            painter.drawText(rect.right() - 36, rect.bottom() + 6, 36, 12, int(QtCore.Qt.AlignmentFlag.AlignRight), "new")

            if not all_values:
                painter.end()
                return

            y_min, y_max = self._y_min, self._y_max
            y_span = max(y_max - y_min, 1e-9)
            for fraction, value in ((0.0, y_max), (0.5, (y_min + y_max) / 2.0), (1.0, y_min)):
                y = rect.top() + int(rect.height() * fraction)
                painter.drawText(1, y - 6, 30, 12, int(QtCore.Qt.AlignmentFlag.AlignRight), f"{value:.2f}")

            for name, _label, color in self.series_specs:
                data = list(self.history[name])
                if len(data) < 2:
                    continue
                path = QtGui.QPainterPath()
                for idx, value in enumerate(data):
                    x = rect.left() + (rect.width() * idx / max(1, self.history_len - 1))
                    y_norm = (value - y_min) / y_span
                    y = rect.bottom() - (rect.height() * y_norm)
                    point = QtCore.QPointF(float(x), float(y))
                    if idx == 0:
                        path.moveTo(point)
                    else:
                        path.lineTo(point)
                pen = QtGui.QPen(QtGui.QColor(color))
                pen.setWidth(2)
                painter.setPen(pen)
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
                latest = data[-1]
                latest_x = rect.left() + (rect.width() * (len(data) - 1) / max(1, self.history_len - 1))
                latest_y = rect.bottom() - (rect.height() * ((latest - y_min) / y_span))
                painter.setBrush(QtGui.QBrush(QtGui.QColor(color)))
                painter.drawEllipse(QtCore.QPointF(float(latest_x), float(latest_y)), 3.0, 3.0)
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

            painter.end()

    class AFEPanel(QtWidgets.QGroupBox):
        def __init__(self, afe: int, client: HDMezzClient, log_fn):
            super().__init__(f"AFE BLOCK {afe}")
            self.afe = afe
            self.client = client
            self.log = log_fn
            self.config_values = {
                "r_shunt_5v": DEFAULT_R_SHUNT_5V,
                "r_shunt_ce": DEFAULT_R_SHUNT_CE,
                "max_current_5v_scale": DEFAULT_MAX_CURRENT_5V_SCALE,
                "max_current_ce_scale": DEFAULT_MAX_CURRENT_CE_SCALE,
                "max_current_5v_shutdown": DEFAULT_MAX_CURRENT_5V_SHUTDOWN,
                "max_current_ce_shutdown": DEFAULT_MAX_CURRENT_CE_SHUTDOWN,
            }

            self.setMinimumHeight(500)
            shell = QtWidgets.QHBoxLayout(self)
            shell.setContentsMargins(14, 18, 14, 14)
            shell.setSpacing(14)

            command_bay = SectionBay("COMMAND & STATUS")
            command_bay.setFixedWidth(300)
            self.enable_check = QtWidgets.QCheckBox("AFT BUS ENABLE")
            self.power_5v = QtWidgets.QCheckBox("5V RAIL")
            self.power_3v3 = QtWidgets.QCheckBox("CE RAIL")
            for control in (self.enable_check, self.power_5v, self.power_3v3):
                control.setToolTip("Pending command value. Telemetry refresh never changes this switch.")
                command_bay.body.addWidget(control)

            lamp_grid = QtWidgets.QGridLayout()
            lamp_grid.setSpacing(8)
            self.power_5v_lamp = StatusLamp("5V POWER", on_color="#39f07f", off_color="#153324")
            self.power_3v3_lamp = StatusLamp("CE POWER", on_color="#39f07f", off_color="#153324")
            self.alert_5v_lamp = StatusLamp("5V ALERT", on_color="#ff4d4d", off_color="#34161b")
            self.alert_3v3_lamp = StatusLamp("CE ALERT", on_color="#ff4d4d", off_color="#34161b")
            lamp_grid.addWidget(self.power_5v_lamp, 0, 0)
            lamp_grid.addWidget(self.power_3v3_lamp, 0, 1)
            lamp_grid.addWidget(self.alert_5v_lamp, 1, 0)
            lamp_grid.addWidget(self.alert_3v3_lamp, 1, 1)
            command_bay.body.addLayout(lamp_grid)

            self.enable_button = QtWidgets.QPushButton("Commit Enable")
            self.enable_button.clicked.connect(self.apply_enable)
            self.power_button = QtWidgets.QPushButton("Commit Power")
            self.power_button.clicked.connect(self.apply_power)
            self.configure_button = QtWidgets.QPushButton("\u2699  Configuration...")
            self.configure_button.clicked.connect(self.open_configuration)
            self.read_status_button = QtWidgets.QPushButton("Scan Telemetry")
            self.read_status_button.clicked.connect(self.read_status)
            self.clear_alert_button = QtWidgets.QPushButton("Clear Alerts")
            self.clear_alert_button.clicked.connect(self.clear_alerts)
            for button in (self.enable_button, self.power_button, self.configure_button,
                           self.read_status_button, self.clear_alert_button):
                button.setMinimumHeight(32)
                command_bay.body.addWidget(button)
            self.config_summary = QtWidgets.QLabel()
            self.config_summary.setWordWrap(True)
            self.config_summary.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.config_summary.setStyleSheet("color: #8ff0ff; font-size: 8pt; padding: 4px;")
            command_bay.body.addWidget(self.config_summary)
            command_bay.body.addStretch(1)
            self._update_config_summary()
            shell.addWidget(command_bay, 0)

            data_column = QtWidgets.QVBoxLayout()
            data_column.setSpacing(10)
            telemetry_bay = SectionBay("LIVE TELEMETRY")
            telemetry_grid = QtWidgets.QGridLayout()
            telemetry_grid.setHorizontalSpacing(10)
            telemetry_grid.setVerticalSpacing(8)
            for column, title in enumerate(("VOLTAGE", "CURRENT", "POWER")):
                heading = QtWidgets.QLabel(title)
                heading.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                heading.setStyleSheet("color: #f9c66f; font-size: 9pt; font-weight: 800; letter-spacing: 1px;")
                telemetry_grid.addWidget(heading, 0, column)
                telemetry_grid.setColumnStretch(column, 1)
            self.v5_display = TelemetryDisplay("5V", "V")
            self.i5_display = TelemetryDisplay("5V", "mA")
            self.p5_display = TelemetryDisplay("5V", "mW")
            self.v3_display = TelemetryDisplay("CE", "V")
            self.i3_display = TelemetryDisplay("CE", "mA")
            self.p3_display = TelemetryDisplay("CE", "mW")
            displays = (
                (self.v5_display, self.i5_display, self.p5_display),
                (self.v3_display, self.i3_display, self.p3_display),
            )
            for row, display_row in enumerate(displays, start=1):
                for column, widget in enumerate(display_row):
                    telemetry_grid.addWidget(widget, row, column)
            telemetry_bay.body.addLayout(telemetry_grid)
            data_column.addWidget(telemetry_bay, 0)

            graphs_bay = SectionBay("TREND ANALYSIS")
            graphs = QtWidgets.QHBoxLayout()
            graphs.setSpacing(10)
            self.voltage_graph = TrendGraph("VOLTAGE", "V", [("v5", "5V", "#8ff0ff"), ("v3", "CE", "#f9c66f")])
            self.current_graph = TrendGraph("CURRENT", "mA", [("i5", "5V", "#39f07f"), ("i3", "CE", "#ffb347")])
            self.power_graph = TrendGraph("POWER", "mW", [("p5", "5V", "#ff7b72"), ("p3", "CE", "#c792ea")])
            graphs.addWidget(self.voltage_graph, 1)
            graphs.addWidget(self.current_graph, 1)
            graphs.addWidget(self.power_graph, 1)
            graphs_bay.body.addLayout(graphs)
            data_column.addWidget(graphs_bay, 1)
            shell.addLayout(data_column, 1)

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

        def _update_config_summary(self) -> None:
            self.config_summary.setText(
                "Cutoff: 5V {:.0f} mA | CE {:.0f} mA\n"
                "Scale: 5V {:.0f} mA | CE {:.0f} mA".format(
                    self.config_values["max_current_5v_shutdown"] * 1000.0,
                    self.config_values["max_current_ce_shutdown"] * 1000.0,
                    self.config_values["max_current_5v_scale"] * 1000.0,
                    self.config_values["max_current_ce_scale"] * 1000.0,
                )
            )

        def read_config(self):
            resp = self._run("READ_BLOCK_CONFIG", lambda: self.client.read_block_config(self.afe))
            if resp is None or not resp.success:
                return None
            self.config_values.update({
                "r_shunt_5v": float(resp.r_shunt_5V),
                "r_shunt_ce": float(resp.r_shunt_3V3),
                "max_current_5v_scale": float(resp.max_current_5V_scale),
                "max_current_ce_scale": float(resp.max_current_3V3_scale),
                "max_current_5v_shutdown": float(resp.max_current_5V_shutdown),
                "max_current_ce_shutdown": float(resp.max_current_3V3_shutdown),
            })
            self._update_config_summary()
            return resp

        def open_configuration(self):
            # Start from the server's current values when available; otherwise
            # retain the last known/default values in this panel.
            self.read_config()
            dialog = ConfigurationDialog(self.afe, self.config_values, self)
            if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            previous = dict(self.config_values)
            candidate = dialog.values()
            self.config_values = candidate
            resp = self._run(
                "CONFIGURE_BLOCK",
                lambda: self.client.configure_block(
                    self.afe,
                    r_shunt_5v=candidate["r_shunt_5v"],
                    r_shunt_3v3=candidate["r_shunt_ce"],
                    max_current_5v_scale=candidate["max_current_5v_scale"],
                    max_current_3v3_scale=candidate["max_current_ce_scale"],
                    max_current_5v_shutdown=candidate["max_current_5v_shutdown"],
                    max_current_3v3_shutdown=candidate["max_current_ce_shutdown"],
                ),
            )
            if resp is None or not resp.success:
                self.config_values = previous
                self._update_config_summary()
                return
            # Hardware configuration deliberately forces both requests off.
            self.power_5v.setChecked(False)
            self.power_3v3.setChecked(False)
            self._update_config_summary()

        def apply_power(self):
            resp = self._run(
                "SET_POWER_STATES",
                lambda: self.client.set_power_states(
                    self.afe,
                    power_5v=self.power_5v.isChecked(),
                    power_3v3=self.power_3v3.isChecked(),
                ),
            )
            if resp is not None:
                self.power_5v.setChecked(bool(resp.power5V))
                self.power_3v3.setChecked(bool(resp.power3V3))

        def read_status(self, *, log_result: bool = True):
            resp = self._run("READ_STATUS", lambda: self.client.read_status(self.afe)) if log_result else self._read_status_silent()
            if resp is None:
                return
            # Polling is telemetry-only: it must never overwrite pending user
            # selections in the command controls.  Successful command replies
            # above are the sole source that synchronizes the checkboxes.
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
            self.voltage_graph.append_values({"v5": resp.measured_voltage5V, "v3": resp.measured_voltage3V3})
            self.current_graph.append_values({"i5": resp.measured_current5V, "i3": resp.measured_current3V3})
            self.power_graph.append_values({"p5": resp.measured_power5V, "p3": resp.measured_power3V3})
            if log_result:
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

        def clear_alerts(self):
            resp = self._run("CLEAR_ALERT_FLAG", lambda: self.client.clear_alert_flag(self.afe))
            if resp is not None:
                self.read_status()

        def _read_status_silent(self):
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.BusyCursor)
            try:
                return self.client.read_status(self.afe)
            except Exception as exc:
                self.log(f"[AFE {self.afe}] AUTO_REFRESH: ERROR {exc}")
                return None
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()

    class HDMezzControlApp(QtWidgets.QWidget):
        def __init__(self, client: HDMezzClient):
            super().__init__()
            self.client = client
            self.setWindowTitle("HD MEZZANINE CONTROL PANEL")
            self.resize(1720, 1040)
            self.setMinimumSize(1180, 760)
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

            controls = QtWidgets.QHBoxLayout()
            controls.setSpacing(8)
            self.auto_refresh = QtWidgets.QCheckBox("AUTO REFRESH - TELEMETRY ONLY")
            self.auto_refresh.setToolTip("Updates meters, alarms, and graphs. It never changes command switches.")
            self.auto_refresh.setChecked(False)
            self.auto_refresh_interval = QtWidgets.QSpinBox()
            self.auto_refresh_interval.setRange(250, 10000)
            self.auto_refresh_interval.setSingleStep(250)
            self.auto_refresh_interval.setValue(1000)
            self.auto_refresh_interval.setSuffix(" ms")
            self.refresh_now = QtWidgets.QPushButton("Refresh All")
            self.refresh_now.clicked.connect(self.refresh_all_now)
            controls.addWidget(self.auto_refresh)
            controls.addWidget(self.auto_refresh_interval)
            controls.addWidget(self.refresh_now)
            banner_layout.addLayout(controls)
            root.addWidget(banner)

            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll_host = QtWidgets.QWidget()
            scroll_layout = QtWidgets.QVBoxLayout(scroll_host)
            scroll_layout.setSpacing(12)
            self.panels = []
            for afe in range(5):
                panel = AFEPanel(afe, client, self.append_log)
                self.panels.append(panel)
                scroll_layout.addWidget(panel)
            scroll_layout.addStretch(1)
            scroll.setWidget(scroll_host)
            root.addWidget(scroll, 1)

            self.log = QtWidgets.QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setMaximumBlockCount(500)
            self.log.setPlaceholderText("Console traffic and telemetry scans will appear here.")
            self.log.setFixedHeight(160)
            root.addWidget(self.log)

            self.refresh_timer = QtCore.QTimer(self)
            self.refresh_timer.timeout.connect(self._auto_refresh_tick)
            self.auto_refresh.toggled.connect(self._toggle_auto_refresh)
            self.auto_refresh_interval.valueChanged.connect(self._update_refresh_interval)

            QtWidgets.QApplication.instance().aboutToQuit.connect(self.client.close)

        def append_log(self, text: str) -> None:
            ts = QtCore.QDateTime.currentDateTime().toString("HH:mm:ss")
            self.log.appendPlainText(f"{ts}  {text}")

        def refresh_all_now(self) -> None:
            for panel in self.panels:
                panel.read_status(log_result=False)

        def _auto_refresh_tick(self) -> None:
            if not self.auto_refresh.isChecked():
                return
            self.refresh_all_now()

        def _toggle_auto_refresh(self, enabled: bool) -> None:
            if enabled:
                self.refresh_timer.start(self.auto_refresh_interval.value())
            else:
                self.refresh_timer.stop()

        def _update_refresh_interval(self, interval_ms: int) -> None:
            if self.refresh_timer.isActive():
                self.refresh_timer.start(interval_ms)

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
                r_shunt_3v3=args.rshunt_ce,
                max_current_5v_scale=args.max_current_5v_scale,
                max_current_3v3_scale=args.max_current_ce_scale,
                max_current_5v_shutdown=args.max_current_5v_shutdown,
                max_current_3v3_shutdown=args.max_current_ce_shutdown,
            )
            print_config_response(resp)
            return 0 if resp.success else 2

        if args.command == "read-block-config":
            resp = client.read_block_config(args.afe)
            print_config_response(resp)
            return 0 if resp.success else 2

        if args.command == "set-power-states":
            resp = client.set_power_states(args.afe, power_5v=bool(int(args.power_5v)), power_3v3=bool(int(args.power_ce)))
            print(
                f"success={resp.success} afe={resp.afeBlock} power5V={int(resp.power5V)} "
                f"powerCE={int(resp.power3V3)} message='{resp.message}'"
            )
            return 0 if resp.success else 2

        if args.command == "read-status":
            resp = client.read_status(args.afe)
            print_status_response(resp)
            return 0 if resp.success else 2

        if args.command == "clear-alert-flag":
            resp = client.clear_alert_flag(args.afe)
            print(f"success={resp.success} afe={resp.afeBlock} message='{resp.message}'")
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

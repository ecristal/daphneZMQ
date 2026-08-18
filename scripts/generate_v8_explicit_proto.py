#!/usr/bin/env python3
"""Generate the explicit proposed-v8 DAPHNE telemetry wire contract.

Every DAPHNE-owned row in the Interface2 tag list becomes one named field in
BoardTelemetry.  Indexed hardware families use a typed repeated-entry message;
the measurement itself remains a statically typed Protobuf field.

The optional trace CSV is also the field-number ledger.  Once generated, an
existing NodeId pattern keeps its field number even if the workbook row order
changes. Retired fields remain in the ledger and are emitted as Protobuf
reservations. New fields receive the next number that has never been used.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

NODE_PREFIX = "nsu=urn:dune:pds:daphne;s="
BOARD_PREFIX = "DAPHNE.Boards.{BoardId}."
EXTERNAL_SUBSYSTEMS = {"Authority", "Endpoint Status", "OPC-UA Bridge"}
VALUE_TYPES = {
    "Boolean": "BooleanSample",
    "Integer": "IntegerSample",
    "Long": "LongSample",
    "Double": "DoubleSample",
    "String": "StringSample",
    "DateTime": "DateTimeSample",
}
TRACE_FIELDS = (
    "protobuf_field_number",
    "protobuf_field",
    "field_status",
    "protobuf_type",
    "repeated",
    "instance_fields",
    "opcua_node_pattern",
    "dcs_data_type",
    "engineering_unit",
    "data_source",
    "control_owner",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag_list", type=Path)
    parser.add_argument("proto", type=Path)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--expected-patterns", type=int, default=316)
    return parser.parse_args()


def snake_case(value: str) -> str:
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    if value and value[0].isdigit():
        value = "n_" + value
    return value


def pascal_case(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in snake_case(value).split("_"))


def proto_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def source_from_notes(notes: str) -> str:
    match = re.search(r"(?:^| \| )SOURCE=([^|]+)", notes)
    return match.group(1).strip() if match else "Interface2 proposed-v8 registry"


def read_rows(tag_list: Path) -> list[dict[str, str]]:
    with tag_list.open(newline="", encoding="utf-8-sig") as stream:
        rows = [
            row
            for row in csv.DictReader(stream)
            if row["DCS Access"] == "Read-Only"
            and row["Subsystem"] not in EXTERNAL_SUBSYSTEMS
        ]
    for row in rows:
        node_id = row["OPC-UA Node Address"]
        if not node_id.startswith(NODE_PREFIX + BOARD_PREFIX):
            raise ValueError(f"DAPHNE NodeId has unexpected prefix: {node_id}")
        if row["Data Type"] not in VALUE_TYPES:
            raise ValueError(f"unsupported value type: {row['Data Type']}")
    return rows


def load_field_ledger(trace: Path | None) -> dict[str, dict[str, str]]:
    if trace is None or not trace.exists():
        return {}
    with trace.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    ledger: dict[str, dict[str, str]] = {}
    for row in rows:
        row.setdefault("field_status", "Active")
        if row["field_status"] not in {"Active", "Retired"}:
            raise ValueError(
                f"field-number ledger has invalid status: {row['field_status']!r}"
            )
        pattern = row["opcua_node_pattern"]
        if pattern in ledger:
            raise ValueError(f"field-number ledger repeats NodeId pattern: {pattern}")
        ledger[pattern] = row
    numbers = [int(row["protobuf_field_number"]) for row in ledger.values()]
    if len(numbers) != len(set(numbers)):
        raise ValueError("field-number ledger contains duplicate field numbers")
    return ledger


def assign_field_numbers(
    rows: list[dict[str, str]], ledger: dict[str, dict[str, str]]
) -> dict[str, int]:
    assigned = {
        pattern: int(row["protobuf_field_number"]) for pattern, row in ledger.items()
    }
    next_number = max(assigned.values(), default=0) + 1
    for row in rows:
        pattern = row["OPC-UA Node Address"][len(NODE_PREFIX) :]
        if pattern in ledger and ledger[pattern]["field_status"] != "Active":
            raise ValueError(
                f"retired protobuf field requires explicit migration review: {pattern}"
            )
        if pattern not in assigned:
            assigned[pattern] = next_number
            next_number += 1
    active_numbers = [
        assigned[row["OPC-UA Node Address"][len(NODE_PREFIX) :]] for row in rows
    ]
    if len(active_numbers) != len(set(active_numbers)):
        raise ValueError("field-number ledger contains duplicate active numbers")
    return assigned


def field_name(pattern: str) -> str:
    suffix = pattern[len(BOARD_PREFIX) :]
    parts = [part for part in suffix.split(".") if not part.startswith("{")]
    return snake_case("_".join(parts))


def placeholders(pattern: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\{([^{}]+)\}", pattern[len(BOARD_PREFIX) :]))


def wrapper_name(indexes: tuple[str, ...], value_type: str) -> str:
    return "".join(pascal_case(index) for index in indexes) + value_type + "Reading"


def proto_header() -> list[str]:
    return [
        "// Generated by scripts/generate_v8_explicit_proto.py; do not edit manually.",
        "//",
        "// This is the authoritative DAPHNE board-service wire contract for the",
        "// proposed DAQ/PDS ICD v8. Every board-owned variable is a named, typed",
        "// field below. The OPC-UA bridge consumes these declarations; it does not",
        "// invent DAPHNE variable names, types, units, ownership, or semantics.",
        "//",
        "// Compatibility rules after release:",
        "//   * field numbers and enum values are append-only;",
        "//   * a missing reading means unavailable, never numeric zero;",
        "//   * indexed readings identify their hardware instance explicitly;",
        "//   * the field annotations are part of the reviewed interface contract.",
        "",
        'syntax = "proto3";',
        "",
        "package daphne.telemetry.v8;",
        "",
        'import "google/protobuf/descriptor.proto";',
        "",
        "extend google.protobuf.FieldOptions {",
        "  string opcua_node_pattern = 50001;",
        "  string engineering_unit = 50002;",
        "  string data_source = 50003;",
        "  string control_owner = 50004;",
        "}",
        "",
        "enum TelemetryQuality {",
        "  TELEMETRY_QUALITY_UNSPECIFIED = 0;",
        "  TELEMETRY_QUALITY_GOOD = 1;",
        "  TELEMETRY_QUALITY_STALE = 2;",
        "  TELEMETRY_QUALITY_INVALID = 3;",
        "  TELEMETRY_QUALITY_UNAVAILABLE = 4;",
        "  TELEMETRY_QUALITY_NOT_APPLICABLE = 5;",
        "}",
        "",
        "enum DiagnosticSeverity {",
        "  DIAGNOSTIC_SEVERITY_UNSPECIFIED = 0;",
        "  DIAGNOSTIC_SEVERITY_INFO = 1;",
        "  DIAGNOSTIC_SEVERITY_WARNING = 2;",
        "  DIAGNOSTIC_SEVERITY_ERROR = 3;",
        "  DIAGNOSTIC_SEVERITY_CRITICAL = 4;",
        "}",
        "",
        "message SampleMetadata {",
        "  TelemetryQuality quality = 1;",
        "  uint64 sample_time_unix_ns = 2;",
        "  uint64 sample_monotonic_ns = 3;",
        "  uint32 error_code = 4;",
        "  string detail = 5;",
        "}",
        "",
    ]


def sample_messages() -> list[str]:
    scalar_types = {
        "BooleanSample": "bool",
        "IntegerSample": "sint32",
        "LongSample": "sint64",
        "DoubleSample": "double",
        "StringSample": "string",
        "DateTimeSample": "sint64",
    }
    lines: list[str] = []
    for message, scalar in scalar_types.items():
        lines.extend(
            [
                f"message {message} {{",
                "  SampleMetadata metadata = 1;",
                "  oneof reading {",
                f"    {scalar} value = 2;",
                "  }",
                "}",
                "",
            ]
        )
    return lines


def indexed_messages(rows: list[dict[str, str]]) -> list[str]:
    combinations = sorted(
        {
            (
                placeholders(row["OPC-UA Node Address"][len(NODE_PREFIX) :]),
                row["Data Type"],
            )
            for row in rows
            if placeholders(row["OPC-UA Node Address"][len(NODE_PREFIX) :])
        },
        key=lambda item: (item[0], item[1]),
    )
    lines: list[str] = []
    for indexes, value_type in combinations:
        lines.append(f"message {wrapper_name(indexes, value_type)} {{")
        for number, index in enumerate(indexes, start=1):
            lines.append(f"  string {snake_case(index)} = {number};")
        lines.append(f"  {VALUE_TYPES[value_type]} sample = {len(indexes) + 1};")
        lines.extend(["}", ""])
    return lines


def board_message(
    rows: list[dict[str, str]],
    field_numbers: dict[str, int],
    ledger: dict[str, dict[str, str]],
) -> tuple[list[str], list[dict[str, str]]]:
    lines = ["message BoardTelemetry {"]
    trace_rows: list[dict[str, str]] = []
    seen_names: set[str] = set()
    active_patterns = {row["OPC-UA Node Address"][len(NODE_PREFIX) :] for row in rows}
    retired_rows = [
        row for pattern, row in ledger.items() if pattern not in active_patterns
    ]
    for retired in sorted(
        retired_rows, key=lambda row: int(row["protobuf_field_number"])
    ):
        number = int(retired["protobuf_field_number"])
        name = retired["protobuf_field"].removeprefix("BoardTelemetry.")
        seen_names.add(name)
        lines.append(f"  reserved {number};")
        lines.append(f'  reserved "{name}";')
    if retired_rows:
        lines.append("")
    for row in sorted(
        rows,
        key=lambda item: field_numbers[item["OPC-UA Node Address"][len(NODE_PREFIX) :]],
    ):
        pattern = row["OPC-UA Node Address"][len(NODE_PREFIX) :]
        indexes = placeholders(pattern)
        name = field_name(pattern)
        if name in seen_names:
            raise ValueError(f"duplicate generated protobuf field name: {name}")
        seen_names.add(name)
        number = field_numbers[pattern]
        sample_type = VALUE_TYPES[row["Data Type"]]
        protobuf_type = (
            wrapper_name(indexes, row["Data Type"]) if indexes else sample_type
        )
        repeated = "repeated " if indexes else ""
        source = source_from_notes(row["Notes"])
        if pattern in ledger:
            previous = ledger[pattern]
            stable_columns = {
                "protobuf_field": f"BoardTelemetry.{name}",
                "protobuf_type": protobuf_type,
                "repeated": "Yes" if indexes else "No",
                "instance_fields": ",".join(snake_case(index) for index in indexes),
                "dcs_data_type": row["Data Type"],
            }
            for column, value in stable_columns.items():
                if previous[column] != value:
                    raise ValueError(
                        f"released {column} changed for field {number}: "
                        f"{previous[column]!r} -> {value!r}"
                    )
        lines.extend(
            [
                f"  // {number:03d} | {row['Data Type']} | {pattern}",
                f"  {repeated}{protobuf_type} {name} = {number} [",
                f"    (opcua_node_pattern) = {proto_string(pattern)},",
                f"    (engineering_unit) = {proto_string(row['Eng Units'])},",
                f"    (data_source) = {proto_string(source)},",
                f"    (control_owner) = {proto_string(row['Control Owner'])}",
                "  ];",
                "",
            ]
        )
        trace_rows.append(
            {
                "protobuf_field_number": str(number),
                "protobuf_field": f"BoardTelemetry.{name}",
                "field_status": "Active",
                "protobuf_type": protobuf_type,
                "repeated": "Yes" if indexes else "No",
                "instance_fields": ",".join(snake_case(index) for index in indexes),
                "opcua_node_pattern": pattern,
                "dcs_data_type": row["Data Type"],
                "engineering_unit": row["Eng Units"],
                "data_source": source,
                "control_owner": row["Control Owner"],
            }
        )
    lines.append("}")
    lines.append("")
    for retired in retired_rows:
        retired = dict(retired)
        retired["field_status"] = "Retired"
        trace_rows.append(retired)
    trace_rows.sort(key=lambda row: int(row["protobuf_field_number"]))
    return lines, trace_rows


def protocol_messages() -> list[str]:
    return [
        "message ReadTelemetrySnapshotRequest {",
        "  // Every request returns the complete, explicitly declared BoardTelemetry.",
        "  uint64 request_sequence = 1;",
        "}",
        "",
        "message TelemetryDiagnostic {",
        "  DiagnosticSeverity severity = 1;",
        "  string component = 2;",
        "  uint32 code = 3;",
        "  string message = 4;",
        "  uint64 first_seen_time_unix_ns = 5;",
        "  uint64 last_seen_time_unix_ns = 6;",
        "  uint64 occurrence_count = 7;",
        "}",
        "",
        "message ReadTelemetrySnapshotResponse {",
        "  bool success = 1;",
        "  string message = 2;",
        "  uint32 schema_major = 3;",
        "  uint32 schema_minor = 4;",
        "  // SHA-256 of this canonical .proto source file used for the build.",
        "  string schema_source_sha256 = 5;",
        "  string contract_revision = 6;",
        "  string board_id = 7;",
        "  uint64 request_sequence = 8;",
        "  uint64 snapshot_sequence = 9;",
        "  uint64 snapshot_time_unix_ns = 10;",
        "  uint64 snapshot_monotonic_ns = 11;",
        "  bool wall_clock_synchronized = 12;",
        "  BoardTelemetry telemetry = 13;",
        "  repeated TelemetryDiagnostic diagnostics = 14;",
        "}",
    ]


def write_trace(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=TRACE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    rows = read_rows(args.tag_list)
    if len(rows) != args.expected_patterns:
        raise ValueError(f"expected {args.expected_patterns} patterns, got {len(rows)}")
    ledger = load_field_ledger(args.trace)
    field_numbers = assign_field_numbers(rows, ledger)
    board_lines, trace_rows = board_message(rows, field_numbers, ledger)
    lines = (
        proto_header()
        + sample_messages()
        + indexed_messages(rows)
        + board_lines
        + protocol_messages()
    )
    args.proto.parent.mkdir(parents=True, exist_ok=True)
    args.proto.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.trace is not None:
        write_trace(args.trace, trace_rows)
    print(
        f"patterns={len(rows)} fields={len(trace_rows)} "
        f"proto={args.proto} trace={args.trace or '-'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

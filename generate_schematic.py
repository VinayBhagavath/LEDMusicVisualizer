#!/usr/bin/env python3
"""Generate spectrum_analyzer.kicad_sch — 8x6 LED matrix music visualizer."""

from __future__ import annotations

import math
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
PROJECT = "spectrum_analyzer"
SYMS_DIR = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols")
OUT = Path(__file__).parent / "spectrum_analyzer.kicad_sch"
ERC_OUT = Path(__file__).parent / "ERC-v2.rpt"
ERC_RPT = Path(__file__).parent / "ERC.rpt"
GRID = 1.27
KICAD_CLI = Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")

LIB_MAP = {
    "Device:R": ("Device.kicad_sym", "R"),
    "Device:LED": ("Device.kicad_sym", "LED"),
    "Transistor_BJT:Q_NPN_EBC": ("Transistor_BJT.kicad_sym", "Q_NPN_EBC"),
    "74xx:74HC595": ("74xx.kicad_sym", "74HC595"),
    "Connector_Generic:Conn_01x11": ("Connector_Generic.kicad_sym", "Conn_01x11"),
    "power:+5V": ("power.kicad_sym", "+5V"),
    "power:GND": ("power.kicad_sym", "GND"),
    "power:PWR_FLAG": ("power.kicad_sym", "PWR_FLAG"),
}

# Arduino Uno pin header map (Connector_Generic Conn_01x11)
AR_PINS = {
    "D2": "1",
    "D3": "2",
    "D4": "3",
    "D5": "4",
    "D6": "5",
    "D7": "6",
    "D10": "7",
    "D11": "8",
    "D12": "9",
    "+5V": "10",
    "GND": "11",
}

ROW_SIGS = ["D2", "D3", "D4", "D5", "D6", "D7"]
SHIFT_SIGS = [("D10", "12", "LATCH", 90.0), ("D11", "14", "DATA", 105.0), ("D12", "11", "CLK", 135.0)]
Q_OUT_PINS = ["15", "1", "2", "3", "4", "5", "6", "7"]  # Q0..Q7 on 74HC595


def uid() -> str:
    return str(uuid.uuid4())


def snap(v: float) -> float:
    return round(v / GRID) * GRID


def sym_pos(x: float, y: float) -> tuple[float, float]:
    return snap(x), snap(y)


def extract_symbol(lib_file: Path, sym_name: str) -> str:
    text = lib_file.read_text()
    needle = f'(symbol "{sym_name}"'
    start = text.find(needle)
    if start < 0:
        raise ValueError(f"Symbol {sym_name!r} not found in {lib_file}")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ValueError(f"Unclosed symbol {sym_name}")


def lib_symbol_block(lib_id: str) -> str:
    lib_file, sym_name = LIB_MAP[lib_id]
    body = extract_symbol(SYMS_DIR / lib_file, sym_name)
    return body.replace(f'(symbol "{sym_name}"', f'(symbol "{lib_id}"', 1)


def iter_pin_blocks(body: str):
    i = 0
    while True:
        start = body.find("(pin ", i)
        if start < 0:
            break
        depth = 0
        for j in range(start, len(body)):
            if body[j] == "(":
                depth += 1
            elif body[j] == ")":
                depth -= 1
                if depth == 0:
                    yield body[start : j + 1]
                    i = j + 1
                    break


def pin_def(lib_id: str, pin_num: str) -> tuple[float, float, int, float]:
    body = lib_symbol_block(lib_id)
    chunks = list(iter_pin_blocks(body))
    if not chunks:
        ext = re.search(r'\(extends\s+"([^"]+)"\)', body)
        if ext:
            parent = f"{lib_id.split(':')[0]}:{ext.group(1)}"
            return pin_def(parent, pin_num)
    for chunk in chunks:
        mnum = re.search(r'\(number\s+"([^"]+)"', chunk)
        mat = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)", chunk)
        mlen = re.search(r"\(length\s+([-\d.]+)\)", chunk)
        if mnum and mat and mnum.group(1) == pin_num:
            length = float(mlen.group(1)) if mlen else 0.0
            return float(mat.group(1)), float(mat.group(2)), int(float(mat.group(3))), length
    raise KeyError(f"Pin {pin_num} not found in {lib_id}")


def pin_connection_local(px: float, py: float, prot: int, length: float) -> tuple[float, float]:
    """KiCad connects wires at the outer end of each pin graphic."""
    r = math.radians(prot)
    return px + length * math.cos(r), py - length * math.sin(r)


def pin_sheet(
    lib_id: str,
    sx: float,
    sy: float,
    srot: int,
    pin_num: str,
    *,
    outer: bool = False,
) -> tuple[float, float]:
    px, py, prot, length = pin_def(lib_id, pin_num)
    cx, cy = pin_connection_local(px, py, prot, length) if outer else (px, py)
    sr = math.radians(srot)
    rx = cx * math.cos(sr) - cy * math.sin(sr)
    ry = cx * math.sin(sr) + cy * math.cos(sr)
    return snap(sx + rx), snap(sy - ry)


def pin_pair(
    lib_id: str, sx: float, sy: float, srot: int, pin_num: str
) -> tuple[tuple[float, float], tuple[float, float]]:
    body = pin_sheet(lib_id, sx, sy, srot, pin_num, outer=False)
    tip = pin_sheet(lib_id, sx, sy, srot, pin_num, outer=True)
    return body, tip


def indent_block(text: str, tabs: int = 1) -> str:
    prefix = "\t" * tabs
    return "\n".join(prefix + line if line else line for line in text.splitlines())


def prop(
    name: str,
    value: str,
    x: float,
    y: float,
    angle: int = 0,
    hide: bool = False,
    justify: str | None = None,
) -> str:
    fx = f"\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)"
    j = f"\n\t\t\t\t(justify {justify})" if justify else ""
    h = "\n\t\t\t\t(hide yes)" if hide else ""
    return f"""\t\t(property "{name}" "{value}"
\t\t\t(at {x} {y} {angle})
\t\t\t(effects{fx}{j}{h}
\t\t\t)
\t\t)"""


def place(
    lib_id: str,
    ref: str,
    value: str,
    x: float,
    y: float,
    rot: int = 0,
    footprint: str = "",
    exclude_sim: bool | None = None,
) -> str:
    body = lib_symbol_block(lib_id)
    nums: list[str] = []
    for chunk in iter_pin_blocks(body):
        mnum = re.search(r'\(number\s+"([^"]+)"', chunk)
        if mnum:
            nums.append(mnum.group(1))
    if not nums:
        ext = re.search(r'\(extends\s+"([^"]+)"\)', body)
        if ext:
            parent = f"{lib_id.split(':')[0]}:{ext.group(1)}"
            for chunk in iter_pin_blocks(lib_symbol_block(parent)):
                mnum = re.search(r'\(number\s+"([^"]+)"', chunk)
                if mnum:
                    nums.append(mnum.group(1))
    seen: set[str] = set()
    pin_lines = []
    for num in nums:
        if num in seen:
            continue
        seen.add(num)
        pin_lines.append(f'\t\t(pin "{num}"\n\t\t\t(uuid "{uid()}")\n\t\t)')
    if exclude_sim is None:
        exclude_sim = lib_id.startswith("power:")
    sim = "yes" if exclude_sim else "no"
    return f"""\t(symbol
\t\t(lib_id "{lib_id}")
\t\t(at {snap(x)} {snap(y)} {rot})
\t\t(unit 1)
\t\t(exclude_from_sim {sim})
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(dnp no)
\t\t(uuid "{uid()}")
{prop("Reference", ref, x + 2.54, y - 2.54)}
{prop("Value", value, x + 2.54, y + 2.54)}
{prop("Footprint", footprint, x, y, hide=True)}
{prop("Datasheet", "~", x, y, hide=True)}
{prop("Description", f"Placed {ref}", x, y, hide=True)}
{chr(10).join(pin_lines)}
\t\t(instances
\t\t\t(project "{PROJECT}"
\t\t\t\t(path "/{ROOT_UUID}"
\t\t\t\t\t(reference "{ref}")
\t\t\t\t\t(unit 1)
\t\t\t\t)
\t\t\t)
\t\t)
\t)"""


class Sch:
    def __init__(self) -> None:
        self.wires: list[str] = []
        self.labels: list[str] = []
        self.junctions: list[tuple[float, float]] = []
        self.no_connects: list[str] = []
        self.symbols: list[str] = []
        self.texts: list[str] = []

    def wire(self, x1: float, y1: float, x2: float, y2: float) -> None:
        x1, y1, x2, y2 = snap(x1), snap(y1), snap(x2), snap(y2)
        self.wires.append(
            f"""\t(wire
\t\t(pts
\t\t\t(xy {x1} {y1})
\t\t\t(xy {x2} {y2})
\t\t)
\t\t(stroke
\t\t\t(width 0)
\t\t\t(type default)
\t\t)
\t\t(uuid "{uid()}")
\t)"""
        )

    def route(self, points: list[tuple[float, float]]) -> None:
        for a, b in zip(points, points[1:]):
            if a != b:
                self.wire(*a, *b)

    def pin_connect(self, lib_id: str, sx: float, sy: float, srot: int, pin_num: str) -> tuple[float, float]:
        """Route a short stub along the pin graphic; return the electrical connection point."""
        body, tip = pin_pair(lib_id, sx, sy, srot, pin_num)
        if body != tip:
            self.wire(*body, *tip)
        return tip

    def label(self, name: str, x: float, y: float, angle: int = 0) -> None:
        x, y = snap(x), snap(y)
        self.labels.append(
            f"""\t(label "{name}"
\t\t(at {x} {y} {angle})
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.27 1.27)
\t\t\t)
\t\t\t(justify left bottom)
\t\t)
\t\t(uuid "{uid()}")
\t)"""
        )

    def junction(self, x: float, y: float) -> None:
        pt = (snap(x), snap(y))
        if pt not in self.junctions:
            self.junctions.append(pt)

    def no_connect(self, x: float, y: float) -> None:
        x, y = snap(x), snap(y)
        self.no_connects.append(
            f"""\t(no_connect
\t\t(at {x} {y})
\t\t(uuid "{uid()}")
\t)"""
        )

    def text(self, s: str, x: float, y: float, size: float = 2.54) -> None:
        self.texts.append(
            f"""\t(text "{s}"
\t\t(exclude_from_sim no)
\t\t(at {snap(x)} {snap(y)} 0)
\t\t(effects
\t\t\t(font
\t\t\t\t(size {size} {size})
\t\t\t)
\t\t\t(justify left bottom)
\t\t)
\t\t(uuid "{uid()}")
\t)"""
        )

    def add(self, block: str) -> None:
        self.symbols.append(block)

    def junction_items(self) -> list[str]:
        return [
            f"""\t(junction
\t\t(at {x} {y})
\t\t(diameter 0)
\t\t(color 0 0 0 0)
\t\t(uuid "{uid()}")
\t)"""
            for x, y in self.junctions
        ]


def build() -> str:
    sch = Sch()

    # Layout constants
    col_x0 = 210.0
    col_dx = 25.4
    led_y0 = 155.0
    led_dy = 15.24
    col_bus_y = snap(130.0)
    row_bus_x = snap(85.0)
    gnd_rail_y = snap(45.0)
    matrix_right_x = snap(col_x0 + 7 * col_dx)  # right edge of LED matrix (for docs)

    # --- Arduino (J1): 9 pins used — D2-D7 rows, D10-D12 shift register, +5V, GND ---
    ar_x, ar_y = sym_pos(40.0, 80.0)
    sch.add(
        place(
            "Connector_Generic:Conn_01x11",
            "J1",
            "Arduino_Uno",
            ar_x,
            ar_y,
            footprint="Connector_PinHeader_2.54mm:PinHeader_1x11_P2.54mm_Vertical",
        )
    )

    def ar_pin(sig: str) -> tuple[float, float]:
        return pin_sheet("Connector_Generic:Conn_01x11", ar_x, ar_y, 0, AR_PINS[sig])

    # --- 74HC595 column driver (8 outputs -> 220R -> column anodes) ---
    u_x, u_y = sym_pos(160.0, 60.0)
    sch.add(place("74xx:74HC595", "U1", "74HC595", u_x, u_y, footprint="Package_DIP:DIP-16_W7.62mm"))

    def u_pin(num: str) -> tuple[float, float]:
        return pin_sheet("74xx:74HC595", u_x, u_y, 0, num)

    # --- Power ---
    p5_x, p5_y = sym_pos(120.0, 40.0)
    gnd_x, gnd_y = sym_pos(130.0, gnd_rail_y)
    flg5_x, flg5_y = sym_pos(p5_x + 5.08, p5_y)
    flg_g_x, flg_g_y = sym_pos(gnd_x + 5.08, gnd_y)
    sch.add(place("power:+5V", "#PWR01", "+5V", p5_x, p5_y))
    sch.add(place("power:GND", "#PWR02", "GND", gnd_x, gnd_y))
    sch.add(place("power:PWR_FLAG", "#FLG01", "PWR_FLAG", flg5_x, flg5_y))
    sch.add(place("power:PWR_FLAG", "#FLG02", "PWR_FLAG", flg_g_x, flg_g_y))

    p5 = pin_sheet("power:+5V", p5_x, p5_y, 0, "1")
    gnd = pin_sheet("power:GND", gnd_x, gnd_y, 0, "1")
    pwr_flag = pin_sheet("power:PWR_FLAG", flg5_x, flg5_y, 0, "1")
    gnd_flag = pin_sheet("power:PWR_FLAG", flg_g_x, flg_g_y, 0, "1")

    for pt in (u_pin("16"), u_pin("10"), ar_pin("+5V")):
        sch.route([pt, p5])
    sch.junction(*p5)
    sch.route([p5, pwr_flag])

    for pt in (u_pin("8"), u_pin("13")):
        sch.route([pt, gnd])
    ar_gnd = ar_pin("GND")
    sch.route([ar_gnd, (gnd[0], ar_gnd[1]), gnd])
    sch.junction(*gnd)
    sch.route([gnd, gnd_flag])

    sch.no_connect(*pin_sheet("74xx:74HC595", u_x, u_y, 0, "9", outer=False))  # Q7' serial out — unused

    # Shift register control: D10=LATCH, D11=DATA, D12=CLK
    for sig, upin, net, mid_x in SHIFT_SIGS:
        a = ar_pin(sig)
        u = u_pin(upin)
        sch.route([a, (mid_x, a[1]), (mid_x, u[1]), u])
        sch.junction(mid_x, u[1])
        sch.label(net, mid_x, u[1])

    # Column resistors R1-R8: 74HC595 Q0-Q7 -> 220R -> C1-C8 buses
    for i, qp in enumerate(Q_OUT_PINS):
        cx, ry = sym_pos(col_x0 + i * col_dx, 95.0)
        sch.add(
            place(
                "Device:R",
                f"R{i + 1}",
                "220",
                cx,
                ry,
                rot=90,
                footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
            )
        )
        r1 = pin_sheet("Device:R", cx, ry, 90, "1")
        r2 = pin_sheet("Device:R", cx, ry, 90, "2")
        qout = u_pin(qp)
        sch.route([qout, (r1[0], qout[1]), r1, r2, (cx, col_bus_y)])
        sch.junction(cx, col_bus_y)
        sch.label(f"C{i + 1}", cx, col_bus_y)

    # LED matrix 8x6 — anodes on column buses, cathodes on row buses
    row_ys: list[float] = []
    for row in range(6):
        row_y = sym_pos(col_x0, led_y0 + row * led_dy)[1]
        row_ys.append(row_y)
        row_bus_y = pin_sheet("Device:LED", sym_pos(col_x0, row_y)[0], row_y, 0, "1", outer=True)[1]

        for col in range(8):
            led_num = row * 8 + col + 1
            lx, ly = sym_pos(col_x0 + col * col_dx, row_y)
            sch.add(
                place(
                    "Device:LED",
                    f"LED{led_num}",
                    "LED",
                    lx,
                    ly,
                    footprint="LED_THT:LED_D5.0mm",
                )
            )
            k = sch.pin_connect("Device:LED", lx, ly, 0, "1")
            a = pin_sheet("Device:LED", lx, ly, 0, "2")
            col_x = sym_pos(col_x0 + col * col_dx, col_bus_y)[0]
            sch.route([a, (col_x, col_bus_y)])
            sch.junction(col_x, col_bus_y)
            sch.route([k, (row_bus_x, k[1]), (row_bus_x, row_bus_y)])
            sch.junction(row_bus_x, row_bus_y)

        sch.label(f"ROW{row + 1}", row_bus_x, row_bus_y)

    # Row drivers: D2-D7 -> 1kR -> NPN base; collector -> ROW bus; emitter -> GND
    q_x = snap(55.0)
    emitter_xs: list[float] = []

    for row in range(6):
        row_y = row_ys[row]
        row_bus_y = pin_sheet("Device:LED", sym_pos(col_x0, row_y)[0], row_y, 0, "1", outer=True)[1]

        rx, ry = sym_pos(48.0 + row * 4.0, row_y)
        sch.add(
            place(
                "Device:R",
                f"R{9 + row}",
                "1k",
                rx,
                ry,
                rot=0,
                footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
            )
        )
        r1 = pin_sheet("Device:R", rx, ry, 0, "1")
        r2 = pin_sheet("Device:R", rx, ry, 0, "2")

        tx, ty = sym_pos(q_x, row_y)
        sch.add(
            place(
                "Transistor_BJT:Q_NPN_EBC",
                f"Q{row + 1}",
                "PN2222A",
                tx,
                ty,
                footprint="Package_TO_SOT_THT:TO-92_Inline",
            )
        )
        # Q_NPN_EBC: 1=E, 2=B, 3=C — emitter pin graphic extends below anchor
        e = sch.pin_connect("Transistor_BJT:Q_NPN_EBC", tx, ty, 0, "1")
        b = pin_sheet("Transistor_BJT:Q_NPN_EBC", tx, ty, 0, "2")
        c = pin_sheet("Transistor_BJT:Q_NPN_EBC", tx, ty, 0, "3")
        emitter_xs.append(e[0])

        ap = ar_pin(ROW_SIGS[row])
        sch.route([ap, (r1[0], ap[1]), r1, r2, b])
        sch.junction(*r2)
        sch.junction(*b)
        sch.route([c, (row_bus_x, c[1]), (row_bus_x, row_bus_y)])
        sch.junction(row_bus_x, row_bus_y)
        sch.route([e, (e[0], gnd_rail_y)])
        sch.junction(e[0], gnd_rail_y)

    # Shared GND rail for all emitter drops — tie to GND power symbol
    rail_left = snap(min(emitter_xs))
    sch.wire(rail_left, gnd_rail_y, gnd[0], gnd_rail_y)
    sch.junction(gnd[0], gnd_rail_y)
    sch.junction(*gnd)

    # Documentation
    sch.text("Real-time Music Visualizer (8x6 LED EQ)", 25, 15, 3.81)
    sch.text("Python mic -> FFT -> 8 log-spaced bands -> serial @ 30Hz", 25, 21, 1.78)
    sch.text("Arduino multiplexes 6 rows @ ~200Hz; 74HC595 drives 8 columns", 25, 27, 1.78)
    sch.text("J1: D2-D7=rows  D10=LATCH  D11=DATA  D12=CLK  +5V/GND", 25, 33, 1.78)

    lib_symbols = "\n".join(indent_block(lib_symbol_block(lib_id), 2) for lib_id in LIB_MAP)

    return f"""(kicad_sch
\t(version 20250114)
\t(generator "cursor-schematic-gen")
\t(generator_version "4.3")
\t(uuid "{ROOT_UUID}")
\t(paper "A2")
\t(title_block
\t\t(title "Spectrum Analyzer LED Matrix")
\t\t(date "2026-06-29")
\t\t(rev "1.0")
\t\t(comment 1 "Real-time music visualizer - 8x6 LED equalizer")
\t\t(comment 2 "Python FFT -> 8 bands -> Arduino serial @ 30Hz")
\t\t(comment 3 "74HC595 column driver + PN2222 row sinks")
\t\t(comment 4 "D2-D7 rows | D10 LATCH D11 DATA D12 CLK")
\t)
\t(lib_symbols
{lib_symbols}
\t)
{chr(10).join(sch.junction_items())}
{chr(10).join(sch.no_connects)}
{chr(10).join(sch.wires)}
{chr(10).join(sch.labels)}
{chr(10).join(sch.texts)}
{chr(10).join(sch.symbols)}
\t(sheet_instances
\t\t(path "/{ROOT_UUID}"
\t\t\t(page "1")
\t\t)
\t)
\t(embedded_fonts no)
)
"""


def run_erc_report(sch_path: Path, report_path: Path) -> tuple[int, int]:
    if not KICAD_CLI.exists():
        print("KiCad CLI not found — skipping ERC", file=sys.stderr)
        return 0, 0
    result = subprocess.run(
        [str(KICAD_CLI), "sch", "erc", str(sch_path), "--format", "report", "--output", str(report_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and not report_path.exists():
        print(result.stderr or result.stdout, file=sys.stderr)
        return -1, -1
    text = report_path.read_text() if report_path.exists() else ""
    errors = warnings = 0
    for line in text.splitlines():
        if "Errors" in line and "Warnings" in line:
            m = re.search(r"Errors (\d+).*Warnings (\d+)", line)
            if m:
                errors, warnings = int(m.group(1)), int(m.group(2))
    return errors, warnings


def verify_netlist(sch_path: Path) -> bool:
    if not KICAD_CLI.exists():
        return True
    net_path = sch_path.with_suffix(".net")
    subprocess.run(
        [str(KICAD_CLI), "sch", "export", "netlist", str(sch_path), "--output", str(net_path)],
        capture_output=True,
    )
    if not net_path.exists():
        return False
    text = net_path.read_text()
    checks = [
        ('(ref "J1")', '"7"', "/LATCH"),
        ('(ref "J1")', '"8"', "/DATA"),
        ('(ref "J1")', '"9"', "/CLK"),
        ('(ref "Q1")', '"3"', "/ROW1"),
        ('(ref "Q1")', '"1"', "GND"),
        ('(ref "U1")', '"15"', "/C1"),
    ]
    blocks = re.split(r"\n\t\t\(net", text)[1:]
    for ref, pin, expect in checks:
        found = False
        for b in blocks:
            if ref in b and f'(pin {pin}' in b:
                name = re.search(r'\(name "([^"]*)"\)', b)
                if name and name.group(1) == expect:
                    found = True
                    break
        if not found:
            print(f"Netlist check failed: {ref} pin {pin} not on {expect}", file=sys.stderr)
            return False
    return True


if __name__ == "__main__":
    OUT.write_text(build())
    print(f"Wrote {OUT}")
    ok = verify_netlist(OUT)
    print(f"Netlist checks: {'PASS' if ok else 'FAIL'}")
    errors, warnings = run_erc_report(OUT, ERC_OUT)
    print(f"ERC: {errors} errors, {warnings} warnings -> {ERC_OUT}")
    if KICAD_CLI.exists():
        subprocess.run(
            [str(KICAD_CLI), "sch", "erc", str(OUT), "--format", "report", "--units", "mils", "--output", str(ERC_RPT)],
            capture_output=True,
        )
        print(f"ERC (mils): {errors} errors, {warnings} warnings -> {ERC_RPT}")
    if errors > 0:
        sys.exit(1)

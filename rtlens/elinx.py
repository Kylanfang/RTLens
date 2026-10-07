"""eLinx 集成模块：IP 核原语 stub + 约束文件解析。

- 内置常见 eLinx GTP 原语的 stub 定义（仅端口声明，供 LSP 符号解析用）
- 支持用户自定义 stub 文件加载（放 elinx_stubs/*.v）
- SDC / XDC / PCF 约束文件解析：信号 → 物理引脚映射
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .parser import parse, ParseResult


# eLinx 常见 GTP 原语 stub（基于公开文档的端口名，用户可自行修正）
ELINX_STUBS = {
    "GTP_PLL": """
module GTP_PLL #(
    parameter FCLK = "100",
    parameter DUTY = "50",
    parameter CLKOS = "DISABLE",
    parameter CLKOK = "DISABLE",
    parameter DYN_FLAG = "STATIC",
    parameter MODE = "NORMAL",
    parameter PMUX_SEL = "0",
    parameter DPDZ_SEL = "0",
    parameter CLKOS_DIV = 8,
    parameter CLKOK_DIV = 8,
    parameter CLKI_DIV = 1,
    parameter PHASE_ADJUST = "DISABLE",
    parameter PHASE_DELAY = "DISABLE",
    parameter PHASE_DELAY_VALUE = 0,
    parameter PHASE_ADJUST_VALUE = 0,
    parameter DEVATION = "DISABLE",
    parameter SSC_EN = "DISABLE",
    parameter SSC_CENTER = "0.4",
    parameter SSC_DEPTH = 8,
    parameter SSC_FREQ = 31
) (
    input CLKIN,
    input CLKFB,
    input RESET,
    input CLKFBSEL,
    input USDYPHS,
    input USDYSTEP,
    input DPDYSTEP,
    input DSDDYSTEP,
    input PSDYSTEP,
    input XSEL,
    input PHASEBWD,
    input PSDWEN,
    input PSDN,
    input DEVIATION,
    input SSCDPHSEL,
    input RESET_PSD,
    input CLKSEL,
    input CLKSWITCH,
    output CLKOP,
    output CLKOS,
    output CLKOK,
    output LOCK,
    output CLKLoss
);
endmodule
""",
    "GTP_CLKBUF": """
module GTP_CLKBUF (
    input I,
    output O
);
endmodule
""",
    "GTP_IOBUF": """
module GTP_IOBUF (
    input I,
    input T,
    output O,
    inout IO
);
endmodule
""",
    "GTP_DPRAM": """
module GTP_DPRAM #(
    parameter WR_DATA_WIDTH = 8,
    parameter RD_DATA_WIDTH = 8,
    parameter WR_ADDR_WIDTH = 10,
    parameter RD_ADDR_WIDTH = 10,
    parameter WR_MODE = "NORMAL",
    parameter RD_MODE = "NORMAL",
    parameter MEM_TYPE = "AUTO"
) (
    input WRCLK,
    input WRCLRN,
    input WREN,
    input WRWEN,
    input [WR_ADDR_WIDTH-1:0] WRADDR,
    input [WR_DATA_WIDTH-1:0] WRDATA,
    input RDCLK,
    input RDCLRN,
    input RDEN,
    input [RD_ADDR_WIDTH-1:0] RDADDR,
    output [RD_DATA_WIDTH-1:0] RDDATA
);
endmodule
""",
    "GTP_SPRAM": """
module GTP_SPRAM #(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 10,
    parameter MODE = "NORMAL",
    parameter MEM_TYPE = "AUTO"
) (
    input CLK,
    input CLRN,
    input WEN,
    input [ADDR_WIDTH-1:0] ADDR,
    input [DATA_WIDTH-1:0] WDATA,
    output [DATA_WIDTH-1:0] RDATA
);
endmodule
""",
    "GTP_ROM": """
module GTP_ROM #(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 10,
    parameter INIT_FILE = ""
) (
    input CLK,
    input [ADDR_WIDTH-1:0] ADDR,
    output [DATA_WIDTH-1:0] DATA
);
endmodule
""",
    "GTP_LUT": """
module GTP_LUT #(
    parameter INIT = 16'h0000,
    parameter EQN = "0"
) (
    input I0, I1, I2, I3,
    output O
);
endmodule
""",
    "GTP_DFF": """
module GTP_DFF #(
    parameter REGSET = "SET",
    parameter CLKMUX = "CLK",
    parameter CEMUX = "CE",
    parameter LSMUX = "LS",
    parameter SRMUX = "SR",
    parameter SRMODE = "ASYNC",
    parameter CEUSED = "ENABLE"
) (
    input CLK, CE, LS, SR,
    input D,
    output Q
);
endmodule
""",
    "GTP_AND2": "module GTP_AND2(input I0, I1, output O); endmodule",
    "GTP_OR2": "module GTP_OR2(input I0, I1, output O); endmodule",
    "GTP_XOR2": "module GTP_XOR2(input I0, I1, output O); endmodule",
    "GTP_INV": "module GTP_INV(input I, output O); endmodule",
    "GTP_MUX2": "module GTP_MUX2(input I0, I1, S0, output O); endmodule",
    "GTP_BUF": "module GTP_BUF(input I, output O); endmodule",
}


@dataclass
class PinConstraint:
    signal: str
    pin: str
    iostandard: str = ""
    drive: str = ""
    slew: str = ""
    pullup: bool = False
    pulldown: bool = False
    file: str = ""
    line: int = 0


class ELinxSupport:
    """eLinx IP stub 加载 + 约束文件解析。"""

    def __init__(self, stub_dir: Optional[str] = None):
        self.stub_modules: Dict[str, ParseResult] = {}
        self.constraints: List[PinConstraint] = []
        self._signal_to_pin: Dict[str, PinConstraint] = {}
        # 加载内置 stub
        self._load_builtin_stubs()
        # 加载用户 stub 目录
        if stub_dir and os.path.isdir(stub_dir):
            self._load_stub_dir(stub_dir)

    def _load_builtin_stubs(self):
        for name, code in ELINX_STUBS.items():
            result = parse(code)
            self.stub_modules[name] = result

    def _load_stub_dir(self, dirpath: str):
        for fn in os.listdir(dirpath):
            if fn.endswith((".v", ".sv")):
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    result = parse(text)
                    for mod in result.modules:
                        self.stub_modules[mod.name] = result
                except OSError:
                    pass

    def is_known_primitive(self, name: str) -> bool:
        return name in self.stub_modules

    def get_stub_ports(self, name: str) -> List:
        result = self.stub_modules.get(name)
        if not result or not result.modules:
            return []
        return result.modules[0].ports

    def parse_constraint_file(self, path: str):
        """解析约束文件（XDC / SDC / PCF 格式均可尝试）。"""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            return
        for i, line in enumerate(lines):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self._parse_constraint_line(line, path, i)

    def _parse_constraint_line(self, line: str, file: str, lineno: int):
        # XDC 风格：set_property PACKAGE_PIN A1 [get_ports clk]
        m = re.match(r'set_property\s+PACKAGE_PIN\s+(\S+)\s+\[get_ports\s+(\w+)\]', line, re.IGNORECASE)
        if m:
            pin, sig = m.group(1), m.group(2)
            c = PinConstraint(signal=sig, pin=pin, file=file, line=lineno)
            self._add_constraint(c)
            return
        # XDC IOSTANDARD
        m = re.match(r'set_property\s+IOSTANDARD\s+(\S+)\s+\[get_ports\s+(\w+)\]', line, re.IGNORECASE)
        if m:
            std, sig = m.group(1), m.group(2)
            c = self._signal_to_pin.get(sig)
            if c:
                c.iostandard = std
            else:
                c = PinConstraint(signal=sig, pin="", iostandard=std, file=file, line=lineno)
                self._signal_to_pin[sig] = c
            self.constraints.append(c) if c not in self.constraints else None
            return
        # PCF 风格：set_io signal pin
        m = re.match(r'set_io\s+(\w+)\s+(\S+)', line, re.IGNORECASE)
        if m:
            sig, pin = m.group(1), m.group(2)
            c = PinConstraint(signal=sig, pin=pin, file=file, line=lineno)
            self._add_constraint(c)
            return
        # Vivado 风格：set_property -dict {PACKAGE_PIN A1 IOSTANDARD LVCMOS33} [get_ports clk]
        m = re.match(r'set_property\s+-dict\s+\{\s*PACKAGE_PIN\s+(\S+)\s+IOSTANDARD\s+(\S+)\s*\}\s+\[get_ports\s+(\w+)\]', line, re.IGNORECASE)
        if m:
            pin, std, sig = m.group(1), m.group(2), m.group(3)
            c = PinConstraint(signal=sig, pin=pin, iostandard=std, file=file, line=lineno)
            self._add_constraint(c)
            return

    def _add_constraint(self, c: PinConstraint):
        self._signal_to_pin[c.signal] = c
        self.constraints.append(c)

    def get_pin(self, signal: str) -> Optional[PinConstraint]:
        return self._signal_to_pin.get(signal)

    def get_all_constraints(self) -> List[PinConstraint]:
        return list(self.constraints)

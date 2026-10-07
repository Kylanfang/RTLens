"""ServerConfig — LSP 服务器配置管理。

支持从字典加载配置（camelCase 键名兼容），提供诊断、补全、索引、格式化等子配置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set


@dataclass
class DiagnosticsConfig:
    enable: bool = True
    max_items: int = 100
    disabled: Set[str] = field(default_factory=set)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DiagnosticsConfig":
        if not d:
            return cls()
        return cls(
            enable=d.get("enable", True),
            max_items=int(d.get("maxItems", d.get("max_items", 100))),
            disabled=set(d.get("disabled", [])),
        )

    def should_run(self, source: str) -> bool:
        """是否对该来源运行诊断。"""
        if not self.enable:
            return False
        if source in self.disabled:
            return False
        return True


@dataclass
class CompletionConfig:
    snippets: bool = True

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CompletionConfig":
        if not d:
            return cls()
        return cls(snippets=d.get("snippets", True))


@dataclass
class IndexingConfig:
    auto_index: bool = True

    @property
    def autoIndex(self) -> bool:
        return self.auto_index

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IndexingConfig":
        if not d:
            return cls()
        return cls(auto_index=d.get("autoIndex", d.get("auto_index", True)))


@dataclass
class FormattingConfig:
    style: str = "k&r"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FormattingConfig":
        if not d:
            return cls()
        return cls(style=d.get("style", "k&r"))


class ServerConfig:
    """LSP 服务器配置根对象。"""

    def __init__(self):
        self.diagnostics = DiagnosticsConfig()
        self.completion = CompletionConfig()
        self.indexing = IndexingConfig()
        self.formatting = FormattingConfig()
        self.logLevel: str = "info"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServerConfig":
        cfg = cls()
        root = data.get("rtlens", data) if data else {}
        if not root:
            return cfg
        if "diagnostics" in root:
            cfg.diagnostics = DiagnosticsConfig.from_dict(root["diagnostics"])
        if "completion" in root:
            cfg.completion = CompletionConfig.from_dict(root["completion"])
        if "indexing" in root:
            cfg.indexing = IndexingConfig.from_dict(root["indexing"])
        if "formatting" in root:
            cfg.formatting = FormattingConfig.from_dict(root["formatting"])
        if "logLevel" in root:
            cfg.logLevel = root["logLevel"]
        return cfg

    def should_diagnostic(self, source: str) -> bool:
        """是否对指定来源运行诊断。"""
        return self.diagnostics.should_run(source)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rtlens": {
                "diagnostics": {
                    "enable": self.diagnostics.enable,
                    "maxItems": self.diagnostics.max_items,
                    "disabled": list(self.diagnostics.disabled),
                },
                "completion": {"snippets": self.completion.snippets},
                "indexing": {"autoIndex": self.indexing.auto_index},
                "formatting": {"style": self.formatting.style},
                "logLevel": self.logLevel,
            }
        }

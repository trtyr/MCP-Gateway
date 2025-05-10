"""
定义项目特定的异常类。
Defines project-specific exception classes.
"""
from typing import Optional


class BridgeBaseError(Exception):
    """MCP 桥接服务器所有自定义异常的基类。"""
    pass


class ConfigurationError(BridgeBaseError):
    """表示加载或验证配置文件时发生错误。"""
    pass


class BackendServerError(BridgeBaseError):
    """
    表示与后端 MCP 服务器交互时发生错误，
    或者后端服务器本身报告了一个错误。
    """

    def __init__(self,
                 message: str,
                 svr_name: Optional[str] = None,
                 orig_exc: Optional[Exception] = None):
        self.svr_name = svr_name
        self.orig_exc = orig_exc

        full_msg = f"后端服务器错误"
        if svr_name:
            full_msg += f" (服务器: {svr_name})"
        full_msg += f": {message}"
        if orig_exc:
            full_msg += f" (原始错误: {type(orig_exc).__name__})"
        super().__init__(full_msg)


class CapabilityConflictError(BridgeBaseError):
    """
    表示在聚合来自不同后端的 capabilities (能力) 时发生名称冲突。
    """

    def __init__(self, cap_name: str, svr1_name: str, svr2_name: str):

        message = (
            f"能力名称冲突: '{cap_name}' 同时由服务器 '{svr1_name}' 和 '{svr2_name}' 提供。"
            " 请确保服务器名称或能力前缀唯一，或配置冲突解决策略。")
        super().__init__(message)

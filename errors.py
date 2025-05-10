"""
定义项目特定的异常类。
Defines project-specific exception classes.
"""
from typing import Optional, Type  


class BridgeBaseError(Exception):
    """项目所有自定义异常的基类。
    Base class for all custom exceptions in this project."""
    pass


class ConfigurationError(BridgeBaseError):
    """表示加载或验证配置文件时发生错误。
    Indicates an error during loading or validation of the configuration file."""
    pass


class BackendServerError(BridgeBaseError):
    """表示与后端MCP服务器交互时发生错误，或者后端服务器报告了一个错误。
    Indicates an error during interaction with a backend MCP server,
    or an error reported by the backend server itself."""

    def __init__(self,
                 message: str,
                 server_name: Optional[str] = None,
                 original_exception: Optional[Exception] = None):
        self.server_name = server_name
        self.original_exception = original_exception
        full_message = f"后端服务器错误"  
        if server_name:
            full_message += f" (服务器: {server_name})"  
        full_message += f": {message}"
        if original_exception:
            full_message += f" (原始错误: {type(original_exception).__name__})"  
        super().__init__(full_message)


class CapabilityConflictError(BridgeBaseError):
    """表示在聚合来自不同后端的 capabilities 时发生名称冲突。
    Indicates a name conflict when aggregating capabilities from different backends."""

    def __init__(self, capability_name: str, server1_name: str,
                 server2_name: str):
        message = (
            f"能力名称冲突: '{capability_name}' 同时由服务器 '{server1_name}' 和 '{server2_name}' 提供。"  
            " 请确保服务器名称或能力前缀唯一。"  
        )
        super().__init__(message)

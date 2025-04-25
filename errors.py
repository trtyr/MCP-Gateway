"""
定义项目特定的异常类。
"""


class ConfigurationError(Exception):
    """表示加载或验证配置文件时发生错误。"""
    pass


class BackendServerError(Exception):
    """表示与后端MCP服务器交互时发生错误。"""
    pass

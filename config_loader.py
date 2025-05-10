import json
import os
from typing import Dict, List, Optional, Any, Union  

from mcp import StdioServerParameters
from errors import ConfigurationError

import logging  

logger = logging.getLogger(__name__)


def _validate_string_list(data: Any, field_name: str,
                          server_name: str) -> List[str]:
    """Helper to validate a list of strings."""
    if not isinstance(data, list):
        raise ConfigurationError(
            f"服务器 '{server_name}' 的 '{field_name}' 必须是一个字符串列表。"  
        )
    validated_list: List[str] = []
    for i, item in enumerate(data):
        if not isinstance(item, str):
            raise ConfigurationError(
                f"服务器 '{server_name}' 的 '{field_name}' 列表的第 {i+1} 个元素必须是字符串。"  
            )
        validated_list.append(item)
    return validated_list


def _validate_string_dict(data: Any, field_name: str,
                          server_name: str) -> Dict[str, str]:
    """Helper to validate a dictionary of string to string."""
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"服务器 '{server_name}' 的 '{field_name}' 必须是一个 JSON 对象 (键值均为字符串的字典)。"  
        )
    validated_dict: Dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise ConfigurationError(
                f"服务器 '{server_name}' 的 '{field_name}' 字典的键必须是字符串。"  
            )
        if not isinstance(value, str):
            raise ConfigurationError(
                f"服务器 '{server_name}' 的 '{field_name}' 字典的值 (键: '{key}') 必须是字符串。"  
            )
        validated_dict[key] = value
    return validated_dict


def load_and_validate_config(config_path: str) -> Dict[str, Dict[str, Any]]:
    logger.debug(f"开始加载配置文件: {config_path}")  
    if not os.path.exists(config_path):
        logger.error(f"配置文件未找到: {config_path}")  
        raise ConfigurationError(
            f"配置文件不存在: {config_path}")  

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"无法解析 JSON 配置文件 '{config_path}': {e}",
                     exc_info=True)  
        raise ConfigurationError(f"无法解析 JSON 配置文件: {config_path}, 错误: {e}")
    except Exception as e:  
        logger.error(f"读取配置文件 '{config_path}' 时发生意外错误: {e}",
                     exc_info=True)  
        raise ConfigurationError(f"读取配置文件时发生意外错误: {config_path}, 错误: {e}")

    if not isinstance(data, dict):
        logger.error("配置文件顶层必须是一个 JSON 对象 (字典)。"
                     )  
        raise ConfigurationError("配置文件顶层必须是一个 JSON 对象 (字典)。")

    validated_config: Dict[str, Dict[str, Any]] = {}
    logger.debug(f"找到 {len(data)} 个服务器配置条目进行验证。"
                 )  

    for server_name, server_conf_any in data.items():
        if not isinstance(server_name, str) or not server_name.strip():
            logger.error(f"配置中发现无效的服务器名称: '{server_name}'。名称必须是非空字符串。"
                         )  
            raise ConfigurationError(
                f"无效的服务器名称 '{server_name}'。名称必须是非空字符串。")  

        server_name = server_name.strip()  

        if not isinstance(server_conf_any, dict):
            logger.error(
                f"服务器 '{server_name}' 的配置必须是一个 JSON 对象。实际类型: {type(server_conf_any)}"
            )  
            raise ConfigurationError(
                f"服务器 '{server_name}' 的配置必须是一个 JSON 对象 (字典)。")
        server_conf: Dict[str, Any] = server_conf_any  

        server_type = server_conf.get("type")
        if not isinstance(server_type, str) or server_type not in [
                "stdio", "sse"
        ]:
            logger.error(
                f"服务器 '{server_name}' 的 'type' 字段无效或缺失。必须是 'stdio' 或 'sse'。得到: {server_type}"
            )  
            raise ConfigurationError(
                f"服务器 '{server_name}' 的配置缺少必需的 'type' 字段，或者其值不是 'stdio' 或 'sse'。"
            )

        logger.debug(f"正在验证服务器 '{server_name}' (类型: {server_type})"
                     )  

        if server_type == "stdio":
            command = server_conf.get("command")
            if not isinstance(command, str) or not command.strip():
                raise ConfigurationError(
                    f"Stdio 服务器 '{server_name}' 的 'command' 必须是一个非空字符串。"  
                )

            args: List[str] = []
            if "args" in server_conf:
                args = _validate_string_list(server_conf["args"], "args",
                                             server_name)

            env: Optional[Dict[str, str]] = None
            if "env" in server_conf and server_conf[
                    "env"] is not None:  
                env = _validate_string_dict(server_conf["env"], "env",
                                            server_name)

            try:
                
                server_params = StdioServerParameters(command=command.strip(),
                                                      args=args,
                                                      env=env)
                validated_config[server_name] = {
                    "type": "stdio",
                    "params": server_params
                }
            except Exception as e:  
                logger.error(
                    f"为 Stdio 服务器 '{server_name}' 创建 StdioServerParameters 时出错: {e}",
                    exc_info=True
                )  
                raise ConfigurationError(
                    f"为 Stdio 服务器 '{server_name}' 创建 StdioServerParameters 时出错: {e}"
                )

        elif server_type == "sse":
            server_url = server_conf.get("url")
            if not isinstance(server_url, str) or not server_url.strip():
                raise ConfigurationError(
                    f"SSE 服务器 '{server_name}' 的 'url' 必须是一个非空字符串。"  
                )
            server_url = server_url.strip()
            if not server_url.startswith(("http://", "https://")):
                raise ConfigurationError(
                    f"SSE 服务器 '{server_name}' 的 'url' ('{server_url}') 看起来不是一个有效的 HTTP/HTTPS URL。"  
                )

            validated_entry: Dict[str, Any] = {
                "type": "sse",
                "url": server_url
            }

            if "command" in server_conf:  
                sse_command = server_conf.get("command")
                if not isinstance(sse_command, str) or not sse_command.strip():
                    raise ConfigurationError(
                        f"SSE 服务器 '{server_name}' 的 'command' (用于本地启动) 必须是一个非空字符串。"  
                    )
                validated_entry['command'] = sse_command.strip()

                sse_args: List[str] = []
                if "args" in server_conf:
                    sse_args = _validate_string_list(server_conf["args"],
                                                     "args", server_name)
                validated_entry['args'] = sse_args  

                sse_env: Optional[Dict[str, str]] = None
                if "env" in server_conf and server_conf["env"] is not None:
                    sse_env = _validate_string_dict(server_conf["env"], "env",
                                                    server_name)
                validated_entry['env'] = sse_env  

            validated_config[server_name] = validated_entry
        logger.debug(f"服务器 '{server_name}' 配置验证通过。"
                     )  

    logger.info(
        f"配置文件 '{config_path}' 加载和验证成功。共处理 {len(validated_config)} 个有效的服务器配置。"
    )  
    return validated_config

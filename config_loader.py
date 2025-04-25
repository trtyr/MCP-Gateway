import json
import os
from typing import Dict, List, Optional, Any

from mcp import StdioServerParameters

from errors import ConfigurationError


def load_and_validate_config(config_path: str) -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(config_path):
        raise ConfigurationError(f"配置文件不存在: {config_path}")

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigurationError(f"无法解析 JSON 配置文件: {config_path}, 错误: {e}")
    except Exception as e:
        raise ConfigurationError(f"读取配置文件时发生意外错误: {config_path}, 错误: {e}")

    if not isinstance(data, dict):
        raise ConfigurationError("配置文件顶层必须是一个 JSON 对象 (字典)。")

    validated_config: Dict[str, Dict[str, Any]] = {}

    for server_name, server_conf in data.items():
        if not isinstance(server_name, str) or not server_name:
            raise ConfigurationError(f"无效的服务器名称 '{server_name}'。名称必须是非空字符串。")

        if not isinstance(server_conf, dict):
            raise ConfigurationError(
                f"服务器 '{server_name}' 的配置必须是一个 JSON 对象 (字典)。")

        server_type = server_conf.get("type")
        if not isinstance(server_type, str) or server_type not in [
                "stdio", "sse"
        ]:
            raise ConfigurationError(
                f"服务器 '{server_name}' 的配置缺少必需的 'type' 字段，或者其值不是 'stdio' 或 'sse'。"
            )

        if server_type == "stdio":

            if "command" not in server_conf:
                raise ConfigurationError(
                    f"Stdio 服务器 '{server_name}' 的配置缺少必需的 'command' 字段。")
            command = server_conf["command"]
            if not isinstance(command, str) or not command:
                raise ConfigurationError(
                    f"Stdio 服务器 '{server_name}' 的 'command' 必须是一个非空字符串。")

            args_conf = server_conf.get("args")
            args: List[str] = []
            if args_conf is not None:
                if not isinstance(args_conf, list):
                    raise ConfigurationError(
                        f"Stdio 服务器 '{server_name}' 的 'args' 必须是一个字符串列表。")
                for i, arg in enumerate(args_conf):
                    if not isinstance(arg, str):
                        raise ConfigurationError(
                            f"Stdio 服务器 '{server_name}' 的 'args' 列表的第 {i+1} 个元素必须是字符串。"
                        )
                    args.append(arg)

            env_conf = server_conf.get("env")
            env: Optional[Dict[str, str]] = None
            if env_conf is not None:
                if not isinstance(env_conf, dict):
                    raise ConfigurationError(
                        f"Stdio 服务器 '{server_name}' 的 'env' 必须是一个 JSON 对象 (字典)。"
                    )
                validated_env: Dict[str, str] = {}
                for key, value in env_conf.items():
                    if not isinstance(key, str):
                        raise ConfigurationError(
                            f"Stdio 服务器 '{server_name}' 的 'env' 字典的键必须是字符串。")
                    if not isinstance(value, str):
                        raise ConfigurationError(
                            f"Stdio 服务器 '{server_name}' 的 'env' 字典的值 (键: '{key}') 必须是字符串。"
                        )
                    validated_env[key] = value
                env = validated_env

            try:
                server_params = StdioServerParameters(command=command,
                                                      args=args,
                                                      env=env)
                validated_config[server_name] = {
                    "type": "stdio",
                    "params": server_params
                }
            except Exception as e:
                raise ConfigurationError(
                    f"为 Stdio 服务器 '{server_name}' 创建 StdioServerParameters 时出错: {e}"
                )

        elif server_type == "sse":

            if "url" not in server_conf:
                raise ConfigurationError(
                    f"SSE 服务器 '{server_name}' 的配置缺少必需的 'url' 字段。")
            server_url = server_conf["url"]
            if not isinstance(server_url, str) or not server_url:
                raise ConfigurationError(
                    f"SSE 服务器 '{server_name}' 的 'url' 必须是一个非空字符串。")
            if not server_url.startswith(("http://", "https://")):
                raise ConfigurationError(
                    f"SSE 服务器 '{server_name}' 的 'url' ('{server_url}') 看起来不是一个有效的 HTTP/HTTPS URL。"
                )

            validated_entry: Dict[str, Any] = {
                "type": "sse",
                "url": server_url
            }

            sse_command = server_conf.get('command')
            sse_args_conf = server_conf.get('args')
            sse_env_conf = server_conf.get('env')

            if sse_command is not None:

                if not isinstance(sse_command, str) or not sse_command:
                    raise ConfigurationError(
                        f"SSE 服务器 '{server_name}' 的 'command' (用于本地启动) 必须是一个非空字符串。"
                    )
                validated_entry['command'] = sse_command

                sse_args: List[str] = []
                if sse_args_conf is not None:
                    if not isinstance(sse_args_conf, list):
                        raise ConfigurationError(
                            f"SSE 服务器 '{server_name}' 的 'args' (用于本地启动) 必须是一个字符串列表。"
                        )
                    for i, arg in enumerate(sse_args_conf):
                        if not isinstance(arg, str):
                            raise ConfigurationError(
                                f"SSE 服务器 '{server_name}' 的 'args' 列表的第 {i+1} 个元素必须是字符串。"
                            )
                        sse_args.append(arg)
                validated_entry['args'] = sse_args

                sse_env: Optional[Dict[str, str]] = None
                if sse_env_conf is not None:
                    if not isinstance(sse_env_conf, dict):
                        raise ConfigurationError(
                            f"SSE 服务器 '{server_name}' 的 'env' (用于本地启动) 必须是一个 JSON 对象 (字典)。"
                        )
                    validated_sse_env: Dict[str, str] = {}
                    for key, value in sse_env_conf.items():
                        if not isinstance(key, str):
                            raise ConfigurationError(
                                f"SSE 服务器 '{server_name}' 的 'env' 字典的键必须是字符串。")
                        if not isinstance(value, str):
                            raise ConfigurationError(
                                f"SSE 服务器 '{server_name}' 的 'env' 字典的值 (键: '{key}') 必须是字符串。"
                            )
                        validated_sse_env[key] = value
                    validated_entry['env'] = validated_sse_env

            validated_config[server_name] = validated_entry

    return validated_config

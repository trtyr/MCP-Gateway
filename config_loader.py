import json
import os
from typing import Dict, List, Optional, Any, Union

from mcp import StdioServerParameters
from errors import ConfigurationError

import logging

logger = logging.getLogger(__name__)


def _valid_str_list(data: Any, field_name: str, svr_name: str) -> List[str]:
    """辅助函数，验证数据是否为字符串列表。"""
    if not isinstance(data, list):
        raise ConfigurationError(
            f"服务器 '{svr_name}' 的 '{field_name}' 必须是一个字符串列表。")

    val_list: List[str] = []
    for i, item in enumerate(data):
        if not isinstance(item, str):
            raise ConfigurationError(
                f"服务器 '{svr_name}' 的 '{field_name}' 列表的第 {i+1} 个元素必须是字符串。")
        val_list.append(item)
    return val_list


def _valid_str_dict(data: Any, field_name: str,
                    svr_name: str) -> Dict[str, str]:
    """辅助函数，验证数据是否为字符串到字符串的字典。"""
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"服务器 '{svr_name}' 的 '{field_name}' 必须是一个 JSON 对象 (键值均为字符串的字典)。")

    val_dict: Dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise ConfigurationError(
                f"服务器 '{svr_name}' 的 '{field_name}' 字典的键必须是字符串。")
        if not isinstance(value, str):
            raise ConfigurationError(
                f"服务器 '{svr_name}' 的 '{field_name}' 字典的值 (键: '{key}') 必须是字符串。")
        val_dict[key] = value
    return val_dict


def load_and_validate_config(cfg_fpath: str) -> Dict[str, Dict[str, Any]]:
    """
    加载并验证 JSON 配置文件。
    返回一个字典，其中键是服务器名称，值是经过验证和处理的服务器配置。
    """
    logger.debug(f"开始加载配置文件: {cfg_fpath}")
    if not os.path.exists(cfg_fpath):
        logger.error(f"配置文件未找到: {cfg_fpath}")
        raise ConfigurationError(f"配置文件不存在: {cfg_fpath}")

    try:
        with open(cfg_fpath, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
    except json.JSONDecodeError as e_json:
        logger.error(f"无法解析 JSON 配置文件 '{cfg_fpath}': {e_json}", exc_info=True)
        raise ConfigurationError(f"无法解析 JSON 配置文件: {cfg_fpath}, 错误: {e_json}")
    except Exception as e_read:
        logger.error(f"读取配置文件 '{cfg_fpath}' 时发生意外错误: {e_read}", exc_info=True)
        raise ConfigurationError(f"读取配置文件时发生意外错误: {cfg_fpath}, 错误: {e_read}")

    if not isinstance(raw_data, dict):
        logger.error("配置文件顶层必须是一个 JSON 对象 (字典)。")
        raise ConfigurationError("配置文件顶层必须是一个 JSON 对象 (字典)。")

    validated_configs: Dict[str, Dict[str, Any]] = {}
    logger.debug(f"找到 {len(raw_data)} 个服务器配置条目进行验证。")

    for svr_name_raw, srv_conf_raw in raw_data.items():
        if not isinstance(svr_name_raw, str) or not svr_name_raw.strip():
            logger.warning(
                f"配置中发现无效的服务器名称键: '{svr_name_raw}' (将被忽略)。名称必须是非空字符串。")

            continue

        svr_name = svr_name_raw.strip()

        if not isinstance(srv_conf_raw, dict):
            logger.warning(
                f"服务器 '{svr_name}' 的配置必须是一个 JSON 对象，实际类型: {type(srv_conf_raw)} (将被忽略)。"
            )
            continue

        srv_conf: Dict[str, Any] = srv_conf_raw

        svr_type = srv_conf.get("type")
        if not isinstance(svr_type, str) or svr_type not in ["stdio", "sse"]:
            logger.warning(
                f"服务器 '{svr_name}' 的 'type' 字段无效或缺失。必须是 'stdio' 或 'sse'，得到: {svr_type} (将被忽略)。"
            )
            continue

        logger.debug(f"正在验证服务器 '{svr_name}' (类型: {svr_type})")
        val_cfg_entry: Dict[str, Any] = {"type": svr_type}

        try:
            if svr_type == "stdio":
                cmd = srv_conf.get("command")
                if not isinstance(cmd, str) or not cmd.strip():
                    raise ConfigurationError(
                        f"Stdio 服务器 '{svr_name}' 的 'command' 必须是一个非空字符串。")

                cmd_args: List[str] = []
                if "args" in srv_conf:
                    cmd_args = _valid_str_list(srv_conf["args"], "args",
                                               svr_name)

                cmd_env: Optional[Dict[str, str]] = None
                if "env" in srv_conf and srv_conf["env"] is not None:
                    cmd_env = _valid_str_dict(srv_conf["env"], "env", svr_name)

                stdio_params = StdioServerParameters(command=cmd.strip(),
                                                     args=cmd_args,
                                                     env=cmd_env)
                val_cfg_entry["params"] = stdio_params

            elif svr_type == "sse":
                sse_url = srv_conf.get("url")
                if not isinstance(sse_url, str) or not sse_url.strip():
                    raise ConfigurationError(
                        f"SSE 服务器 '{svr_name}' 的 'url' 必须是一个非空字符串。")

                sse_url = sse_url.strip()
                if not sse_url.startswith(("http://", "https://")):
                    raise ConfigurationError(
                        f"SSE 服务器 '{svr_name}' 的 'url' ('{sse_url}') 看起来不是一个有效的 HTTP/HTTPS URL。"
                    )
                val_cfg_entry["url"] = sse_url

                if "command" in srv_conf:
                    sse_cmd = srv_conf.get("command")
                    if not isinstance(sse_cmd, str) or not sse_cmd.strip():
                        raise ConfigurationError(
                            f"SSE 服务器 '{svr_name}' 的 'command' (用于本地启动) 必须是一个非空字符串。"
                        )
                    val_cfg_entry['command'] = sse_cmd.strip()

                    sse_cmd_args: List[str] = []
                    if "args" in srv_conf:
                        sse_cmd_args = _valid_str_list(srv_conf["args"],
                                                       "args", svr_name)
                    val_cfg_entry['args'] = sse_cmd_args

                    sse_cmd_env: Optional[Dict[str, str]] = None
                    if "env" in srv_conf and srv_conf["env"] is not None:
                        sse_cmd_env = _valid_str_dict(srv_conf["env"], "env",
                                                      svr_name)
                    val_cfg_entry['env'] = sse_cmd_env

            validated_configs[svr_name] = val_cfg_entry
            logger.debug(f"服务器 '{svr_name}' 配置验证通过。")

        except ConfigurationError as e_svr_cfg:
            logger.error(f"服务器 '{svr_name}' 配置无效，已跳过: {e_svr_cfg}")

        except Exception as e_svr_unexpected:
            logger.error(
                f"处理服务器 '{svr_name}' 配置时发生意外错误，已跳过: {e_svr_unexpected}",
                exc_info=True)

    if not validated_configs and raw_data:
        logger.error("配置文件中所有服务器配置均无效。")
        raise ConfigurationError("配置文件中没有有效的服务器配置。")
    elif not validated_configs:
        logger.info(f"配置文件 '{cfg_fpath}' 为空或不包含任何服务器配置。")

    logger.info(
        f"配置文件 '{cfg_fpath}' 加载和验证完成。共处理 {len(validated_configs)} 个有效的服务器配置。")
    return validated_configs

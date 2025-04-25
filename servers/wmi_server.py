# stdio_servers/wmi_server.py
# -*- coding: utf-8 -*-

import sys
import logging
import json
from typing import List, Dict, Any, Optional

try:
    import wmi
except ImportError:
    print("错误：缺少 'wmi' 库。请在你的虚拟环境中运行 'uv add wmi' (或 'pip install wmi') 进行安装。")
    sys.exit(1)

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("WmiServer")

mcp = FastMCP("WMI")


@mcp.tool()
async def query_wmi(wmi_class: str,
                    properties: Optional[List[str]] = None,
                    filter: Optional[str] = None) -> str:
    """
    Tool queries WMI classes.

    Valid only on Windows.

    Args:
        wmi_class: WMI class name (e.g., 'Win32_Processor').
        properties: (Optional) List[str] specifying properties to return. If omitted/empty, returns all available properties.
        filter: (Optional) WQL 'WHERE' clause string to filter results (e.g., "Name='root'").

    Returns:
        JSON string containing a list of query results.
        Each object in the list is a WMI instance; key-value pairs are requested properties & values.
        If query fails, returns error string.
    """
    logger.info(
        f"接收到 WMI 查询请求: Class='{wmi_class}', Properties={properties}, Filter='{filter}'"
    )

    if sys.platform != "win32":
        logger.error("WMI 查询工具仅支持在 Windows 上运行。")
        return json.dumps({"error": "此工具仅支持 Windows。"})

    if not wmi_class:
        logger.warning("WMI 类名不能为空。")
        return json.dumps({"error": "WMI 类名不能为空。"})

    try:

        logger.debug("正在连接到本地 WMI 服务...")
        conn = wmi.WMI()
        logger.debug("WMI 连接成功。")

        select_clause = "*"
        if properties and isinstance(properties, list) and len(properties) > 0:

            valid_properties = [
                str(p) for p in properties if isinstance(p, str) and p
            ]
            if valid_properties:
                select_clause = ", ".join(valid_properties)
            else:
                logger.warning("提供的属性列表无效或为空，将查询所有属性(*)。")

        wql_query = f"SELECT {select_clause} FROM {wmi_class}"

        if filter and isinstance(filter, str) and filter.strip():
            wql_query += f" WHERE {filter.strip()}"

        logger.debug(f"构建的 WQL 查询: {wql_query}")

        query_results = conn.query(wql_query)
        logger.info(f"查询 '{wql_query}' 返回了 {len(query_results)} 个结果。")

        result_list: List[Dict[str, Any]] = []
        for item in query_results:
            instance_dict = {}

            props_to_get = valid_properties if 'valid_properties' in locals(
            ) and valid_properties else [
                prop.Name for prop in item.Properties_
            ]

            for prop_name in props_to_get:
                try:

                    value = getattr(item, prop_name, None)

                    if value is None:
                        instance_dict[prop_name] = None
                    elif isinstance(value, (str, int, float, bool)):
                        instance_dict[prop_name] = value
                    elif isinstance(value, (list, tuple)):

                        try:
                            instance_dict[prop_name] = [str(v) for v in value]
                        except Exception:
                            instance_dict[
                                prop_name] = f"无法序列化的列表/元组: {type(value)}"
                    else:

                        try:
                            instance_dict[prop_name] = str(value)
                        except Exception:
                            instance_dict[
                                prop_name] = f"无法序列化的类型: {type(value)}"
                except AttributeError:
                    logger.warning(f"实例 {item} 上找不到属性 '{prop_name}'，跳过。")
                    instance_dict[prop_name] = None
                except Exception as get_attr_err:
                    logger.error(f"获取属性 '{prop_name}' 时出错: {get_attr_err}")
                    instance_dict[prop_name] = f"获取错误: {get_attr_err}"

            result_list.append(instance_dict)

        return json.dumps(result_list, indent=2, default=str)

    except wmi.x_wmi as e:
        logger.error(f"执行 WMI 查询时发生错误: {e}")

        error_info = {"error": f"WMI 查询错误: {e}"}
        if hasattr(e, 'com_error'):
            error_info["com_error_details"] = str(e.com_error)
        return json.dumps(error_info)
    except Exception as e:
        logger.exception(f"处理 WMI 查询时发生意外错误: {e}")
        return json.dumps({"error": f"意外错误: {type(e).__name__} - {e}"})


if __name__ == "__main__":

    if sys.platform != "win32":
        logger.error("WMI 服务器仅能在 Windows 上运行。正在退出。")
        sys.exit(1)

    logger.info("启动 WMI MCP 服务器 ...")
    mcp.run(transport='stdio')
    logger.info("WMI MCP 服务器已停止。")

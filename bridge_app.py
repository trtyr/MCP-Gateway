import asyncio
import logging
import os
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.requests import Request

from mcp import ClientSession
from mcp.server import Server as McpServer
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from mcp import types as mcp_types

from config_loader import load_and_validate_config, ConfigurationError
from client_manager import ClientManager
from capability_registry import CapabilityRegistry
from errors import BackendServerError

SERVER_NAME = "MCP_Bridge_Server"
SERVER_VERSION = "3.0.1"
AUTHOR = "特让他也让"
SSE_PATH = "/sse"
POST_MESSAGES_PATH = "/messages/"

DEFAULT_LOG_FPATH = "unknown_bridge_log.log"
DEFAULT_LOG_LVL = "INFO"

logger = logging.getLogger(__name__)

mcp_server = McpServer(SERVER_NAME)
mcp_server.manager: Optional[ClientManager] = None
mcp_server.registry: Optional[CapabilityRegistry] = None
logger.debug(f"底层 MCP 服务器实例 '{mcp_server.name}' 已创建。")


def _gen_status_info(app_state: Optional[object],
                     status_msg: str,
                     tools: Optional[List[mcp_types.Tool]] = None,
                     resources: Optional[List[mcp_types.Resource]] = None,
                     prompts: Optional[List[mcp_types.Prompt]] = None,
                     err_msg: Optional[str] = None,
                     conn_svrs_num: Optional[int] = None,
                     total_svrs_num: Optional[int] = None) -> Dict[str, Any]:
    """
    生成结构化的状态信息字典。
    Generate a structured dictionary of status information.
    """
    host = getattr(app_state, 'host', 'N/A') if app_state else 'N/A'
    port = getattr(app_state, 'port', 0) if app_state else 0

    info: Dict[str, Any] = {
        "ts":
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status_msg":
        status_msg,
        "host":
        host,
        "port":
        port,
        "log_fpath":
        getattr(app_state, 'actual_log_file', DEFAULT_LOG_FPATH)
        if app_state else DEFAULT_LOG_FPATH,
        "log_lvl_cfg":
        getattr(app_state, 'file_log_level_configured', DEFAULT_LOG_LVL)
        if app_state else DEFAULT_LOG_LVL,
        "sse_url":
        f"http://{host}:{port}{SSE_PATH}" if port > 0 else "N/A",
        "cfg_fpath":
        getattr(app_state, 'config_file_path', 'N/A') if app_state else 'N/A',
        "err_msg":
        err_msg,
        "tools":
        tools or [],
        "resources":
        resources or [],
        "prompts":
        prompts or []
    }
    if tools is not None:
        info["tools_count"] = len(tools)
    if resources is not None:
        info["resources_count"] = len(resources)
    if prompts is not None:
        info["prompts_count"] = len(prompts)
    if conn_svrs_num is not None:
        info["conn_svrs_num"] = conn_svrs_num
    if total_svrs_num is not None:
        info["total_svrs_num"] = total_svrs_num
    return info


def disp_console_status(stage: str,
                        status_info: Dict[str, Any],
                        is_final: bool = False):
    """在控制台打印美化后的状态信息。"""
    header = f" MCP Bridge Server v{SERVER_VERSION} (by {AUTHOR}) "
    sep_char = "="
    line_len = 70

    if not hasattr(disp_console_status, "header_printed") or is_final:
        print(f"\n{sep_char * line_len}")
        print(f"{header:-^{line_len}}")
        print(f"{sep_char * line_len}")
        if not is_final:
            disp_console_status.header_printed = True
        else:
            if hasattr(disp_console_status, "header_printed"):
                delattr(disp_console_status, "header_printed")

    print(f"[{status_info['ts']}] {stage} 状态: {status_info['status_msg']}")

    if not is_final and stage == "🚀 初始化":
        print(f"    服务器名称: {SERVER_NAME}")
        print(f"    SSE URL: {status_info['sse_url']}")
        print(f"    配置文件: {os.path.basename(status_info['cfg_fpath'])}")
        print(
            f"    日志文件: {status_info['log_fpath']} (级别: {status_info['log_lvl_cfg']})"
        )

    if "total_svrs_num" in status_info and "conn_svrs_num" in status_info:
        print(
            f"    后端服务: {status_info['conn_svrs_num']} / {status_info['total_svrs_num']} 已连接"
        )

    if "tools_count" in status_info:
        print(f"    MCP 工具: {status_info['tools_count']} 个已加载")
    if "resources_count" in status_info:
        print(f"    MCP 资源: {status_info['resources_count']} 个已加载")
    if "prompts_count" in status_info:
        print(f"    MCP 提示: {status_info['prompts_count']} 个已加载")

    if status_info.get("err_msg"):
        print(f"    !! 错误: {status_info['err_msg']}")

    if not is_final:
        print("-" * line_len)

    if is_final:
        print(f"    日志文件: {status_info['log_fpath']}")
        print(f"{sep_char * line_len}\n")


def log_file_status(status_info: Dict[str, Any], log_lvl: int = logging.INFO):
    """将详细状态信息记录到日志文件。"""
    log_lines = [
        f"Server Status Update: {status_info['status_msg']}",
        f"  Author: {AUTHOR}",
        f"  SSE URL: {status_info['sse_url']}",
        f"  Config File Used: {status_info['cfg_fpath']}",
        f"  Configured File Log Level: {status_info['log_lvl_cfg']}",
        f"  Actual Log File: {status_info['log_fpath']}",
    ]
    if "total_svrs_num" in status_info and "conn_svrs_num" in status_info:
        log_lines.append(
            f"  Backend Services: {status_info['conn_svrs_num']}/{status_info['total_svrs_num']} connected"
        )
    if status_info.get("err_msg"):
        log_lines.append(f"  Error Details: {status_info['err_msg']}")

    for cap_type_plural, cap_key_count, cap_list_key in [
        ("Tools", "tools_count", "tools"),
        ("Resources", "resources_count", "resources"),
        ("Prompts", "prompts_count", "prompts")
    ]:
        if cap_key_count in status_info:
            log_lines.append(
                f"  Loaded MCP {cap_type_plural} ({status_info[cap_key_count]}):"
            )
            cap_list = status_info.get(cap_list_key, [])
            if cap_list:
                for item in cap_list:
                    desc = item.description.strip().split(
                        '\n')[0] if item.description else "-"
                    log_lines.append(f"    - {item.name}, Description: {desc}")
            elif status_info[cap_key_count] > 0:
                log_lines.append(
                    f"    Detail list for {cap_list_key} not provided in status_info for logging, but count is > 0."
                )
            else:
                log_lines.append(f"    No {cap_list_key} loaded.")

    logger.log(log_lvl, "\n".join(log_lines))


async def _setup_app_configs(app_state: object) -> Tuple[str, Dict[str, Any]]:
    """加载并验证配置文件。"""
    cfg_fpath = getattr(app_state, 'config_file_path', "config.json")
    logger.info(f"加载配置文件: {cfg_fpath}")

    status_info_load = _gen_status_info(
        app_state, f"正在加载配置 ({os.path.basename(cfg_fpath)})...")
    disp_console_status("📄 配置加载", status_info_load)
    log_file_status(status_info_load)

    config = load_and_validate_config(cfg_fpath)
    total_svrs = len(config)
    logger.info(f"配置文件加载并验证成功，共 {total_svrs} 个后端配置。")

    status_info_loaded = _gen_status_info(app_state,
                                          f"配置加载完毕，共 {total_svrs} 个后端服务。",
                                          total_svrs_num=total_svrs)
    disp_console_status("📄 配置加载", status_info_loaded)
    return cfg_fpath, config


async def _connect_backends(
        manager: ClientManager, config: Dict[str, Any],
        app_state: object) -> Tuple[int, int, Dict[str, ClientSession]]:
    """连接所有后端服务器。"""
    total_svrs = len(config)
    status_msg_conn = f"正在连接 {total_svrs} 个后端服务..."
    status_info_conn_start = _gen_status_info(app_state,
                                              status_msg_conn,
                                              total_svrs_num=total_svrs)
    disp_console_status("🔌 后端连接", status_info_conn_start)
    log_file_status(status_info_conn_start)

    await manager.start_all(config)
    active_sessions = manager.get_all_sessions()
    conn_svrs = len(active_sessions)

    log_lvl_conn = logging.INFO
    if conn_svrs == 0 and total_svrs > 0:
        conn_msg_short = f"❌ 所有后端连接失败 ({conn_svrs}/{total_svrs})"
        log_lvl_conn = logging.ERROR
    elif conn_svrs < total_svrs:
        conn_msg_short = f"⚠️ 部分后端连接失败 ({conn_svrs}/{total_svrs})"
        log_lvl_conn = logging.WARNING
    else:
        conn_msg_short = f"✅ 所有后端连接成功 ({conn_svrs}/{total_svrs})" if total_svrs > 0 else "✅ (未配置后端服务)"

    status_info_conn_done = _gen_status_info(app_state,
                                             conn_msg_short,
                                             conn_svrs_num=conn_svrs,
                                             total_svrs_num=total_svrs)
    disp_console_status("🔌 后端连接", status_info_conn_done)
    log_file_status(status_info_conn_done, log_lvl=log_lvl_conn)

    if conn_svrs == 0 and total_svrs > 0:
        raise BackendServerError(f"无法连接到任何后端服务器 ({total_svrs} 个已配置)。桥接服务无法启动。")
    return conn_svrs, total_svrs, active_sessions


async def _discover_capabilities(
    registry: CapabilityRegistry, active_sessions: Dict[str, ClientSession],
    app_state: object, conn_svrs_num: int, total_svrs_num: int
) -> Tuple[List[mcp_types.Tool], List[mcp_types.Resource],
           List[mcp_types.Prompt]]:
    """发现并注册所有后端的能力。"""
    status_msg_disc = f"正在发现 MCP 能力 ({conn_svrs_num}/{total_svrs_num} 个已连接服务)..."
    status_info_disc_start = _gen_status_info(app_state,
                                              status_msg_disc,
                                              conn_svrs_num=conn_svrs_num,
                                              total_svrs_num=total_svrs_num)
    disp_console_status("🔍 能力发现", status_info_disc_start)
    log_file_status(status_info_disc_start)

    tools: List[mcp_types.Tool] = []
    resources: List[mcp_types.Resource] = []
    prompts: List[mcp_types.Prompt] = []

    if conn_svrs_num > 0:
        await registry.discover_and_register(active_sessions)
        tools = registry.get_aggregated_tools()
        resources = registry.get_aggregated_resources()
        prompts = registry.get_aggregated_prompts()
    else:
        logger.info("没有活动的后端会话，跳过能力发现。")

    status_info_disc_done = _gen_status_info(app_state,
                                             "能力发现与注册完毕。",
                                             tools=tools,
                                             resources=resources,
                                             prompts=prompts,
                                             conn_svrs_num=conn_svrs_num,
                                             total_svrs_num=total_svrs_num)

    disp_console_status("🔍 能力发现", status_info_disc_done)
    log_file_status(status_info_disc_done)
    return tools, resources, prompts


def _init_bridge_components(mcp_svr_instance: McpServer,
                            cli_manager: ClientManager,
                            cap_registry: CapabilityRegistry):
    """初始化桥接服务器的核心组件。"""
    mcp_svr_instance.manager = cli_manager
    mcp_svr_instance.registry = cap_registry
    logger.info("ClientManager 和 CapabilityRegistry 已附加到 mcp_server 实例。")


@asynccontextmanager
async def app_lifespan(app: Starlette) -> AsyncIterator[None]:
    """应用生命周期管理：启动和关闭。"""
    global mcp_server

    app_s = app.state
    logger.info(f"桥接服务器 '{SERVER_NAME}' v{SERVER_VERSION} 启动流程开始...")
    logger.info(f"作者: {AUTHOR}")
    logger.debug(
        f"Lifespan 获取到 host='{getattr(app_s, 'host', 'N/A')}', port={getattr(app_s, 'port', 0)}"
    )
    logger.info(
        f"配置文件日志级别: {getattr(app_s, 'file_log_level_configured', DEFAULT_LOG_LVL)}"
    )
    logger.info(
        f"实际日志文件: {getattr(app_s, 'actual_log_file', DEFAULT_LOG_FPATH)}")
    logger.info(
        f"将使用的配置文件: {getattr(app_s, 'config_file_path', 'config.json')}")

    cli_mgr = ClientManager()
    cap_reg = CapabilityRegistry()
    startup_ok = False

    tools: List[mcp_types.Tool] = []
    resources: List[mcp_types.Resource] = []
    prompts: List[mcp_types.Prompt] = []
    err_detail_msg: Optional[str] = None
    conn_svrs: int = 0
    total_svrs: int = 0

    try:
        status_info_init = _gen_status_info(app_s, "桥接服务器正在启动...")
        disp_console_status("🚀 初始化", status_info_init)
        log_file_status(status_info_init)

        _, config_data = await _setup_app_configs(app_s)
        conn_svrs, total_svrs, active_sess = await _connect_backends(
            cli_mgr, config_data, app_s)
        tools, resources, prompts = await _discover_capabilities(
            cap_reg, active_sess, app_s, conn_svrs, total_svrs)
        _init_bridge_components(mcp_server, cli_mgr, cap_reg)

        logger.info("生命周期启动阶段成功完成。")
        startup_ok = True

        status_info_ready = _gen_status_info(app_s,
                                             "服务器已成功启动并准备就绪！",
                                             tools=tools,
                                             resources=resources,
                                             prompts=prompts,
                                             conn_svrs_num=conn_svrs,
                                             total_svrs_num=total_svrs)
        disp_console_status("✅ 服务就绪", status_info_ready)
        log_file_status(status_info_ready)
        yield

    except ConfigurationError as e_cfg:
        logger.exception(f"配置错误: {e_cfg}")
        err_detail_msg = f"配置错误: {e_cfg}"
        status_info_fail = _gen_status_info(app_s,
                                            "服务器启动失败。",
                                            err_msg=err_detail_msg,
                                            total_svrs_num=total_svrs)
        disp_console_status("❌ 启动失败", status_info_fail)
        log_file_status(status_info_fail, log_lvl=logging.ERROR)
        raise
    except BackendServerError as e_backend:
        logger.exception(f"后端错误: {e_backend}")
        err_detail_msg = f"后端错误: {e_backend}"
        status_info_fail = _gen_status_info(app_s,
                                            "服务器启动失败。",
                                            err_msg=err_detail_msg,
                                            conn_svrs_num=conn_svrs,
                                            total_svrs_num=total_svrs)
        disp_console_status("❌ 启动失败", status_info_fail)
        log_file_status(status_info_fail, log_lvl=logging.ERROR)
        raise
    except Exception as e_exc:
        logger.exception(f"应用生命周期启动时发生意外错误: {e_exc}")
        err_detail_msg = f"意外错误: {type(e_exc).__name__} - {e_exc}"
        status_info_fail = _gen_status_info(app_s,
                                            "服务器启动失败。",
                                            err_msg=err_detail_msg,
                                            conn_svrs_num=conn_svrs,
                                            total_svrs_num=total_svrs)
        disp_console_status("❌ 启动失败", status_info_fail)
        log_file_status(status_info_fail, log_lvl=logging.ERROR)
        raise
    finally:
        logger.info(f"桥接服务器 '{SERVER_NAME}' 关闭流程开始...")
        status_info_shutdown = _gen_status_info(app_s,
                                                "服务器正在关闭...",
                                                tools=tools,
                                                resources=resources,
                                                prompts=prompts,
                                                conn_svrs_num=conn_svrs,
                                                total_svrs_num=total_svrs)
        disp_console_status("🛑 关闭中", status_info_shutdown, is_final=False)
        log_file_status(status_info_shutdown, log_lvl=logging.WARNING)

        active_manager = mcp_server.manager if mcp_server.manager else cli_mgr
        if active_manager:
            logger.info("正在停止所有后端服务器连接...")
            await active_manager.stop_all()
            logger.info("后端连接已停止。")
        else:
            logger.warning("ClientManager 未初始化或未成功附加，跳过停止步骤。")

        final_msg_short = "服务器正常关闭。" if startup_ok else f"服务器异常退出{(f' - 错误: {err_detail_msg}' if err_detail_msg else '')}"
        final_icon = "✅" if startup_ok else "❌"
        final_log_lvl = logging.INFO if startup_ok else logging.ERROR

        status_info_final = _gen_status_info(
            app_s,
            final_msg_short,
            err_msg=err_detail_msg if not startup_ok else None)
        disp_console_status(f"{final_icon} 最终状态",
                            status_info_final,
                            is_final=True)
        log_file_status(status_info_final, log_lvl=final_log_lvl)
        logger.info(f"桥接服务器 '{SERVER_NAME}' 关闭流程完成。")


async def _fwd_req_helper(cap_name_full: str, mcp_method: str,
                          args: Optional[Dict[str, Any]],
                          mcp_svr: McpServer) -> Any:
    """辅助函数，用于将 MCP 请求转发到正确的后端服务器。"""
    logger.info(f"开始转发请求: 能力='{cap_name_full}', 方法='{mcp_method}', 参数={args}")

    registry = mcp_svr.registry
    manager = mcp_svr.manager

    if not registry or not manager:
        logger.error("转发请求时 registry 或 manager 未设置。这是严重的服务器内部错误。")
        raise BackendServerError("桥接服务器内部错误：核心组件未初始化。")

    route_info = registry.resolve_capability(cap_name_full)
    if not route_info:
        logger.warning(f"无法解析能力名称 '{cap_name_full}'。MCP客户端应收到错误。")
        raise ValueError(f"能力 '{cap_name_full}' 不存在。")

    svr_name, orig_cap_name = route_info
    logger.debug(
        f"能力 '{cap_name_full}' 解析为服务器 '{svr_name}' 的能力 '{orig_cap_name}'。")

    session = manager.get_session(svr_name)
    if not session:
        logger.error(f"无法获取服务器 '{svr_name}' 的活动会话以转发 '{cap_name_full}'。")
        raise RuntimeError(
            f"无法连接到提供能力 '{cap_name_full}' 的后端服务器 '{svr_name}'。(会话不存在或已丢失)")

    try:
        target_method_on_session = getattr(session, mcp_method)
    except AttributeError:
        logger.exception(f"内部编程错误：ClientSession 上不存在方法 '{mcp_method}'。")
        raise NotImplementedError(f"桥接服务器内部错误：无法找到转发方法 '{mcp_method}'。")

    try:
        logger.debug(
            f"正在调用后端 '{svr_name}' 的方法 '{mcp_method}' (原始能力: '{orig_cap_name}')"
        )
        result: Any
        if mcp_method == "call_tool":
            result = await target_method_on_session(name=orig_cap_name,
                                                    arguments=args or {})
        elif mcp_method == "read_resource":
            content, mime_type = await target_method_on_session(
                name=orig_cap_name)
            result = mcp_types.ReadResourceResult(content=content,
                                                  mime_type=mime_type)
        elif mcp_method == "get_prompt":
            result = await target_method_on_session(name=orig_cap_name,
                                                    arguments=args)
        else:
            logger.error(f"内部编程错误：未知的转发方法名称 '{mcp_method}'。")
            raise NotImplementedError(f"桥接服务器内部错误：无法处理此请求类型 '{mcp_method}'。")

        logger.info(
            f"成功从后端 '{svr_name}' 收到 '{mcp_method}' 的结果 (能力: '{cap_name_full}')。"
        )
        return result
    except asyncio.TimeoutError:
        logger.error(
            f"与后端 '{svr_name}' 通信超时 (能力: '{cap_name_full}', 方法: '{mcp_method}')。"
        )
        raise
    except (ConnectionError, BrokenPipeError) as conn_e:
        logger.error(
            f"与后端 '{svr_name}' 连接丢失 (能力: '{cap_name_full}', 方法: '{mcp_method}'): {type(conn_e).__name__}"
        )
        raise
    except BackendServerError:
        logger.warning(f"后端 '{svr_name}' 报告了一个服务器错误在处理 '{cap_name_full}' 时。")
        raise
    except Exception as e_fwd:
        logger.exception(
            f"转发请求给后端 '{svr_name}' 时发生意外错误 (能力: '{cap_name_full}', 方法: '{mcp_method}')"
        )
        raise BackendServerError(
            f"处理来自 '{svr_name}' 的请求 '{cap_name_full}' 时发生意外后端错误: {type(e_fwd).__name__}"
        ) from e_fwd


@mcp_server.list_tools()
async def handle_list_tools() -> List[mcp_types.Tool]:
    logger.debug("处理 listTools 请求...")
    if not mcp_server.registry: raise BackendServerError("Registry 未初始化")
    tools = mcp_server.registry.get_aggregated_tools()
    logger.info(f"返回 {len(tools)} 个聚合工具")
    return tools


@mcp_server.list_resources()
async def handle_list_resources() -> List[mcp_types.Resource]:
    logger.debug("处理 listResources 请求...")
    if not mcp_server.registry: raise BackendServerError("Registry 未初始化")
    resources = mcp_server.registry.get_aggregated_resources()
    logger.info(f"返回 {len(resources)} 个聚合资源")
    return resources


@mcp_server.list_prompts()
async def handle_list_prompts() -> List[mcp_types.Prompt]:
    logger.debug("处理 listPrompts 请求...")
    if not mcp_server.registry: raise BackendServerError("Registry 未初始化")
    prompts = mcp_server.registry.get_aggregated_prompts()
    logger.info(f"返回 {len(prompts)} 个聚合提示")
    return prompts


@mcp_server.call_tool()
async def handle_call_tool(
        name: str, arguments: Dict[str, Any]) -> List[mcp_types.TextContent]:
    logger.debug(f"处理 callTool: name='{name}'")
    result = await _fwd_req_helper(name, "call_tool", arguments, mcp_server)
    if isinstance(result, mcp_types.CallToolResult):
        return result.content
    logger.error(f"call_tool 转发返回了非预期的类型: {type(result)} for tool '{name}'")
    raise BackendServerError(f"调用工具 '{name}' 后端返回类型错误。")


@mcp_server.read_resource()
async def handle_read_resource(name: str) -> mcp_types.ReadResourceResult:
    logger.debug(f"处理 readResource: name='{name}'")
    result = await _fwd_req_helper(name, "read_resource", None, mcp_server)
    if isinstance(result, mcp_types.ReadResourceResult):
        return result
    logger.error(
        f"read_resource 转发返回了非预期的类型: {type(result)} for resource '{name}'")
    raise BackendServerError(f"读取资源 '{name}' 后端返回类型错误。")


@mcp_server.get_prompt()
async def handle_get_prompt(
        name: str,
        arguments: Optional[Dict[str,
                                 Any]] = None) -> mcp_types.GetPromptResult:
    logger.debug(f"处理 getPrompt: name='{name}'")
    typed_args: Optional[Dict[str, str]] = None
    if arguments is not None:
        try:
            typed_args = {k: str(v) for k, v in arguments.items()}
        except Exception:
            logger.warning(
                f"无法将 get_prompt 的参数转换为 Dict[str, str] for prompt '{name}'. 将尝试使用原始参数。",
                exc_info=True)
            pass

    result = await _fwd_req_helper(name, "get_prompt", typed_args or arguments,
                                   mcp_server)
    if isinstance(result, mcp_types.GetPromptResult):
        return result
    logger.error(f"get_prompt 转发返回了非预期的类型: {type(result)} for prompt '{name}'")
    raise BackendServerError(f"获取提示 '{name}' 后端返回类型错误。")


sse_transport = SseServerTransport(POST_MESSAGES_PATH)


async def handle_sse(request: Request) -> None:
    """处理传入的 SSE 连接请求。"""
    logger.debug(f"接收到新的 SSE 连接请求 (GET): {request.url}")
    global mcp_server
    if not mcp_server.manager or not mcp_server.registry:
        logger.error(
            "在 handle_sse 中发现 manager 或 registry 未设置。关键组件缺失，无法处理SSE连接。")
        return

    async with sse_transport.connect_sse(
            request.scope,
            request.receive,
            request._send,
    ) as (read_stream, write_stream):
        try:
            srv_caps = {}
            if mcp_server.registry:
                srv_caps = mcp_server.get_capabilities(NotificationOptions(),
                                                       {})
            else:
                logger.warning(
                    "mcp_server.registry 未设置，在SSE初始化时将使用空的 capabilities。")
            logger.debug(f"为SSE连接获取到的服务器Capabilities: {srv_caps}")
        except Exception as e_caps:
            logger.exception(
                f"为SSE连接获取 mcp_server.get_capabilities 时出错: {e_caps}")
            srv_caps = {}

        init_opts = InitializationOptions(
            server_name=SERVER_NAME,
            server_version=SERVER_VERSION,
            capabilities=srv_caps,
        )
        logger.debug(
            f"准备运行 mcp_server.run (MCP主循环) for SSE connection with options: {init_opts}"
        )
        await mcp_server.run(read_stream, write_stream, init_opts)
    logger.debug(f"SSE 连接已关闭: {request.url}")


app: Starlette = Starlette(lifespan=app_lifespan,
                           routes=[
                               Route(SSE_PATH, endpoint=handle_sse),
                               Mount(POST_MESSAGES_PATH,
                                     app=sse_transport.handle_post_message),
                           ])
logger.info(
    f"Starlette ASGI 应用 '{SERVER_NAME}' 已创建。SSE GET on {SSE_PATH}, POST on {POST_MESSAGES_PATH}"
)

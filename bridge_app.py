import asyncio
import logging
import os

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.requests import Request

from mcp.server import Server as McpServer
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from mcp import types as mcp_types

from config_loader import load_and_validate_config, ConfigurationError
from client_manager import ClientManager
from capability_registry import CapabilityRegistry
from errors import BackendServerError

CONFIG_FILE_PATH = "config.json"
SERVER_NAME = "MCP_Bridge_Server"
SERVER_VERSION = "3.0.0"
AUTHOR = "特让他也让"
SSE_PATH = "/sse"
POST_MESSAGES_PATH = "/messages/"

DEFAULT_ACTUAL_LOG_FILE = "unknown_bridge_log.log"
DEFAULT_FILE_LOG_LEVEL = "INFO"

logger = logging.getLogger(__name__) 

mcp_server = McpServer(SERVER_NAME)
mcp_server.manager: Optional[ClientManager] = None
mcp_server.registry: Optional[CapabilityRegistry] = None
logger.debug(f"Low-level McpServer instance '{mcp_server.name}' created.")


def display_status_on_console(
    status_message: str,
    app_state: Optional[object] = None,
    tools_list: Optional[List[mcp_types.Tool]] = None,
    error_message: Optional[str] = None,
    connected_servers: int = 0,
    total_servers: int = 0,
):
    """仅在控制台打印美化后的状态信息。"""
    host = getattr(app_state, 'host', 'N/A') if app_state else 'N/A'
    port = getattr(app_state, 'port', 0) if app_state else 0
    
    console_lines = [
        f"--- {SERVER_NAME} v{SERVER_VERSION} ---",
        f"作者: {AUTHOR}",
        f"状态: {status_message}",
    ]
    if total_servers > 0:
         console_lines.append(f"后端服务: {connected_servers}/{total_servers} 已连接")
    
    if tools_list is not None:
        tool_info_line = f"MCP 工具: {len(tools_list)} 个已加载"
        console_lines.append(tool_info_line)
        
        
        
        
        
        
        
        
            
    if error_message:
        console_lines.append(f"错误: {error_message}")
    
    print("\n" + "\n".join(console_lines))


def log_server_status_to_file(
    status_message: str,
    app_state: Optional[object] = None,
    tools_list: Optional[List[mcp_types.Tool]] = None,
    error_message: Optional[str] = None,
    connected_servers: int = 0,
    total_servers: int = 0,
    log_level_for_file: int = logging.INFO
):
    """将详细状态信息记录到日志文件。"""
    host = getattr(app_state, 'host', 'N/A') if app_state else 'N/A'
    port = getattr(app_state, 'port', 0) if app_state else 0
    actual_log_file = getattr(app_state, 'actual_log_file', DEFAULT_ACTUAL_LOG_FILE) if app_state else DEFAULT_ACTUAL_LOG_FILE
    file_log_level_configured = getattr(app_state, 'file_log_level_configured', DEFAULT_FILE_LOG_LEVEL) if app_state else DEFAULT_FILE_LOG_LEVEL
    full_sse_url = f"http://{host}:{port}{SSE_PATH}" if port > 0 else "N/A"

    log_lines_for_file = [
        f"Server Status Update: {status_message}",
        f"  Author: {AUTHOR}",
        f"  SSE URL: {full_sse_url}",
        f"  Configured File Log Level: {file_log_level_configured}",
        f"  Actual Log File: {actual_log_file}",
    ]
    if total_servers > 0:
        log_lines_for_file.append(f"  Backend Services: {connected_servers}/{total_servers} connected")
    if error_message:
        log_lines_for_file.append(f"  Error Details: {error_message}")
    if tools_list is not None:
        log_lines_for_file.append(f"  Loaded MCP Tools ({len(tools_list)}):")
        if tools_list:
            for tool in tools_list:
                first_line_desc = tool.description.strip().split('\n')[0] if tool.description else "-"
                log_lines_for_file.append(f"    - Tool: {tool.name}, Description: {first_line_desc}")
        else:
            log_lines_for_file.append("    No tools loaded.")
    
    logger.log(log_level_for_file, "\n".join(log_lines_for_file))


@asynccontextmanager
async def app_lifespan(app: Starlette) -> AsyncIterator[None]:
    global mcp_server
    
    host = getattr(app.state, 'host', 'N/A')
    port = getattr(app.state, 'port', 0)
    
    logger.info(f"桥接服务器 '{SERVER_NAME}' v{SERVER_VERSION} 启动流程开始...")
    logger.info(f"作者: {AUTHOR}")
    logger.debug(f"Lifespan 获取到 host='{host}', port={port}")
    logger.info(f"配置文件日志级别: {getattr(app.state, 'file_log_level_configured', DEFAULT_FILE_LOG_LEVEL)}")
    logger.info(f"实际日志文件: {getattr(app.state, 'actual_log_file', DEFAULT_ACTUAL_LOG_FILE)}")

    manager = ClientManager()
    registry = CapabilityRegistry()
    startup_success = False
    tools_list: Optional[List[mcp_types.Tool]] = None
    error_msg_details = None
    connected_count = 0
    total_config_servers = 0

    try:
        display_status_on_console("🚀 正在启动...", app_state=app.state)
        log_server_status_to_file("🚀 正在启动...", app_state=app.state)

        logger.info(f"加载配置文件: {CONFIG_FILE_PATH}")
        display_status_on_console("📄 正在加载配置...", app_state=app.state)
        log_server_status_to_file("📄 正在加载配置...", app_state=app.state)
        config = load_and_validate_config(CONFIG_FILE_PATH)
        total_config_servers = len(config)
        logger.info(f"配置文件加载并验证成功，共 {total_config_servers} 个后端配置。")

        display_status_on_console(f"🔌 正在连接 {total_config_servers} 个后端...", app_state=app.state, total_servers=total_config_servers)
        log_server_status_to_file(f"🔌 正在连接 {total_config_servers} 个后端...", app_state=app.state, total_servers=total_config_servers)
        await manager.start_all(config)
        active_sessions = manager._sessions 
        connected_count = len(active_sessions)
        
        status_conn_msg = f"🔌 后端连接中 ({connected_count}/{total_config_servers} 已连接)"
        log_level_conn = logging.INFO
        if connected_count < total_config_servers:
            logger.warning(f"部分后端服务器连接失败 ({connected_count}/{total_config_servers})。")
            status_conn_msg = f"⚠️ 部分后端连接失败 ({connected_count}/{total_config_servers})"
            log_level_conn = logging.WARNING
        
        display_status_on_console(status_conn_msg, app_state=app.state, connected_servers=connected_count, total_servers=total_config_servers)
        log_server_status_to_file(status_conn_msg, app_state=app.state, connected_servers=connected_count, total_servers=total_config_servers, log_level_for_file=log_level_conn)

        status_discovery_msg = f"🔍 正在发现 MCP Capabilities ({connected_count}/{total_config_servers} 已连接)"
        display_status_on_console(status_discovery_msg, app_state=app.state, connected_servers=connected_count, total_servers=total_config_servers)
        log_server_status_to_file(status_discovery_msg, app_state=app.state, connected_servers=connected_count, total_servers=total_config_servers)
        
        await registry.discover_and_register(active_sessions)
        tools_list = registry.get_aggregated_tools()

        mcp_server.manager = manager
        mcp_server.registry = registry
        logger.info("ClientManager 和 CapabilityRegistry 已附加到 mcp_server 实例。")

        logger.info("生命周期启动阶段成功完成。")
        startup_success = True
        display_status_on_console("✅ 服务器已就绪", app_state=app.state, tools_list=tools_list, connected_servers=connected_count, total_servers=total_config_servers)
        log_server_status_to_file("✅ 服务器已就绪", app_state=app.state, tools_list=tools_list, connected_servers=connected_count, total_servers=total_config_servers)
        yield
    except ConfigurationError as e:
        logger.exception(f"配置错误: {e}")
        error_msg_details = f"配置错误: {e}"
        display_status_on_console("❌ 启动失败", app_state=app.state, error_message=error_msg_details)
        log_server_status_to_file("❌ 启动失败", app_state=app.state, error_message=error_msg_details, connected_servers=connected_count, total_servers=total_config_servers, log_level_for_file=logging.ERROR)
        raise
    except BackendServerError as e:
        logger.exception(f"后端错误: {e}")
        error_msg_details = f"后端错误: {e}"
        display_status_on_console("❌ 启动失败", app_state=app.state, error_message=error_msg_details)
        log_server_status_to_file("❌ 启动失败", app_state=app.state, error_message=error_msg_details, connected_servers=connected_count, total_servers=total_config_servers, log_level_for_file=logging.ERROR)
        raise
    except Exception as e:
        logger.exception(f"应用生命周期启动时发生意外错误: {e}")
        error_msg_details = f"意外错误: {type(e).__name__} - {e}"
        display_status_on_console("❌ 启动失败", app_state=app.state, error_message=error_msg_details)
        log_server_status_to_file("❌ 启动失败", app_state=app.state, error_message=error_msg_details, connected_servers=connected_count, total_servers=total_config_servers, log_level_for_file=logging.ERROR)
        raise
    finally:
        logger.info(f"桥接服务器 '{SERVER_NAME}' 关闭流程开始...")
        display_status_on_console("🛑 正在关闭...", app_state=app.state, tools_list=tools_list, connected_servers=connected_count, total_servers=total_config_servers)
        log_server_status_to_file("🛑 正在关闭...", app_state=app.state, tools_list=tools_list, connected_servers=connected_count, total_servers=total_config_servers, log_level_for_file=logging.WARNING)
        
        if mcp_server.manager: 
            logger.info("正在停止所有后端服务器连接...")
            await mcp_server.manager.stop_all()
            logger.info("后端连接已停止。")
        elif manager: 
            logger.warning("mcp_server.manager 未设置，但 ClientManager 实例存在。尝试停止它。")
            await manager.stop_all()
            logger.info("ClientManager 停止尝试完成。")
        else:
            logger.warning("ClientManager 未初始化，跳过停止步骤。")

        final_status_msg = "✅ 服务器正常关闭。" if startup_success else f"❌ 服务器异常退出{(f' - 错误: {error_msg_details}' if error_msg_details else '')}"
        final_log_level_for_file = logging.INFO if startup_success else logging.ERROR
        
        print(f"\n--- {SERVER_NAME} 最终状态 ---")
        print(final_status_msg)
        print(f"日志文件位于: {getattr(app.state, 'actual_log_file', DEFAULT_ACTUAL_LOG_FILE)}")
        print("---")

        logger.log(final_log_level_for_file, f"最终状态: {final_status_msg}")
        logger.info(f"桥接服务器 '{SERVER_NAME}' 关闭流程完成。")


async def _forward_request_helper(prefixed_name: str, method_name: str,
                                  arguments: Optional[Dict[str, Any]],
                                  server: McpServer) -> Any:
    logger.info(
        f"开始转发请求: Capability='{prefixed_name}', 方法='{method_name}', 参数={arguments}"
    )
    registry = server.registry
    manager = server.manager
    if not registry or not manager:
        logger.error("转发请求时 mcp_server.registry 或 mcp_server.manager 未设置。这是严重的服务器内部错误。")
        raise BackendServerError("桥接服务器内部错误：核心组件未初始化。")

    route_info = registry.resolve_capability(prefixed_name)
    if not route_info:
        logger.warning(f"无法解析Capability名称 '{prefixed_name}'。MCP客户端应收到错误。")
        raise ValueError(f"Capability '{prefixed_name}' 不存在。") 

    server_name, original_name = route_info
    logger.debug(
        f"Capability '{prefixed_name}' 解析为服务器 '{server_name}' 的Capability '{original_name}'。"
    )
    session = manager.get_session(server_name)
    if not session:
        logger.error(f"无法获取服务器 '{server_name}' 的活动会话以转发 '{prefixed_name}'。")
        raise RuntimeError( 
            f"无法连接到提供Capability '{prefixed_name}' 的后端服务器 '{server_name}'。(会话不存在或已丢失)"
        )
    try:
        target_method = getattr(session, method_name)
    except AttributeError:
        logger.exception(f"内部编程错误：ClientSession 上不存在方法 '{method_name}'。")
        raise NotImplementedError(f"桥接服务器内部错误：无法找到转发方法 '{method_name}'。")

    try:
        logger.debug(
            f"正在调用后端 '{server_name}' 的方法 '{method_name}' (原始Capability: '{original_name}')"
        )
        if method_name == "call_tool":
            result = await target_method(name=original_name,
                                         arguments=arguments or {})
        elif method_name == "read_resource":
            content, mime_type = await target_method(name=original_name)
            result = mcp_types.ReadResourceResult(content=content, mime_type=mime_type)
        elif method_name == "get_prompt":
            result = await target_method(name=original_name,
                                         arguments=arguments) 
        else:
            logger.error(f"内部编程错误：未知的转发方法名称 '{method_name}'。")
            raise NotImplementedError(f"桥接服务器内部错误：无法处理此请求类型 '{method_name}'。")
        logger.info(
            f"成功从后端 '{server_name}' 收到 '{method_name}' 的结果 (Capability: '{prefixed_name}')。"
        )
        return result
    except asyncio.TimeoutError: 
        logger.error(
            f"与后端 '{server_name}' 通信超时 (Capability: '{prefixed_name}', 方法: '{method_name}')。"
        )
        raise 
    except (ConnectionError, BrokenPipeError) as e: 
        logger.error(
            f"与后端 '{server_name}' 连接丢失 (Capability: '{prefixed_name}', 方法: '{method_name}'): {type(e).__name__}"
        )
        raise 
    except BackendServerError: 
        logger.warning(f"后端 '{server_name}' 报告了一个服务器错误在处理 '{prefixed_name}' 时。")
        raise 
    except Exception as e: 
        logger.exception(
            f"转发请求给后端 '{server_name}' 时发生意外错误 (Capability: '{prefixed_name}', 方法: '{method_name}')"
        )
        raise BackendServerError(f"处理来自 '{server_name}' 的请求 '{prefixed_name}' 时发生意外后端错误: {type(e).__name__}") from e

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
async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[Any]: 
    logger.debug(f"处理 callTool: name='{name}'")
    result = await _forward_request_helper(name, "call_tool", arguments, mcp_server)
    if isinstance(result, mcp_types.CallToolResult):
        return result.content 
    logger.error(f"call_tool 转发返回了非预期的类型: {type(result)} for tool '{name}'")
    raise BackendServerError(f"调用工具 '{name}' 后端返回类型错误。")

@mcp_server.read_resource()
async def handle_read_resource(name: str) -> mcp_types.ReadResourceResult: 
    logger.debug(f"处理 readResource: name='{name}'")
    result = await _forward_request_helper(name, "read_resource", None, mcp_server)
    if isinstance(result, mcp_types.ReadResourceResult):
        return result
    logger.error(f"read_resource 转发返回了非预期的类型: {type(result)} for resource '{name}'")
    raise BackendServerError(f"读取资源 '{name}' 后端返回类型错误。")

@mcp_server.get_prompt()
async def handle_get_prompt(
        name: str,
        arguments: Optional[Dict[str, Any]] = None) -> mcp_types.GetPromptResult:
    logger.debug(f"处理 getPrompt: name='{name}'")
    result = await _forward_request_helper(name, "get_prompt", arguments, mcp_server)
    if isinstance(result, mcp_types.GetPromptResult):
        return result
    logger.error(f"get_prompt 转发返回了非预期的类型: {type(result)} for prompt '{name}'")
    raise BackendServerError(f"获取提示 '{name}' 后端返回类型错误。")

sse_transport = SseServerTransport(POST_MESSAGES_PATH)

async def handle_sse(request: Request) -> None:
    logger.debug(f"接收到新的 SSE 连接请求 (GET): {request.url}")
    global mcp_server
    if not mcp_server.manager or not mcp_server.registry: 
        logger.error("在 handle_sse 中发现 manager 或 registry 未设置。关键组件缺失，无法处理SSE连接。")
        return 
    async with sse_transport.connect_sse(
            request.scope, request.receive, request._send, 
    ) as (read_stream, write_stream):
        try:
            server_capabilities = {}
            if mcp_server.registry: 
                 server_capabilities = mcp_server.get_capabilities(
                    NotificationOptions(), {}) 
            else: 
                logger.warning("mcp_server.registry 未设置，在SSE初始化时将使用空的 capabilities。")
            logger.debug(f"为SSE连接获取到的服务器Capabilities: {server_capabilities}")
        except Exception as e: 
            logger.exception(f"为SSE连接获取 mcp_server.get_capabilities 时出错: {e}")
            server_capabilities = {} 
        init_options = InitializationOptions(
            server_name=SERVER_NAME,
            server_version=SERVER_VERSION,
            capabilities=server_capabilities,
        )
        logger.debug(f"准备运行 mcp_server.run (MCP主循环) for SSE connection with options: {init_options}")
        await mcp_server.run(read_stream, write_stream, init_options)
    logger.debug(f"SSE 连接已关闭: {request.url}")

app: Starlette = Starlette(lifespan=app_lifespan,
                           routes=[
                               Route(SSE_PATH, endpoint=handle_sse),
                               Mount(POST_MESSAGES_PATH, app=sse_transport.handle_post_message),
                           ])
logger.info(
    f"Starlette ASGI 应用 '{SERVER_NAME}' 已创建。SSE GET on {SSE_PATH}, POST on {POST_MESSAGES_PATH}"
)

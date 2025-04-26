import asyncio
import logging
import os
import argparse
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, AsyncGenerator

from rich.console import Console, Group
from rich.panel import Panel
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table, Column
from rich.text import Text
from rich.theme import Theme
from rich.markup import escape
from rich.box import MINIMAL, ROUNDED, HEAVY_EDGE
from rich.rule import Rule
from rich.padding import Padding

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.requests import Request
from starlette.types import ASGIApp

from mcp.server import Server as McpServer
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from mcp import types as mcp_types

from config_loader import load_and_validate_config, ConfigurationError
from client_manager import ClientManager
from capability_registry import CapabilityRegistry
from errors import BackendServerError, ConfigurationError

CONFIG_FILE_PATH = "config.json"
SERVER_NAME = "MCP_Bridge_Server"
SERVER_VERSION = "3.0.0"
AUTHOR = "特让他也让"
SSE_PATH = "/sse"
LOG_DIR = "logs"
POST_MESSAGES_PATH = "/messages/"

ACTUAL_LOG_FILE = os.path.join(LOG_DIR, "unknown_log.log")

logger = logging.getLogger(__name__)
client_manager_logger = logging.getLogger("client_manager")
capability_registry_logger = logging.getLogger("capability_registry")

CUSTOM_THEME = Theme({
    "info": "bold bright_green",
    "warning": "bold bright_yellow",
    "error": "bold bright_red",
    "key": "bold blue",
    "value": "white",
    "dim_value": "dim white",
    "tool_name": "bold magenta",
    "tool_desc": "default",
    "tool_header": "bold blue",
    "panel.border": "blue",
    "rule.line": "dim blue",
    "spinner": "bold blue",
    "status.ok": "bold green",
    "status.error": "bold red",
    "status.working": "bold yellow",
    "server_count": "bold green",
    "author": "italic yellow",
    "section_title": "bold underline blue"
})

console = Console(theme=CUSTOM_THEME)

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "bridge_app.log")

parser_display = argparse.ArgumentParser(add_help=False)
parser_display.add_argument('--log-level', type=str, default='info')
args_display, _ = parser_display.parse_known_args()
DISPLAY_LOG_LEVEL = args_display.log_level.upper()

mcp_server = McpServer(SERVER_NAME)
mcp_server.manager: Optional[ClientManager] = None
mcp_server.registry: Optional[CapabilityRegistry] = None
logger.debug(f"Low-level McpServer instance '{mcp_server.name}' created.")


def build_status_panel(
    status: str,
    status_icon: str = "⏳",
    tools_list: Optional[List[mcp_types.Tool]] = None,
    error_message: Optional[str] = None,
    connected_servers: int = 0,
    total_servers: int = 0,
    host: str = "未提供",
    port: int = 0,
) -> Panel:

    full_sse_url = f"http://{host}:{port}{SSE_PATH}" if port > 0 else "N/A"

    basic_info_lines = [
        Text.assemble(("👨‍💻 作者: ", "key"), (AUTHOR, "author")),
        Text.assemble(("📡 SSE URL: ", "key"), (full_sse_url, "value")),
        Text.assemble(("📝 日志级别: ", "key"), (DISPLAY_LOG_LEVEL, "value")),
        Text.assemble(("📂 日志路径: ", "key"), (ACTUAL_LOG_FILE, "dim_value")),
    ]
    if total_servers > 0:
        server_status_style = "server_count" if connected_servers == total_servers else "warning"
        basic_info_lines.append(
            Text.assemble(("🔌 后端服务: ", "key"),
                          (f"{connected_servers}/{total_servers} 已连接",
                           server_status_style)))

    basic_info_group = Padding(Group(*basic_info_lines), (0, 0, 0, 1))

    status_style = "status.working"
    if "就绪" in status or "完成" in status:
        status_style = "status.ok"
        status_icon = "✅"
    elif "错误" in status or "失败" in status:
        status_style = "status.error"
        status_icon = "❌"
    elif "关闭" in status:
        status_style = "status.error"
        status_icon = "🛑"

    status_renderables = []
    if "就绪" not in status and "错误" not in status and "关闭" not in status:
        status_renderables.append(Spinner("dots", style="spinner"))
        status_renderables.append(" ")
    status_text_part = Text(f"{status_icon} {status}", style=status_style)
    status_renderables.append(status_text_part)
    if error_message:
        status_renderables.append(
            Text(f"\n   错误详情: [error]{escape(error_message)}[/error]"))

    status_line_group = Padding(Group(*status_renderables), (0, 0, 0, 1))

    tools_section_renderables = []
    if tools_list is not None:
        tool_count = len(tools_list)

        tools_section_renderables.append(
            Text(f"🛠️ 加载的 MCP 工具 ({tool_count} 个)", style="section_title"))
        tools_section_renderables.append("")

        if tools_list:
            tool_table = Table(
                box=None,
                expand=True,
                show_header=True,
                header_style="tool_header",
                padding=(0, 1),
                show_edge=False,
            )

            tool_table.add_column("工具名称",
                                  style="tool_name",
                                  min_width=25,
                                  ratio=30,
                                  no_wrap=True)
            tool_table.add_column("工具描述", style="tool_desc", ratio=70)

            for tool in tools_list:
                first_line_desc = tool.description.strip().split(
                    '\n')[0] if tool.description else "[dim]-[/dim]"
                tool_table.add_row(tool.name, first_line_desc)
            tools_section_renderables.append(tool_table)
        else:
            tools_section_renderables.append(
                Text("[dim]未加载任何工具。", justify="center"))

    main_content_parts = [
        basic_info_group,
        Rule(style="rule.line"),
        status_line_group,
    ]
    if tools_section_renderables:
        main_content_parts.append(Rule(style="rule.line"))
        main_content_parts.extend(tools_section_renderables)

    main_content = Group(*main_content_parts)

    return Panel(main_content,
                 title=f"✨ {SERVER_NAME} v{SERVER_VERSION} ✨",
                 title_align="center",
                 border_style="panel.border",
                 box=HEAVY_EDGE,
                 expand=True,
                 padding=(1, 2))


@asynccontextmanager
async def app_lifespan(app: Starlette) -> AsyncIterator[None]:
    global mcp_server
    logger.info(f"桥接服务器 '{SERVER_NAME}' 启动流程开始...")

    host = getattr(app.state, 'host', 'N/A')
    port = getattr(app.state, 'port', 0)
    logger.debug(f"Lifespan 获取到 host='{host}', port={port}")

    manager = ClientManager()
    registry = CapabilityRegistry()
    startup_success = False
    tools_list: Optional[List[mcp_types.Tool]] = None
    error_msg = None
    connected_count = 0
    total_count = 0

    with Live(console=console, auto_refresh=False,
              vertical_overflow="visible") as live:
        try:
            live.update(build_status_panel("🚀 正在启动...",
                                           host=host,
                                           port=port,
                                           connected_servers=connected_count,
                                           total_servers=total_count),
                        refresh=True)

            logger.info(f"加载配置文件: {CONFIG_FILE_PATH}")
            live.update(build_status_panel("📄 正在加载配置...",
                                           host=host,
                                           port=port,
                                           connected_servers=connected_count,
                                           total_servers=total_count),
                        refresh=True)
            config = load_and_validate_config(CONFIG_FILE_PATH)
            total_count = len(config)
            logger.info("配置文件加载并验证成功。")

            live.update(build_status_panel(f"🔌 正在连接 {total_count} 个后端...",
                                           host=host,
                                           port=port,
                                           connected_servers=connected_count,
                                           total_servers=total_count),
                        refresh=True)
            await manager.start_all(config)
            active_sessions = manager._sessions
            connected_count = len(active_sessions)
            if connected_count < total_count:
                logger.warning(
                    f"部分后端服务器连接失败 ({connected_count}/{total_count})。")

            live.update(build_status_panel(
                f"🔍 正在发现 MCP Capabilities ({connected_count}/{total_count} 已连接)...",
                connected_servers=connected_count,
                total_servers=total_count),
                        refresh=True)
            await registry.discover_and_register(active_sessions)
            tools_list = registry.get_aggregated_tools()

            mcp_server.manager = manager
            mcp_server.registry = registry
            logger.info(
                "ClientManager 和 CapabilityRegistry 已附加到 mcp_server 实例。")

            logger.info("生命周期启动阶段成功完成。")
            startup_success = True
            live.update(build_status_panel("✅ 服务器已就绪",
                                           host=host,
                                           port=port,
                                           status_icon="✅",
                                           tools_list=tools_list,
                                           connected_servers=connected_count,
                                           total_servers=total_count),
                        refresh=True)
            yield
        except ConfigurationError as e:
            logger.exception(f"配置错误: {e}")
            error_msg = f"配置错误: {e}"
            live.update(build_status_panel("❌ 启动失败",
                                           host=host,
                                           port=port,
                                           status_icon="❌",
                                           error_message=error_msg,
                                           tools_list=None,
                                           connected_servers=connected_count,
                                           total_servers=total_count),
                        refresh=True)
            raise
        except BackendServerError as e:
            logger.exception(f"后端错误: {e}")
            error_msg = f"后端错误: {e}"
            live.update(build_status_panel("❌ 启动失败",
                                           host=host,
                                           port=port,
                                           status_icon="❌",
                                           error_message=error_msg,
                                           tools_list=None,
                                           connected_servers=connected_count,
                                           total_servers=total_count),
                        refresh=True)
            raise
        except Exception as e:
            logger.exception(f"意外错误: {e}")
            error_msg = f"意外错误: {type(e).__name__}"
            live.update(build_status_panel("❌ 启动失败",
                                           host=host,
                                           port=port,
                                           status_icon="❌",
                                           error_message=error_msg,
                                           tools_list=None,
                                           connected_servers=connected_count,
                                           total_servers=total_count),
                        refresh=True)
            raise
        finally:
            logger.info(f"桥接服务器 '{SERVER_NAME}' 关闭流程开始...")

            live.update(build_status_panel("🛑 正在关闭...",
                                           host=host,
                                           port=port,
                                           status_icon="⏳",
                                           tools_list=tools_list,
                                           connected_servers=connected_count,
                                           total_servers=total_count),
                        refresh=True)
            if startup_success and mcp_server.manager:
                logger.info("正在停止所有后端服务器连接...")
                await mcp_server.manager.stop_all()
                logger.info("后端连接已停止。")
            elif not startup_success:
                logger.info("跳过资源清理。")
            logger.info(f"桥接服务器 '{SERVER_NAME}' 已关闭。")
            final_status = "✅ 正常关闭" if startup_success else f"❌ 异常退出 {f'(错误: {error_msg})' if error_msg else ''}"
            final_icon = "✅" if startup_success else "❌"

    console.print(
        Panel(f"{final_icon} {SERVER_NAME} 关闭流程完成。", border_style="dim"))


async def _forward_request_helper(prefixed_name: str, method_name: str,
                                  arguments: Optional[Dict[str, Any]],
                                  server: McpServer) -> Any:
    logger.info(
        f"开始转发请求: Capability='{prefixed_name}', 方法='{method_name}', 参数={arguments}"
    )

    try:
        registry = server.registry
        manager = server.manager
        if not registry or not manager:
            logger.error("转发请求时无法访问 mcp_server.manager 或 mcp_server.registry。")

            raise BackendServerError("桥接服务器内部错误：服务器状态未初始化。")
    except AttributeError:
        logger.exception("转发请求时无法访问 mcp_server 上的 manager 或 registry 属性。")

        raise BackendServerError("桥接服务器内部错误：服务器状态不可访问。")

    route_info = registry.resolve_capability(prefixed_name)
    if not route_info:
        logger.warning(f"无法解析Capability名称 '{prefixed_name}'。")

        raise ValueError(f"Capability '{prefixed_name}' 不存在。")

    server_name, original_name = route_info
    logger.debug(
        f"Capability '{prefixed_name}' 解析为服务器 '{server_name}' 的Capability '{original_name}'。"
    )

    session = manager.get_session(server_name)
    if not session:
        logger.error(f"无法获取服务器 '{server_name}' 的活动会话。")

        raise RuntimeError(
            f"无法连接到提供Capability '{prefixed_name}' 的后端服务器 '{server_name}'。(会话不存在)"
        )

    try:
        target_method = getattr(session, method_name)
    except AttributeError:
        logger.exception(f"内部错误：ClientSession 上不存在方法 '{method_name}'。")

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
            result = mcp_types.ReadResourceResult(content=content,
                                                  mime_type=mime_type)
        elif method_name == "get_prompt":
            result = await target_method(name=original_name,
                                         arguments=arguments)
        else:

            logger.error(f"内部错误：未知的转发方法名称 '{method_name}'。")
            raise NotImplementedError(f"桥接服务器内部错误：无法处理此请求类型 '{method_name}'。")

        logger.info(
            f"成功从后端 '{server_name}' 收到 '{method_name}' 的结果 (Capability: '{prefixed_name}')。"
        )
        return result
        # except mcp_types.Error as e:

        #     logger.warning(
        #         f"后端 '{server_name}' 返回 MCP 错误 (Capability: '{prefixed_name}'): Type={e.type}, Msg='{e.message}'"
        #     )
        raise e
    except asyncio.TimeoutError as e:
        logger.error(
            f"与后端 '{server_name}' 通信超时 (Capability: '{prefixed_name}', 方法: '{method_name}')。"
        )

        raise e
    except (ConnectionError, BrokenPipeError) as e:
        logger.error(
            f"与后端 '{server_name}' 连接丢失 (Capability: '{prefixed_name}', 方法: '{method_name}'): {e}"
        )

        raise e
    except Exception as e:
        logger.exception(
            f"转发请求给后端 '{server_name}' 时发生意外错误 (Capability: '{prefixed_name}', 方法: '{method_name}'): {e}"
        )

        raise BackendServerError(f"处理请求时发生意外的后端错误: {type(e).__name__}") from e


@mcp_server.list_tools()
async def handle_list_tools() -> List[mcp_types.Tool]:
    logger.debug("处理 listTools 请求...")
    if not mcp_server.registry: raise BackendServerError("Registry 未设置")
    tools = mcp_server.registry.get_aggregated_tools()
    logger.info(f"返回 {len(tools)} 个工具")
    return tools


@mcp_server.list_resources()
async def handle_list_resources() -> List[mcp_types.Resource]:
    logger.debug("处理 listResources 请求...")
    if not mcp_server.registry: raise BackendServerError("Registry 未设置")
    resources = mcp_server.registry.get_aggregated_resources()
    logger.info(f"返回 {len(resources)} 个资源")
    return resources


@mcp_server.list_prompts()
async def handle_list_prompts() -> List[mcp_types.Prompt]:
    logger.debug("处理 listPrompts 请求...")
    if not mcp_server.registry: raise BackendServerError("Registry 未设置")
    prompts = mcp_server.registry.get_aggregated_prompts()
    logger.info(f"返回 {len(prompts)} 个提示")
    return prompts


@mcp_server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> list:
    logger.debug(f"处理 callTool: name='{name}'")

    result = await _forward_request_helper(name, "call_tool", arguments,
                                           mcp_server)

    if isinstance(result, mcp_types.CallToolResult):
        return result.content
    else:

        logger.error(f"call_tool 转发成功但返回了非预期的类型: {type(result)}")
        raise BackendServerError("call_tool 转发返回类型错误。")


@mcp_server.read_resource()
async def handle_read_resource(name: str) -> mcp_types.ReadResourceResult:
    logger.debug(f"处理 readResource: name='{name}'")
    result = await _forward_request_helper(name, "read_resource", None,
                                           mcp_server)

    if isinstance(result, mcp_types.ReadResourceResult):
        return result
    else:
        logger.error(f"read_resource 转发成功但返回了非预期的类型: {type(result)}")
        raise BackendServerError("read_resource 转发返回类型错误。")


@mcp_server.get_prompt()
async def handle_get_prompt(
        name: str,
        arguments: Optional[Dict[str,
                                 Any]] = None) -> mcp_types.GetPromptResult:
    logger.debug(f"处理 getPrompt: name='{name}'")
    result = await _forward_request_helper(name, "get_prompt", arguments,
                                           mcp_server)

    if isinstance(result, mcp_types.GetPromptResult):
        return result
    else:
        logger.error(f"get_prompt 转发成功但返回了非预期的类型: {type(result)}")
        raise BackendServerError("get_prompt 转发返回类型错误。")


sse_transport = SseServerTransport(POST_MESSAGES_PATH)


async def handle_sse(request: Request) -> None:

    logger.debug(f"接收到新的 SSE 连接请求 (GET): {request.url}")
    global mcp_server
    if not mcp_server.manager or not mcp_server.registry:
        logger.error("在 handle_sse 中发现 manager 或 registry 未设置。")

    async with sse_transport.connect_sse(
            request.scope,
            request.receive,
            request._send,
    ) as (read_stream, write_stream):
        try:
            server_capabilities = mcp_server.get_capabilities(
                NotificationOptions(), {})
            logger.debug(f"获取到的服务器Capabilities: {server_capabilities}")
        except Exception as e:
            logger.exception(f"获取 capabilities 出错: {e}")
            server_capabilities = {}

        init_options = InitializationOptions(
            server_name=SERVER_NAME,
            server_version=SERVER_VERSION,
            capabilities=server_capabilities,
        )
        logger.debug(f"准备运行 mcp_server.run: {init_options}")
        await mcp_server.run(read_stream, write_stream, init_options)
    logger.debug(f"SSE 连接已关闭: {request.url}")


app: Starlette = Starlette(lifespan=app_lifespan,
                           routes=[
                               Route(SSE_PATH, endpoint=handle_sse),
                               Mount(POST_MESSAGES_PATH,
                                     app=sse_transport.handle_post_message),
                           ])
logger.info(
    f"Starlette ASGI 应用已创建。SSE GET on {SSE_PATH}, POST on {POST_MESSAGES_PATH}"
)

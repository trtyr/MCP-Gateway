# mods/sse_test_server.py
import logging
import uvicorn
import asyncio
import signal
from typing import Optional  # <--- 新增导入
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.requests import Request
from mcp.server.fastmcp import FastMCP
from mcp.server import Server as McpLowLevelServer
from mcp.server.sse import SseServerTransport
from mcp.server.models import InitializationOptions
from mcp.server.lowlevel import NotificationOptions
from mcp import types as mcp_types

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[SseTestServer] %(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 创建一个名为 "SseTest" 的 FastMCP 服务器实例
mcp = FastMCP("SseTest")
logger.info("SseTest MCP Server (FastMCP) instance created.")

SSE_SERVER_HOST = "127.0.0.1"
SSE_SERVER_PORT = 8021
SSE_ENDPOINT_PATH = "/mcp_sse"
SSE_POST_MESSAGES_PATH = "/mcp_messages/"


@mcp.tool()
async def echo_sse(message: str, repeat: int = 1) -> str:
    """
    一个简单的 SSE 测试工具，它会回显接收到的消息，并可选择重复多次。
    A simple SSE test tool that echoes back the received message, optionally repeated.

    Parameters:
    message (str): 要回显的消息。The message to echo.
    repeat (int): 消息重复的次数，默认为1。Number of times to repeat the message, defaults to 1.

    Returns:
    str: 前缀为 "SSE Echo: " 的原始消息（可能重复）。The original message (possibly repeated) prefixed with "SSE Echo: ".
    """
    logger.info(
        f"Tool 'echo_sse' called with message: '{message}', repeat: {repeat}")
    response_message = f"SSE Echo: {message} " * repeat
    response = response_message.strip()
    logger.info(f"Tool 'echo_sse' responding with: '{response}'")
    return response


@mcp.prompt()
def sse_example_prompt(user_name: str) -> list[mcp_types.PromptMessage]:
    """
    一个简单的 SSE 测试提示。
    A simple SSE test prompt.

    Parameters:
    user_name (str): 用户的名字。The user's name.

    Returns:
    list[mcp_types.PromptMessage]: 一个包含用户和助手消息的列表。A list of user and assistant messages.
    """
    logger.info(
        f"Prompt 'sse_example_prompt' called with user_name: '{user_name}'")
    return [
        mcp_types.UserMessage(content=mcp_types.TextContent(
            text=f"Hello, my name is {user_name}.")),
        mcp_types.AssistantMessage(content=mcp_types.TextContent(
            text=
            f"Nice to meet you, {user_name}! How can I help you today via SSE?"
        ))
    ]


# --- Starlette App Setup for SSE Transport ---
if not isinstance(mcp._mcp_server, McpLowLevelServer):
    logger.error(
        "FastMCP instance did not initialize its internal McpServer correctly."
    )
    raise TypeError("mcp._mcp_server is not of type McpLowLevelServer")
mcp_low_level_server: McpLowLevelServer = mcp._mcp_server

sse_transport = SseServerTransport(SSE_POST_MESSAGES_PATH)
logger.info(
    f"SseServerTransport created for POST messages at {SSE_POST_MESSAGES_PATH}"
)


async def handle_sse_connection(request: Request) -> None:
    """处理传入的 SSE 连接请求 (GET 请求)"""
    logger.info(
        f"New SSE connection request from {request.client.host}:{request.client.port} to {request.url.path}"
    )
    async with sse_transport.connect_sse(
            request.scope,
            request.receive,
            request._send,  # type: ignore
    ) as (read_stream, write_stream):
        logger.debug("SSE streams established. Starting MCP protocol run.")

        try:
            server_capabilities = mcp_low_level_server.get_capabilities(
                notification_options=NotificationOptions(),
                experimental_capabilities={})
            logger.debug(
                f"Capabilities for SseTestServer: {server_capabilities}")

            init_options = InitializationOptions(
                server_name="SseTestServer",
                server_version="1.0.1",
                capabilities=server_capabilities)
            logger.debug(
                f"MCP InitializationOptions for SSE connection: {init_options}"
            )

            await mcp_low_level_server.run(read_stream, write_stream,
                                           init_options)
        except Exception as e:
            logger.exception(f"Error during MCP run for SSE connection: {e}")

    logger.info(
        f"SSE connection from {request.client.host}:{request.client.port} closed."
    )


sse_app = Starlette(
    debug=True,
    routes=[
        Route(SSE_ENDPOINT_PATH, endpoint=handle_sse_connection),
        Mount(SSE_POST_MESSAGES_PATH, app=sse_transport.handle_post_message),
    ],
    on_startup=[
        lambda: logger.info(
            f"SseTestServer Starlette app starting up. SSE GET on http://{SSE_SERVER_HOST}:{SSE_SERVER_PORT}{SSE_ENDPOINT_PATH}"
        )
    ],
    on_shutdown=[
        lambda: logger.info("SseTestServer Starlette app shutting down.")
    ])

uvicorn_server_instance: Optional[uvicorn.Server] = None


def signal_handler(sig, frame):
    logger.warning(
        f"Received signal {sig}. Initiating graceful shutdown for SseTestServer..."
    )
    if uvicorn_server_instance:
        uvicorn_server_instance.should_exit = True
    else:
        logger.error(
            "Uvicorn server instance not found for signal handling. Exiting.")
        asyncio.create_task(shutdown_event.set())


shutdown_event = asyncio.Event()


async def main_async():
    global uvicorn_server_instance

    config = uvicorn.Config(
        app=sse_app,
        host=SSE_SERVER_HOST,
        port=SSE_SERVER_PORT,
        log_level="info",
    )
    uvicorn_server_instance = uvicorn.Server(config)

    loop = asyncio.get_running_loop()
    for sig_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig_name, signal_handler, sig_name, None)
            logger.info(f"Registered signal handler for {sig_name.name}")
        except NotImplementedError:
            signal.signal(sig_name, signal_handler)
            logger.warning(
                f"Registered signal.signal handler for {sig_name.name} (Windows fallback)"
            )

    logger.info(
        f"Starting SseTest MCP Server (uvicorn.Server) on http://{SSE_SERVER_HOST}:{SSE_SERVER_PORT}"
    )

    try:
        await uvicorn_server_instance.serve()
    except KeyboardInterrupt:
        logger.info(
            "KeyboardInterrupt caught in main_async. Server should be shutting down via signal handler."
        )
    except Exception as e:
        logger.exception(f"SseTest MCP Server (uvicorn.Server) crashed: {e}")
    finally:
        logger.info(
            "SseTest MCP Server (uvicorn.Server) has shut down or is shutting down."
        )


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info(
            "SseTestServer main execution interrupted by KeyboardInterrupt. Exiting."
        )
    except SystemExit as e:
        logger.info(f"SseTestServer exiting with code {e.code}.")
    finally:
        logger.info("SseTestServer application finished.")

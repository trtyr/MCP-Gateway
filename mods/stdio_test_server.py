import logging
from mcp.server.fastmcp import FastMCP
from mcp import types as mcp_types

logging.basicConfig(
    level=logging.INFO,
    format='[StdioTestServer] %(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

mcp = FastMCP("StdioTest")
logger.info("StdioTest MCP Server instance created.")


@mcp.tool()
async def echo_stdio(message: str) -> str:
    """
    一个简单的 Stdio 测试工具，它会回显接收到的消息。
    A simple Stdio test tool that echoes back the received message.

    Parameters:
    message (str): 要回显的消息。The message to echo.

    Returns:
    str: 前缀为 "Stdio Echo: " 的原始消息。The original message prefixed with "Stdio Echo: ".
    """
    logger.info(f"Tool 'echo_stdio' called with message: '{message}'")
    response = f"Stdio Echo: {message}"
    logger.info(f"Tool 'echo_stdio' responding with: '{response}'")
    return response


@mcp.tool()
async def add_stdio(a: int, b: int) -> int:
    """
    一个简单的 Stdio 测试工具，计算两个整数的和。
    A simple Stdio test tool that calculates the sum of two integers.

    Parameters:
    a (int): 第一个整数。The first integer.
    b (int): 第二个整数。The second integer.

    Returns:
    int: 两个整数的和。The sum of the two integers.
    """
    logger.info(f"Tool 'add_stdio' called with a={a}, b={b}")
    result = a + b
    logger.info(f"Tool 'add_stdio' responding with: {result}")
    return result


@mcp.resource("x-stdio-test-resource://local/greeting")
def get_stdio_greeting() -> str:
    """
    一个简单的 Stdio 测试资源，返回一个固定的问候语。
    A simple Stdio test resource that returns a fixed greeting.
    """
    logger.info("Resource 'x-stdio-test-resource://local/greeting' requested.")
    greeting = "Hello from Stdio Test Server Resource!"
    logger.info(
        f"Resource 'x-stdio-test-resource://local/greeting' responding with: '{greeting}'"
    )
    return greeting


if __name__ == "__main__":
    logger.info("Starting StdioTest MCP Server with stdio transport...")

    try:
        mcp.run(transport="stdio")
    except Exception as e:
        logger.exception(f"StdioTest MCP Server crashed: {e}")

        import sys
        sys.exit(1)
    logger.info("StdioTest MCP Server has shut down.")

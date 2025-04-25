# stdio_servers/bash_server.py
# -*- coding: utf-8 -*-
import asyncio
import logging
import sys
from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

mcp = FastMCP("bash")


@mcp.tool()
async def bash(command: str) -> str:
    """
    在服务器上执行 bash cmd, 返回 stdout 和 stderr.

    Args:
        command: bash cmd string (e.g., "ls -l", "echo 'hello world'").

    Returns:
        含 exit code, stdout, stderr 的 formatted string.
    """
    logger.info(f"收到执行 bash 命令的请求: '{command}'")

    if not command:
        logger.warning("收到的命令为空，不执行任何操作。")
        return "错误：命令不能为空。"

    try:

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

        stdout, stderr = await asyncio.wait_for(process.communicate(),
                                                timeout=60.0)

        stdout_str = stdout.decode(sys.stdout.encoding or 'utf-8',
                                   errors='ignore').strip()
        stderr_str = stderr.decode(sys.stderr.encoding or 'utf-8',
                                   errors='ignore').strip()
        exit_code = process.returncode

        logger.info(f"命令 '{command}' 执行完成，退出码: {exit_code}")
        if stdout_str:
            logger.debug(f"命令 STDOUT: {stdout_str}")
        if stderr_str:
            logger.warning(f"命令 STDERR: {stderr_str}")

        result = f"退出码: {exit_code}\n\n"
        result += f"--- 标准输出 (STDOUT) ---\n{stdout_str}\n\n"
        result += f"--- 标准错误 (STDERR) ---\n{stderr_str}"
        return result

    except asyncio.TimeoutError:
        logger.error(f"执行命令 '{command}' 超时 (超过 60 秒)。")

        if process and process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        return f"错误：执行命令 '{command}' 超时。"
    except FileNotFoundError:
        logger.error(f"执行命令失败: shell 未找到或命令 '{command}' 无法执行。")
        return f"错误: 无法找到或执行 shell 来处理命令 '{command}'。"
    except Exception as e:
        logger.exception(f"执行命令 '{command}' 时发生意外错误: {e}")
        return f"执行命令 '{command}' 时发生错误: {e}"


if __name__ == "__main__":
    logger.info("启动 Bash  MCP 服务器 ...")

    mcp.run(transport='stdio')
    logger.info("Bash MCP 服务器已停止。")

# stdio_servers/powershell_server.py
# -*- coding: utf-8 -*-

import asyncio
import sys
import logging
from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PowerShellServer")

mcp = FastMCP("PowerShell")


@mcp.tool()
async def PowerShell(command: str) -> str:
    """
    Run specified PowerShell command.

    Args:
        command: PowerShell command string to execute.

    Returns:
        Combined stdout & stderr string from the command.
        Returns error message on failure.
    """
    logger.info(f"接收到 PowerShell 命令请求: '{command}'")
    if not command:
        logger.warning("收到的命令为空，不执行任何操作。")
        return "错误：命令不能为空。"

    if sys.platform != "win32":
        logger.error("此 PowerShell 工具目前仅支持在 Windows 上运行。")
        return "错误：此工具仅支持 Windows。"
    executable = "powershell.exe"

    try:

        process = await asyncio.create_subprocess_exec(
            executable,
            "-NonInteractive",
            "-NoProfile",
            "-Command",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

        logger.debug(f"启动 PowerShell 进程 (PID: {process.pid}) 来执行命令。")

        stdout_bytes, stderr_bytes = await process.communicate()

        stdout = stdout_bytes.decode(sys.stdout.encoding,
                                     errors='replace').strip()
        stderr = stderr_bytes.decode(sys.stderr.encoding,
                                     errors='replace').strip()

        logger.debug(
            f"PowerShell 进程 (PID: {process.pid}) 已结束，返回码: {process.returncode}"
        )
        logger.debug(f"STDOUT: {stdout}")
        logger.debug(f"STDERR: {stderr}")

        if process.returncode != 0:
            logger.warning(f"命令执行失败，返回码: {process.returncode}")

            error_message = f"命令执行失败 (返回码: {process.returncode})。\n"
            if stdout:
                error_message += f"输出:\n{stdout}\n"
            if stderr:
                error_message += f"错误:\n{stderr}"
            return error_message.strip()
        else:
            logger.info("命令执行成功。")

            result_message = ""
            if stdout:
                result_message += f"输出:\n{stdout}\n"
            if stderr:
                result_message += f"错误输出(但返回码为0):\n{stderr}"
            return result_message.strip(
            ) if result_message else "命令成功执行，但没有输出。"

    except FileNotFoundError:
        logger.error(f"找不到 PowerShell 可执行文件 '{executable}'。请确保它在系统 PATH 中。")
        return f"错误：找不到 PowerShell 可执行文件 '{executable}'。"
    except asyncio.TimeoutError:
        logger.error(f"执行 PowerShell 命令 '{command}' 超时。")

        if process and process.returncode is None:
            try:
                process.terminate()
                await process.wait()
                logger.info(f"已终止超时的 PowerShell 进程 (PID: {process.pid})。")
            except ProcessLookupError:
                logger.warning(
                    f"尝试终止超时的 PowerShell 进程 (PID: {process.pid}) 时未找到该进程。")
            except Exception as term_err:
                logger.error(f"终止超时的 PowerShell 进程时发生错误: {term_err}")
        return "错误：命令执行超时。"
    except Exception as e:
        logger.exception(f"执行 PowerShell 命令时发生意外错误: {e}")
        return f"错误：执行命令时发生意外错误 - {type(e).__name__}: {e}"


if __name__ == "__main__":
    logger.info("启动 PowerShell MCP 服务器 ...")

    mcp.run(transport='stdio')
    logger.info("PowerShell MCP 服务器已停止。")

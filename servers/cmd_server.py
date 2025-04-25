# stdio_servers/cmd_server.py
# -*- coding: utf-8 -*-

import asyncio
import sys
import logging
from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("CmdServer")

mcp = FastMCP("cmd")


@mcp.tool()
async def cmd(command: str) -> str:
    """
    执行 cmd.exe 命令并返回 stdout 和 stderr。

    Args:
        command: 要执行的 Cmd 命令 string。

    Returns:
        合并的 stdout & stderr string。
        若失败, 返回错误信息。
    """
    logger.info(f"接收到 Cmd 命令请求: '{command}'")
    if not command:
        logger.warning("收到的命令为空，不执行任何操作。")
        return "错误：命令不能为空。"

    if sys.platform != "win32":
        logger.error("此 Cmd 工具目前仅支持在 Windows 上运行。")
        return "错误：此工具仅支持 Windows。"
    executable = "cmd.exe"

    process = None
    try:

        process = await asyncio.create_subprocess_exec(
            executable,
            "/c",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

        logger.debug(f"启动 Cmd 进程 (PID: {process.pid}) 来执行命令。")

        stdout_bytes, stderr_bytes = await process.communicate()

        stdout_encoding = sys.stdout.encoding if sys.stdout.encoding else 'utf-8'
        stderr_encoding = sys.stderr.encoding if sys.stderr.encoding else 'utf-8'
        try:
            stdout = stdout_bytes.decode(stdout_encoding,
                                         errors='replace').strip()
        except Exception as decode_err_out:
            logger.warning(
                f"使用 {stdout_encoding} 解码 stdout 失败: {decode_err_out}, 尝试 utf-8"
            )
            stdout = stdout_bytes.decode('utf-8', errors='replace').strip()

        try:
            stderr = stderr_bytes.decode(stderr_encoding,
                                         errors='replace').strip()
        except Exception as decode_err_err:
            logger.warning(
                f"使用 {stderr_encoding} 解码 stderr 失败: {decode_err_err}, 尝试 utf-8"
            )
            stderr = stderr_bytes.decode('utf-8', errors='replace').strip()

        logger.debug(
            f"Cmd 进程 (PID: {process.pid}) 已结束，返回码: {process.returncode}")
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
        logger.error(f"找不到 Cmd 可执行文件 '{executable}'。请确保它在系统 PATH 中。")
        return f"错误：找不到 Cmd 可执行文件 '{executable}'。"
    except asyncio.TimeoutError:
        logger.error(f"执行 Cmd 命令 '{command}' 时发生意外超时。")
        if process and process.returncode is None:
            try:
                process.terminate()
                await process.wait()
                logger.info(f"已终止超时的 Cmd 进程 (PID: {process.pid})。")
            except ProcessLookupError:
                logger.warning(f"尝试终止超时的 Cmd 进程 (PID: {process.pid}) 时未找到该进程。")
            except Exception as term_err:
                logger.error(f"终止超时的 Cmd 进程时发生错误: {term_err}")
        return "错误：命令执行意外超时。"
    except Exception as e:
        logger.exception(f"执行 Cmd 命令时发生意外错误: {e}")
        return f"错误：执行命令时发生意外错误 - {type(e).__name__}: {e}"


if __name__ == "__main__":
    logger.info("启动 Cmd MCP 服务器 (stdio 模式)...")

    mcp.run(transport='stdio')
    logger.info("Cmd MCP 服务器已停止。")

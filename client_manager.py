import asyncio
import logging
import os
import sys
from typing import Dict, Optional, Any, List, Tuple, AsyncGenerator
from contextlib import asynccontextmanager, AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp import types as mcp_types
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
try:
    import httpx
    SSE_NETWORK_EXCEPTIONS = (httpx.ConnectError, httpx.TimeoutException,
                              httpx.NetworkError)
except ImportError:
    SSE_NETWORK_EXCEPTIONS = ()

from errors import BackendServerError, ConfigurationError

logger = logging.getLogger(__name__)

LOCAL_SSE_STARTUP_DELAY = 2.0


@asynccontextmanager
async def _manage_subprocess(
        command: str, args: List[str], env: Optional[Dict[str, str]],
        server_name: str) -> AsyncGenerator[asyncio.subprocess.Process, None]:
    process = None
    try:

        python_executable = sys.executable or "python"

        if command.lower() == "python":
            actual_command = python_executable
        else:
            actual_command = command
        logger.debug(f"[{server_name}] 确定执行命令: {actual_command}")
        logger.info(
            f"[{server_name}] 准备启动本地进程: '{actual_command}' with args {args}")
        process = await asyncio.create_subprocess_exec(
            actual_command,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ,
                **env
            } if env else None)
        logger.info(f"[{server_name}] 本地进程已启动 (PID: {process.pid})。")
        yield process
    except FileNotFoundError as fnf_err:
        logger.error(
            f"[{server_name}] _manage_subprocess 内部错误: 找不到文件或命令 - {fnf_err}",
            exc_info=True)
        raise
    except Exception as e:
        logger.error(
            f"[{server_name}] _manage_subprocess 内部发生意外错误: {type(e).__name__}: {e}",
            exc_info=True)
        raise
    finally:
        if process and process.returncode is None:
            logger.info(f"[{server_name}] 正在尝试终止本地进程 (PID: {process.pid})...")
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5.0)
                logger.info(f"[{server_name}] 本地进程 (PID: {process.pid}) 已终止。")
            except asyncio.TimeoutError:
                logger.warning(
                    f"[{server_name}] 等待本地进程 (PID: {process.pid}) 终止超时，可能需要手动清理。"
                )
            except ProcessLookupError:
                logger.warning(
                    f"[{server_name}] 尝试终止时未找到本地进程 (PID: {process.pid})，可能已自行退出。"
                )
            except Exception as term_err:
                logger.error(
                    f"[{server_name}] 终止本地进程 (PID: {process.pid}) 时发生错误: {term_err}"
                )


class ClientManager:

    def __init__(self):

        self._sessions: Dict[str, ClientSession] = {}
        self._pending_tasks: Dict[str, asyncio.Task] = {}
        self._exit_stack = AsyncExitStack()
        logger.info("客户端管理器 ClientManager 已初始化。")

    async def start_all(self, config: Dict[str, Dict[str, Any]]):

        logger.info(f"开始启动并连接所有后端服务器 (共 {len(config)} 个)...")
        tasks = []
        for server_name, server_conf in config.items():
            task = asyncio.create_task(self._start_single_server(
                server_name, server_conf),
                                       name=f"start_{server_name}")
            self._pending_tasks[server_name] = task
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        self._pending_tasks.clear()

        successful_connections = 0
        for i, result in enumerate(results):
            task_name = tasks[i].get_name()
            server_name_from_task = task_name.split(
                "start_",
                1)[1] if task_name.startswith("start_") else "unknown"
            if isinstance(result, Exception):

                if isinstance(result, Exception):
                    logger.error(
                        f"[{server_name_from_task}] 启动过程中发生未捕获的错误: {result}",
                        exc_info=result)
                elif result is True:
                    successful_connections += 1

        logger.info("所有后端服务器启动尝试已完成。")
        active_server_count = len(self._sessions)
        total_server_count = len(config)
        if active_server_count < total_server_count:
            logger.warning(
                f"部分后端服务器未能成功启动或连接。活动服务器: {active_server_count}/{total_server_count}"
            )
        else:
            logger.info(
                f"所有后端服务器 ({active_server_count}/{total_server_count}) 均已成功连接。"
            )

    async def _start_single_server(self, server_name: str,
                                   server_config: Dict[str, Any]) -> bool:

        server_type = server_config.get('type')
        logger.info(f"[{server_name}] 尝试连接，类型: {server_type}...")
        session: Optional[ClientSession] = None
        transport_context = None
        sse_process_manager = None

        try:
            if server_type == "stdio":
                logger.debug(f"[{server_name}] Stdio 类型，准备使用 stdio_client。")
                server_params = server_config.get('params')
                if not isinstance(server_params, StdioServerParameters):
                    logger.error(
                        f"[{server_name}] Stdio 配置无效，'params' 类型错误或缺失。")
                    raise ConfigurationError(
                        f"服务器 '{server_name}' 的 Stdio 配置无效。")
                transport_context = stdio_client(server_params)

            elif server_type == "sse":
                logger.debug(f"[{server_name}] SSE 类型，检查是否需要本地启动...")
                sse_command = server_config.get('command')
                sse_args = server_config.get('args', [])
                sse_env = server_config.get('env')
                server_url = server_config.get('url')

                if not isinstance(server_url, str) or not server_url:
                    logger.error(f"[{server_name}] SSE 配置无效，'url' 类型错误或缺失。")
                    raise ConfigurationError(
                        f"服务器 '{server_name}' 的 SSE 'url' 配置无效。")

                if sse_command:
                    if not isinstance(sse_command, str):
                        logger.error(
                            f"[{server_name}] SSE 本地启动配置无效，'command' 必须是字符串。")
                        raise ConfigurationError(
                            f"服务器 '{server_name}' 的 SSE 'command' 配置无效。")
                    if not isinstance(sse_args, list):
                        logger.error(
                            f"[{server_name}] SSE 本地启动配置无效，'args' 必须是列表。")
                        raise ConfigurationError(
                            f"服务器 '{server_name}' 的 SSE 'args' 配置无效。")

                    if sse_env is not None and not isinstance(sse_env, dict):
                        logger.error(
                            f"[{server_name}] SSE 本地启动配置无效，'env' 必须是字典。")
                        raise ConfigurationError(
                            f"服务器 '{server_name}' 的 SSE 'env' 配置无效。")

                    logger.info(f"[{server_name}] 配置了本地启动命令，将启动 SSE 服务器进程...")

                    sse_process_manager = _manage_subprocess(
                        sse_command, sse_args, sse_env, server_name)
                    await self._exit_stack.enter_async_context(
                        sse_process_manager)

                    logger.info(
                        f"[{server_name}] 等待 {LOCAL_SSE_STARTUP_DELAY} 秒让本地 SSE 服务器启动..."
                    )
                    await asyncio.sleep(LOCAL_SSE_STARTUP_DELAY)
                    logger.info(f"[{server_name}] 等待结束，尝试连接到 {server_url}")
                else:
                    logger.info(
                        f"[{server_name}] 未配置本地启动命令，将直接连接到外部 SSE 服务器: {server_url}"
                    )

                transport_context = sse_client(url=server_url)

            else:
                logger.error(f"[{server_name}] 未知的服务器类型: '{server_type}'")
                raise ConfigurationError(
                    f"服务器 '{server_name}' 的类型 '{server_type}' 不支持。")

            logger.debug(f"[{server_name}] 进入客户端连接上下文 ({server_type})...")
            transport_streams = await self._exit_stack.enter_async_context(
                transport_context)
            logger.debug(f"[{server_name}] 客户端连接成功 ({server_type})，获取到传输流。")

            logger.debug(f"[{server_name}] 进入 ClientSession 上下文...")
            session_context = ClientSession(*transport_streams)
            session = await self._exit_stack.enter_async_context(
                session_context)
            logger.debug(f"[{server_name}] ClientSession 实例已创建: {session}")

            logger.info(f"[{server_name}] 尝试初始化 MCP 连接...")
            await asyncio.wait_for(session.initialize(), timeout=15.0)
            logger.info(f"与服务器 '{server_name}' ({server_type}) 的 MCP 连接初始化成功。")

            self._sessions[server_name] = session
            logger.info(f"服务器 '{server_name}' ({server_type}) 已成功添加至管理器。")
            return True

        except ConfigurationError as e:
            logger.error(f"[{server_name}] 配置错误导致启动失败: {e}")
            return False
        except asyncio.TimeoutError:
            logger.error(
                f"[{server_name}] ({server_type}) 初始化 MCP 连接或本地启动后连接超时。")
            return False
        except asyncio.CancelledError:
            logger.warning(f"[{server_name}] ({server_type}) 启动任务被取消。")
            return False
        except SSE_NETWORK_EXCEPTIONS as e:
            logger.error(
                f"[{server_name}] (SSE) 网络连接错误: {type(e).__name__}: {e}")
            return False
        except (ConnectionRefusedError, BrokenPipeError, ConnectionError) as e:
            logger.error(
                f"[{server_name}] ({server_type}) 连接错误: {type(e).__name__}: {e}"
            )
            return False

        except FileNotFoundError as e:
            logger.error(
                f"[{server_name}] 尝试本地启动 {server_type} 服务器时出错: 找不到命令或文件 - {e}")
            return False
        except Exception as e:
            logger.exception(
                f"[{server_name}] ({server_type}) 启动过程中发生意外错误: {type(e).__name__}: {e}"
            )
            return False
        finally:
            self._pending_tasks.pop(server_name, None)
            logger.debug(f"[{server_name}] _start_single_server 任务完成。")

    async def stop_all(self):

        logger.info("开始关闭所有后端服务器连接和本地进程 (通过 AsyncExitStack)...")

        if self._pending_tasks:
            logger.info(f"正在取消 {len(self._pending_tasks)} 个待处理的启动任务...")
            for task in self._pending_tasks.values():
                task.cancel()
            await asyncio.gather(*self._pending_tasks.values(),
                                 return_exceptions=True)
            self._pending_tasks.clear()
            logger.info("待处理的启动任务已取消。")

        logger.info(f"正在调用 AsyncExitStack.aclose() 来清理资源 (包括连接和子进程)...")
        try:
            await self._exit_stack.aclose()
            logger.info("AsyncExitStack 已成功关闭所有上下文。")
        except Exception as e:
            logger.exception(f"关闭 AsyncExitStack 时发生错误: {e}")

        self._sessions.clear()
        logger.info("客户端管理器 ClientManager 已关闭。")

    def get_session(self, server_name: str) -> Optional[ClientSession]:

        return self._sessions.get(server_name)

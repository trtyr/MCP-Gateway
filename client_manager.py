import asyncio
import logging
import os
import sys
from typing import Dict, Optional, Any, List, Tuple, AsyncGenerator
from contextlib import asynccontextmanager, AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
try:
    import httpx

    SSE_NET_EXCS = (httpx.ConnectError, httpx.TimeoutException,
                    httpx.NetworkError, httpx.ReadTimeout, httpx.WriteTimeout,
                    httpx.PoolTimeout)
except ImportError:
    SSE_NET_EXCS = ()

from errors import BackendServerError, ConfigurationError

logger = logging.getLogger(__name__)

SSE_LOCAL_START_DELAY = 5
MCP_INIT_TIMEOUT = 15


async def _log_subproc_stream(stream: Optional[asyncio.StreamReader],
                              svr_name: str, stream_name: str):
    """异步读取并记录来自子进程流的行。"""
    if not stream:
        return
    while True:
        try:
            line_bytes = await stream.readline()
            if not line_bytes:
                logger.debug(f"[{svr_name}-{stream_name}] 流已结束 (EOF)。")
                break
            line = line_bytes.decode(errors='replace').strip()
            if line:
                logger.info(f"[{svr_name}-{stream_name}] {line}")
        except asyncio.CancelledError:
            logger.debug(f"[{svr_name}-{stream_name}] 日志记录任务已取消。")
            break
        except Exception as e_stream:
            logger.error(f"[{svr_name}-{stream_name}] 读取流时发生错误: {e_stream}",
                         exc_info=True)
            break


@asynccontextmanager
async def _manage_subproc(
        cmd_to_exec: str, args: List[str], proc_env: Optional[Dict[str, str]],
        svr_name: str) -> AsyncGenerator[asyncio.subprocess.Process, None]:
    """管理子进程的启动和终止的异步上下文管理器。"""
    process: Optional[asyncio.subprocess.Process] = None
    stdout_log_task: Optional[asyncio.Task] = None
    stderr_log_task: Optional[asyncio.Task] = None
    try:

        py_exec = sys.executable or "python"
        actual_cmd = py_exec if cmd_to_exec.lower(
        ) == "python" else cmd_to_exec

        logger.info(f"[{svr_name}] 准备启动本地进程: '{actual_cmd}' 参数: {args}")

        current_env = os.environ.copy()
        if proc_env:
            current_env.update(proc_env)

        process = await asyncio.create_subprocess_exec(
            actual_cmd,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=current_env)
        logger.info(f"[{svr_name}] 本地进程已启动 (PID: {process.pid})。")

        if process.stdout:
            stdout_log_task = asyncio.create_task(
                _log_subproc_stream(process.stdout, svr_name, "stdout"),
                name=f"{svr_name}_stdout_logger")
        if process.stderr:
            stderr_log_task = asyncio.create_task(
                _log_subproc_stream(process.stderr, svr_name, "stderr"),
                name=f"{svr_name}_stderr_logger")
        yield process
    except FileNotFoundError:
        logger.error(f"[{svr_name}] 启动本地进程错误: 命令 '{actual_cmd}' 未找到。",
                     exc_info=True)
        raise
    except Exception as e_subproc:
        logger.error(f"[{svr_name}] 启动本地进程 '{actual_cmd}' 时发生意外错误。",
                     exc_info=True)
        raise
    finally:

        if stdout_log_task and not stdout_log_task.done():
            stdout_log_task.cancel()
        if stderr_log_task and not stderr_log_task.done():
            stderr_log_task.cancel()

        if stdout_log_task or stderr_log_task:
            await asyncio.gather(stdout_log_task,
                                 stderr_log_task,
                                 return_exceptions=True)
            logger.debug(f"[{svr_name}] 子进程流日志记录任务已完成。")

        if process and process.returncode is None:
            logger.info(f"[{svr_name}] 正在尝试终止本地进程 (PID: {process.pid})...")
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=3.0)
                logger.info(f"[{svr_name}] 本地进程 (PID: {process.pid}) 已成功终止。")
            except asyncio.TimeoutError:
                logger.warning(
                    f"[{svr_name}] 终止本地进程 (PID: {process.pid}) 超时，将尝试强制终止 (kill)..."
                )
                process.kill()
                await process.wait()
                logger.info(
                    f"[{svr_name}] 本地进程 (PID: {process.pid}) 已被强制终止 (killed)。")
            except ProcessLookupError:
                logger.warning(
                    f"[{svr_name}] 尝试终止时未找到本地进程 (PID: {process.pid})。")
            except Exception as e_term:
                logger.error(
                    f"[{svr_name}] 终止本地进程 (PID: {process.pid}) 时发生错误: {e_term}",
                    exc_info=True)


def _log_backend_fail(svr_name: str,
                      svr_type: Optional[str],
                      e: Exception,
                      context: str = "启动"):
    """记录后端服务器启动或连接失败的辅助函数。"""
    svr_type_str = svr_type or '未知类型'
    if isinstance(e, asyncio.TimeoutError):
        logger.error(f"[{svr_name}] ({svr_type_str}) {context}超时。")
    elif isinstance(e, ConfigurationError):
        logger.error(f"[{svr_name}] ({svr_type_str}) 配置错误导致{context}失败: {e}")
    elif isinstance(e, (*SSE_NET_EXCS, ConnectionRefusedError, BrokenPipeError,
                        ConnectionError)):
        logger.error(
            f"[{svr_name}] ({svr_type_str}) 网络/连接错误导致{context}失败: {type(e).__name__}: {e}"
        )
    elif isinstance(e, FileNotFoundError):
        logger.error(
            f"[{svr_name}] (本地启动 {svr_type_str}) 错误: 找不到命令或文件 '{e.filename}' 导致{context}失败。"
        )
    else:
        logger.exception(
            f"[{svr_name}] ({svr_type_str}) {context}过程中发生未预料的严重错误。")


class ClientManager:
    """管理与所有后端 MCP 服务器的连接和会话。"""

    def __init__(self):
        self._sessions: Dict[str, ClientSession] = {}
        self._pending_tasks: Dict[str, asyncio.Task] = {}
        self._exit_stack = AsyncExitStack()
        logger.info("客户端管理器 ClientManager 已初始化。")

    async def _init_stdio_backend(
            self, svr_name: str,
            stdio_cfg: StdioServerParameters) -> Tuple[Any, ClientSession]:
        """初始化并连接到 Stdio 类型的后端服务器。"""
        logger.debug(f"[{svr_name}] Stdio 类型，准备使用 stdio_client。")

        transport_ctx = stdio_client(stdio_cfg)
        streams = await self._exit_stack.enter_async_context(transport_ctx)
        logger.debug(f"[{svr_name}] (stdio) 传输流已建立。")

        session_ctx = ClientSession(*streams)
        session = await self._exit_stack.enter_async_context(session_ctx)
        return transport_ctx, session

    async def _init_sse_backend(
            self, svr_name: str, sse_url: str, sse_cmd: Optional[str],
            sse_cmd_args: List[str],
            sse_cmd_env: Optional[Dict[str,
                                       str]]) -> Tuple[Any, ClientSession]:
        """初始化并连接到 SSE 类型的后端服务器，如果配置了命令则先启动它。"""
        if sse_cmd:
            logger.info(f"[{svr_name}] 配置了本地启动命令，将启动 SSE 服务器子进程...")

            await self._exit_stack.enter_async_context(
                _manage_subproc(sse_cmd, sse_cmd_args, sse_cmd_env, svr_name))
            logger.info(
                f"[{svr_name}] 等待 {SSE_LOCAL_START_DELAY} 秒让本地 SSE 服务器启动...")
            await asyncio.sleep(SSE_LOCAL_START_DELAY)

        transport_ctx = sse_client(url=sse_url)
        streams = await self._exit_stack.enter_async_context(transport_ctx)
        logger.debug(f"[{svr_name}] (sse) 传输流已建立。")

        session_ctx = ClientSession(*streams)
        session = await self._exit_stack.enter_async_context(session_ctx)
        return transport_ctx, session

    async def _start_backend_svr(self, svr_name: str,
                                 svr_conf: Dict[str, Any]) -> bool:
        """启动并初始化单个后端服务器的连接。"""
        svr_type = svr_conf.get('type')
        logger.info(f"[{svr_name}] 正在尝试连接，类型: {svr_type}...")
        session: Optional[ClientSession] = None

        try:
            if svr_type == "stdio":
                stdio_params = svr_conf.get('params')
                if not isinstance(stdio_params, StdioServerParameters):
                    raise ConfigurationError(
                        f"服务器 '{svr_name}' 的 Stdio 配置无效 ('params' 类型错误)。")
                _, session = await self._init_stdio_backend(
                    svr_name, stdio_params)

            elif svr_type == "sse":
                sse_url = svr_conf.get('url')
                if not isinstance(sse_url, str) or not sse_url:
                    raise ConfigurationError(
                        f"服务器 '{svr_name}' 的 SSE 'url' 配置无效。")

                _, session = await self._init_sse_backend(
                    svr_name, sse_url, svr_conf.get('command'),
                    svr_conf.get('args', []), svr_conf.get('env'))
            else:
                raise ConfigurationError(
                    f"服务器 '{svr_name}' 的类型 '{svr_type}' 不支持。")

            if not session:
                raise BackendServerError(
                    f"[{svr_name}] ({svr_type}) 会话未能成功创建。")

            logger.info(
                f"[{svr_name}] 尝试初始化 MCP 连接 (超时: {MCP_INIT_TIMEOUT}s)...")
            await asyncio.wait_for(session.initialize(),
                                   timeout=MCP_INIT_TIMEOUT)

            self._sessions[svr_name] = session
            logger.info(f"✅ 与服务器 '{svr_name}' ({svr_type}) 的 MCP 连接初始化成功。")
            return True

        except asyncio.CancelledError:
            logger.warning(f"[{svr_name}] ({svr_type or '未知类型'}) 启动任务被取消。")
            return False
        except Exception as e_start:
            _log_backend_fail(svr_name, svr_type, e_start, context="连接或初始化")
            return False

    async def start_all(self, config_data: Dict[str, Dict[str, Any]]):
        """根据配置启动所有后端服务器的连接。"""
        logger.info(f"开始启动并连接所有后端服务器 (共 {len(config_data)} 个)...")
        for svr_name, svr_conf in config_data.items():
            task = asyncio.create_task(self._start_backend_svr(
                svr_name, svr_conf),
                                       name=f"start_{svr_name}")
            self._pending_tasks[svr_name] = task

        if self._pending_tasks:

            results = await asyncio.gather(*self._pending_tasks.values(),
                                           return_exceptions=True)

            for svr_name, result in zip(self._pending_tasks.keys(), results):
                if isinstance(result, Exception):
                    logger.error(
                        f"[{svr_name}] 启动任务因异常 '{type(result).__name__}' 失败 (已在 _start_backend_svr 中记录)。"
                    )
                elif result is False:
                    logger.warning(
                        f"[{svr_name}] 启动任务返回 False (已在 _start_backend_svr 中记录)。"
                    )

        self._pending_tasks.clear()

        active_svrs_count = len(self._sessions)
        total_svrs_count = len(config_data)
        logger.info(
            f"所有后端服务器启动尝试已完成。活动服务器: {active_svrs_count}/{total_svrs_count}")
        if active_svrs_count < total_svrs_count:
            logger.warning("部分后端服务器未能成功启动或连接。请检查文件日志获取详细信息。")

    async def stop_all(self):
        """关闭所有活动的会话和由管理器启动的子进程。"""
        logger.info("开始关闭所有后端服务器连接和本地进程 (通过 AsyncExitStack)...")

        if self._pending_tasks:
            logger.info(f"正在取消 {len(self._pending_tasks)} 个待处理的启动任务...")
            for task in self._pending_tasks.values():
                if not task.done():
                    task.cancel()

            await asyncio.gather(*self._pending_tasks.values(),
                                 return_exceptions=True)
            self._pending_tasks.clear()
            logger.info("待处理的启动任务已请求取消并清理。")

        logger.info(f"正在调用 AsyncExitStack.aclose() 来清理所有已管理的资源...")
        try:
            await self._exit_stack.aclose()
            logger.info("AsyncExitStack 已成功关闭所有上下文 (连接和子进程)。")
        except Exception as e_aclose:
            logger.exception(
                f"关闭 AsyncExitStack 时发生错误: {e_aclose}。部分资源可能未正确释放。")

        self._sessions.clear()
        logger.info("客户端管理器 ClientManager 已关闭，所有会话已清除。")

    def get_session(self, svr_name: str) -> Optional[ClientSession]:
        """获取指定名称的后端服务器的活动会话。"""
        return self._sessions.get(svr_name)

    def get_active_session_count(self) -> int:
        """获取当前活动会话的数量。"""
        return len(self._sessions)

    def get_all_sessions(self) -> Dict[str, ClientSession]:
        """获取所有活动会话的字典副本。"""
        return self._sessions.copy()

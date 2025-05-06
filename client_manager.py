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
    SSE_NETWORK_EXCEPTIONS = (httpx.ConnectError, httpx.TimeoutException,
                              httpx.NetworkError, httpx.ReadTimeout, httpx.WriteTimeout,
                              httpx.PoolTimeout)
except ImportError:
    SSE_NETWORK_EXCEPTIONS = ()

from errors import BackendServerError, ConfigurationError

logger = logging.getLogger(__name__) # For ClientManager's own logs

DEFAULT_LOCAL_SSE_STARTUP_DELAY = 5
DEFAULT_MCP_INITIALIZE_TIMEOUT = 15

async def _log_subprocess_stream(stream: Optional[asyncio.StreamReader], server_name: str, stream_name: str):
    """Asynchronously reads and logs lines from a subprocess stream."""
    if not stream:
        return
    while True:
        try:
            line_bytes = await stream.readline()
            if not line_bytes:
                logger.debug(f"[{server_name}-{stream_name}] stream ended (EOF).")
                break
            line = line_bytes.decode(errors='replace').strip()
            if line: # Avoid logging empty lines if not desired
                logger.info(f"[{server_name}-{stream_name}] {line}")
        except asyncio.CancelledError:
            logger.debug(f"[{server_name}-{stream_name}] logging task cancelled.")
            break
        except Exception as e:
            logger.error(f"[{server_name}-{stream_name}] Error reading stream: {e}", exc_info=True)
            break

@asynccontextmanager
async def _manage_subprocess(
        command: str, args: List[str], env: Optional[Dict[str, str]],
        server_name: str) -> AsyncGenerator[asyncio.subprocess.Process, None]:
    process: Optional[asyncio.subprocess.Process] = None
    stdout_logger_task: Optional[asyncio.Task] = None
    stderr_logger_task: Optional[asyncio.Task] = None
    try:
        python_executable = sys.executable
        if not python_executable:
            logger.warning(f"[{server_name}] sys.executable is not set. Falling back to 'python'.")
            python_executable = "python"
        actual_command = python_executable if command.lower() == "python" else command
        
        logger.info(f"[{server_name}] 准备启动本地进程: '{actual_command}' with args {args}")
        
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        process = await asyncio.create_subprocess_exec(
            actual_command, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=merged_env
        )
        logger.info(f"[{server_name}] 本地进程已启动 (PID: {process.pid})。")
        
        # Start tasks to log stdout and stderr from the subprocess
        if process.stdout:
            stdout_logger_task = asyncio.create_task(
                _log_subprocess_stream(process.stdout, server_name, "stdout")
            )
        if process.stderr:
            stderr_logger_task = asyncio.create_task(
                _log_subprocess_stream(process.stderr, server_name, "stderr")
            )
        yield process
    except FileNotFoundError:
        logger.error(f"[{server_name}] 启动本地进程错误: 命令 '{actual_command}' 未找到。", exc_info=True)
        raise
    except Exception:
        logger.error(f"[{server_name}] 启动本地进程 '{actual_command}' 时发生意外错误。", exc_info=True)
        raise
    finally:
        if stdout_logger_task and not stdout_logger_task.done():
            stdout_logger_task.cancel()
        if stderr_logger_task and not stderr_logger_task.done():
            stderr_logger_task.cancel()
        
        # Wait for logger tasks to finish cancellation
        if stdout_logger_task or stderr_logger_task:
            await asyncio.gather(stdout_logger_task, stderr_logger_task, return_exceptions=True)
            logger.debug(f"[{server_name}] Subprocess stream logger tasks finished.")

        if process and process.returncode is None:
            logger.info(f"[{server_name}] 正在尝试终止本地进程 (PID: {process.pid})...")
            try:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3.0)
                    logger.info(f"[{server_name}] 本地进程 (PID: {process.pid}) 已成功终止。")
                except asyncio.TimeoutError:
                    logger.warning(f"[{server_name}] 终止本地进程 (PID: {process.pid}) 超时，将尝试强制终止 (kill)...")
                    process.kill()
                    await process.wait()
                    logger.info(f"[{server_name}] 本地进程 (PID: {process.pid}) 已被强制终止 (killed)。")
            except ProcessLookupError:
                logger.warning(f"[{server_name}] 尝试终止时未找到本地进程 (PID: {process.pid})，可能已自行退出。")
            except Exception as term_err:
                logger.error(f"[{server_name}] 终止本地进程 (PID: {process.pid}) 时发生错误: {term_err}", exc_info=True)

class ClientManager:
    def __init__(self):
        self._sessions: Dict[str, ClientSession] = {}
        self._pending_tasks: Dict[str, asyncio.Task] = {}
        self._exit_stack = AsyncExitStack()
        logger.info("客户端管理器 ClientManager 已初始化。")

    async def start_all(self, config: Dict[str, Dict[str, Any]]):
        logger.info(f"开始启动并连接所有后端服务器 (共 {len(config)} 个)...")
        for server_name, server_conf in config.items():
            task = asyncio.create_task(
                self._start_single_server(server_name, server_conf),
                name=f"start_{server_name}"
            )
            self._pending_tasks[server_name] = task
        
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks.values(), return_exceptions=True)
        self._pending_tasks.clear()

        active_server_count = len(self._sessions)
        total_server_count = len(config)
        logger.info(f"所有后端服务器启动尝试已完成。活动服务器: {active_server_count}/{total_server_count}")
        if active_server_count < total_server_count:
            logger.warning("部分后端服务器未能成功启动或连接。请检查文件日志获取详细信息。")

    async def _start_single_server(self, server_name: str, server_config: Dict[str, Any]) -> bool:
        server_type = server_config.get('type')
        logger.info(f"[{server_name}] 正在尝试连接，类型: {server_type}...")
        transport_context = None
        session: Optional[ClientSession] = None

        try:
            if server_type == "stdio":
                logger.debug(f"[{server_name}] Stdio 类型，准备使用 stdio_client。")
                stdio_params = server_config.get('params')
                if not isinstance(stdio_params, StdioServerParameters):
                    logger.error(f"[{server_name}] Stdio 配置无效: 'params' 必须是 StdioServerParameters 实例。")
                    raise ConfigurationError(f"服务器 '{server_name}' 的 Stdio 配置无效。")
                # For stdio, _manage_subprocess is part of stdio_client's responsibilities if command is involved
                # If stdio_client itself launches the process, its stdout/stderr needs to be handled by mcp.py library
                # or we'd need to wrap stdio_client if it doesn't log those streams.
                # The current _manage_subprocess is for local SSE.
                # For stdio, the mcp.py library's stdio_client handles the subprocess.
                # We assume mcp.py's stdio_client does not print subprocess output directly to console.
                # If it does, that's a library behavior we can't directly control here without modifying mcp.py
                transport_context = stdio_client(stdio_params)


            elif server_type == "sse":
                server_url = server_config.get('url')
                if not isinstance(server_url, str) or not server_url:
                    logger.error(f"[{server_name}] SSE 配置无效: 'url' 缺失或类型错误。")
                    raise ConfigurationError(f"服务器 '{server_name}' 的 SSE 'url' 配置无效。")

                sse_command = server_config.get('command')
                if sse_command:
                    logger.info(f"[{server_name}] 配置了本地启动命令，将启动 SSE 服务器子进程...")
                    sse_args = server_config.get('args', [])
                    sse_env = server_config.get('env')
                    if not isinstance(sse_args, list): raise ConfigurationError(f"[{server_name}] SSE 'args' must be a list.")
                    if sse_env is not None and not isinstance(sse_env, dict): raise ConfigurationError(f"[{server_name}] SSE 'env' must be a dict.")
                    
                    await self._exit_stack.enter_async_context(
                        _manage_subprocess(sse_command, sse_args, sse_env, server_name)
                    )
                    logger.info(f"[{server_name}] 等待 {DEFAULT_LOCAL_SSE_STARTUP_DELAY} 秒让本地 SSE 服务器启动...")
                    await asyncio.sleep(DEFAULT_LOCAL_SSE_STARTUP_DELAY)
                
                transport_context = sse_client(url=server_url)
            else:
                logger.error(f"[{server_name}] 未知的服务器类型: '{server_type}'")
                raise ConfigurationError(f"服务器 '{server_name}' 的类型 '{server_type}' 不支持。")

            transport_streams = await self._exit_stack.enter_async_context(transport_context)
            logger.debug(f"[{server_name}] ({server_type}) 传输流已建立。")

            session_context = ClientSession(*transport_streams)
            session = await self._exit_stack.enter_async_context(session_context)
            logger.debug(f"[{server_name}] ClientSession 实例已创建。")

            logger.info(f"[{server_name}] 尝试初始化 MCP 连接 (超时: {DEFAULT_MCP_INITIALIZE_TIMEOUT}s)...")
            await asyncio.wait_for(session.initialize(), timeout=DEFAULT_MCP_INITIALIZE_TIMEOUT)
            
            self._sessions[server_name] = session
            logger.info(f"✅ 与服务器 '{server_name}' ({server_type}) 的 MCP 连接初始化成功。")
            return True
        except ConfigurationError as e:
            logger.error(f"[{server_name}] ({server_type or '未知类型'}) 配置错误导致启动失败: {e}")
            return False
        except asyncio.TimeoutError:
            logger.error(f"[{server_name}] ({server_type or '未知类型'}) 操作超时。")
            return False
        except asyncio.CancelledError:
            logger.warning(f"[{server_name}] ({server_type or '未知类型'}) 启动任务被取消。")
            return False
        except (*SSE_NETWORK_EXCEPTIONS, ConnectionRefusedError, BrokenPipeError, ConnectionError) as e:
            logger.error(f"[{server_name}] ({server_type or '未知类型'}) 网络/连接错误: {type(e).__name__}: {e}")
            return False
        except FileNotFoundError as e:
             logger.error(f"[{server_name}] (本地启动 {server_type}) 错误: 找不到命令或文件 - {e.filename}")
             return False
        except Exception:
            logger.exception(f"[{server_name}] ({server_type or '未知类型'}) 启动过程中发生未预料的严重错误。")
            return False

    async def stop_all(self):
        logger.info("开始关闭所有后端服务器连接和本地进程 (通过 AsyncExitStack)...")
        if self._pending_tasks:
            logger.info(f"正在取消 {len(self._pending_tasks)} 个待处理的启动任务...")
            for task_name, task in list(self._pending_tasks.items()):
                if not task.done():
                    task.cancel()
                del self._pending_tasks[task_name]
            await asyncio.sleep(0)
            logger.info("待处理的启动任务已请求取消。")

        logger.info(f"正在调用 AsyncExitStack.aclose() 来清理所有已管理的资源...")
        try:
            await self._exit_stack.aclose()
            logger.info("AsyncExitStack 已成功关闭所有上下文 (连接和子进程)。")
        except Exception:
            logger.exception("关闭 AsyncExitStack 时发生错误。部分资源可能未正确释放。")

        self._sessions.clear()
        logger.info("客户端管理器 ClientManager 已关闭，所有会话已清除。")

    def get_session(self, server_name: str) -> Optional[ClientSession]:
        return self._sessions.get(server_name)

    def get_active_session_count(self) -> int:
        return len(self._sessions)

    def get_all_sessions(self) -> Dict[str, ClientSession]:
        return self._sessions.copy()

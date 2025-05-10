import uvicorn
import argparse
import logging
import logging.config
import sys
import os
from datetime import datetime
import copy
from typing import Tuple, Optional
import asyncio

try:
    import bridge_app
except ImportError as e_imp:
    print(f"严重错误: 无法导入 bridge_app.py. 请确保该文件存在且在PYTHONPATH中。错误: {e_imp}",
          file=sys.stderr)
    sys.exit(1)

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

BASE_LOG_CFG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple_file": {
            "format":
            '%(asctime)s - %(name)25s:%(lineno)-4d - %(levelname)-7s - %(message)s',
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "file_handler": {
            "class": "logging.FileHandler",
            "level": "DEBUG",
            "formatter": "simple_file",
            "filename": "temp_log_name.log",
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "uvicorn": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO"
        },
        "uvicorn.error": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO"
        },
        "uvicorn.access": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "WARNING"
        },
        "starlette": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO"
        },
        "bridge_app": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO"
        },
        "client_manager": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO"
        },
        "capability_registry": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO"
        },
        "config_loader": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO"
        },
        __name__: {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO"
        },
        "mcp": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO"
        },
    },
    "root": {
        "handlers": ["file_handler"],
        "level": "WARNING",
    },
}


def setup_logging(log_lvl_str: str) -> Tuple[str, str]:
    """
    设置日志系统。
    使用基于时间戳和日志级别的动态文件名。
    根据命令行参数调整特定应用模块的日志级别。
    """
    log_lvl_valid = log_lvl_str.upper()
    valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    if log_lvl_valid not in valid_levels:
        print(f"警告: 无效的日志级别 '{log_lvl_str}'. 将使用 'INFO'.")
        log_lvl_valid = 'INFO'

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_fpath = os.path.join(LOG_DIR,
                             f"bridge_server_{ts}_{log_lvl_valid}.log")

    log_cfg = copy.deepcopy(BASE_LOG_CFG)
    log_cfg['handlers']['file_handler']['filename'] = log_fpath

    app_loggers_cfg = [
        "bridge_app", "client_manager", "capability_registry", "config_loader",
        __name__, "mcp", "uvicorn", "uvicorn.error", "starlette"
    ]
    for name in app_loggers_cfg:
        if name in log_cfg['loggers']:
            log_cfg['loggers'][name]['level'] = log_lvl_valid
        else:
            log_cfg['loggers'][name] = {
                "handlers": ["file_handler"],
                "propagate": False,
                "level": log_lvl_valid
            }

    log_cfg['loggers']['uvicorn.access'][
        'level'] = 'INFO' if log_lvl_valid == 'DEBUG' else 'WARNING'
    log_cfg['root'][
        'level'] = log_lvl_valid if log_lvl_valid == 'DEBUG' else 'WARNING'

    try:
        logging.config.dictConfig(log_cfg)
        print(f"日志系统已初始化。文件日志级别: {log_lvl_valid}, 日志文件: {log_fpath}")
    except Exception as e_log_cfg:
        print(f"应用日志配置时发生错误: {e_log_cfg}", file=sys.stderr)

    return log_fpath, log_lvl_valid


uvicorn_svr_inst: Optional[uvicorn.Server] = None
module_logger = logging.getLogger(__name__)


async def main_async(host: str, port: int, log_lvl_cli: str):
    """异步主函数，用于启动和管理 Uvicorn 服务器。"""
    global uvicorn_svr_inst

    log_fpath, cfg_log_lvl = setup_logging(log_lvl_cli)

    module_logger.info(
        f"---- {bridge_app.SERVER_NAME} v{bridge_app.SERVER_VERSION} 启动 (文件日志级别: {cfg_log_lvl}) ----"
    )

    script_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_abs_path = os.path.join(script_dir, "config.json")
    module_logger.info(f"配置文件路径解析为: {cfg_abs_path}")

    if hasattr(bridge_app, 'app') and bridge_app.app:
        app_s = bridge_app.app.state
        app_s.host = host
        app_s.port = port
        app_s.actual_log_file = log_fpath
        app_s.file_log_level_configured = cfg_log_lvl
        app_s.config_file_path = cfg_abs_path
        module_logger.debug("已将配置参数存储到 app.state。")
    else:
        module_logger.error("无法在 bridge_app 中找到 'app' 对象。服务器无法启动。")
        sys.exit(1)

    uvicorn_cfg = uvicorn.Config(
        app="bridge_app:app",
        host=host,
        port=port,
        log_config=None,
        log_level=cfg_log_lvl.lower() if cfg_log_lvl == 'DEBUG' else 'warning',
    )
    uvicorn_svr_inst = uvicorn.Server(uvicorn_cfg)

    module_logger.info(f"准备启动 Uvicorn 服务器: http://{host}:{port}")
    try:
        await uvicorn_svr_inst.serve()
    except (KeyboardInterrupt, SystemExit) as e_exit:
        module_logger.info(f"服务器因 '{type(e_exit).__name__}' 停止。")

    except Exception as e_serve:
        module_logger.exception(f"Uvicorn 服务器运行时发生意外错误: {e_serve}")
        raise
    finally:
        module_logger.info(f"{bridge_app.SERVER_NAME} 已关闭或正在关闭。")


def main():
    """程序主入口，解析参数并启动异步主函数。"""
    parser = argparse.ArgumentParser(description=f"启动 MCP 桥接服务器")
    parser.add_argument('--host',
                        type=str,
                        default='0.0.0.0',
                        help='主机地址 (默认: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=9000, help='端口 (默认: 9000)')
    parser.add_argument(
        '--log-level',
        type=str,
        default='info',
        choices=['debug', 'info', 'warning', 'error', 'critical'],
        help='设置文件日志级别 (默认: info)')
    args = parser.parse_args()

    try:
        asyncio.run(
            main_async(host=args.host,
                       port=args.port,
                       log_lvl_cli=args.log_level))
    except KeyboardInterrupt:
        module_logger.info("MCP Bridge Server 主程序被 KeyboardInterrupt 中断。")
    except SystemExit as e_sys_exit:

        if e_sys_exit.code is None or e_sys_exit.code == 0:
            module_logger.info(
                f"MCP Bridge Server 主程序正常退出 (代码: {e_sys_exit.code})。")
        else:
            module_logger.error(
                f"MCP Bridge Server 主程序因 SystemExit 异常退出 (代码: {e_sys_exit.code})。"
            )
    except Exception as e_fatal:
        module_logger.exception(f"MCP Bridge Server 主程序发生未捕获的致命错误: {e_fatal}")
        sys.exit(1)
    finally:
        module_logger.info("MCP Bridge Server 应用程序执行完毕。")


if __name__ == "__main__":
    main()

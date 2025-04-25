import uvicorn
import argparse
import logging
import logging.config
import sys
import os
from datetime import datetime
import copy
import bridge_app

LOG_DIR = "logs"

os.makedirs(LOG_DIR, exist_ok=True)

BASE_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {},
    "formatters": {
        "simple_file": {
            "format":
            '%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s',
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
            "level": "INFO",
            "handlers": ["file_handler"],
            "propagate": False
        },
        "uvicorn.error": {
            "level": "INFO",
            "handlers": ["file_handler"],
            "propagate": False
        },
        "uvicorn.access": {
            "level": "WARNING",
            "handlers": ["file_handler"],
            "propagate": False
        },
        "starlette": {
            "level": "INFO",
            "handlers": ["file_handler"],
            "propagate": False
        },
        "bridge_app": {
            "level": "INFO",
            "handlers": ["file_handler"],
            "propagate": False
        },
        "client_manager": {
            "level": "INFO",
            "handlers": ["file_handler"],
            "propagate": False
        },
        "capability_registry": {
            "level": "INFO",
            "handlers": ["file_handler"],
            "propagate": False
        },
        "config_loader": {
            "level": "INFO",
            "handlers": ["file_handler"],
            "propagate": False
        },
        __name__: {
            "level": "INFO",
            "handlers": ["file_handler"],
            "propagate": False,
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["file_handler"]
    },
}


def setup_logging(log_level_str: str):
    log_level = log_level_str.upper()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dynamic_log_filename = os.path.join(LOG_DIR,
                                        f"log_{timestamp}_{log_level}.log")

    logging_config = copy.deepcopy(BASE_LOGGING_CONFIG)

    logging_config['handlers']['file_handler'][
        'filename'] = dynamic_log_filename

    logging_config['handlers']['file_handler']['level'] = log_level
    for logger_name in logging_config['loggers']:

        if logger_name == 'uvicorn.access' and log_level != 'DEBUG':
            logging_config['loggers'][logger_name]['level'] = 'WARNING'
        else:
            logging_config['loggers'][logger_name]['level'] = log_level
    logging_config['root']['level'] = log_level

    try:
        logging.config.dictConfig(logging_config)
    except ValueError as e:
        print(f"错误：无效的日志配置字典: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"应用日志配置时发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    return dynamic_log_filename


def main():
    try:
        if not os.path.exists(LOG_DIR):
            os.makedirs(LOG_DIR)
            print(f"日志目录 '{LOG_DIR}' 已创建。")
    except OSError as e:
        print(f"错误：无法创建日志目录 '{LOG_DIR}': {e}")
    try:
        from bridge_app import SERVER_NAME, SERVER_VERSION
    except ImportError as e:
        print(f"错误：无法从 bridge_app.py 导入必要的组件: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"导入 bridge_app 时发生意外错误: {e}")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description=f"启动 {SERVER_NAME} v{SERVER_VERSION}")

    parser.add_argument('--host', type=str, default='0.0.0.0', help='主机地址')
    parser.add_argument('--port', type=int, default=9000, help='端口')
    parser.add_argument(
        '--log-level',
        type=str,
        default='info',
        choices=['debug', 'info', 'warning', 'error', 'critical'],
        help='设置文件日志级别 (默认为 info)')
    parser.add_argument('--reload', action='store_true', help='启用自动重载')

    args = parser.parse_args()

    actual_log_file = setup_logging(args.log_level)

    bridge_app.ACTUAL_LOG_FILE = actual_log_file

    logger = logging.getLogger(__name__)
    logger.info(f"---- Uvicorn 启动日志 (Level: {args.log_level.upper()}) ----")

    if hasattr(bridge_app, 'app'):
        bridge_app.app.state.host = args.host
        bridge_app.app.state.port = args.port
        logger.debug(f"已将 host='{args.host}' 和 port={args.port} 存储到 app.state")
    else:
        logger.error("无法在 bridge_app 中找到 'app' 对象来存储 host/port。")

    uvicorn.run("bridge_app:app",
                host=args.host,
                port=args.port,
                log_level=args.log_level.lower(),
                log_config=None,
                reload=args.reload)


if __name__ == "__main__":
    main()

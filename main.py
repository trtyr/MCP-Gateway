import uvicorn
import argparse
import logging
import logging.config
import sys
import os
from datetime import datetime
import copy
from typing import Tuple
import bridge_app

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

BASE_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {},
    "formatters": {
        "simple_file": {
            "format": '%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s',
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
        "uvicorn": { "handlers": ["file_handler"], "propagate": False, "level": "INFO"},
        "uvicorn.error": { "handlers": ["file_handler"], "propagate": False, "level": "INFO"},
        "uvicorn.access": { "handlers": ["file_handler"], "propagate": False, "level": "WARNING"},
        "starlette": { "handlers": ["file_handler"], "propagate": False, "level": "INFO"},
        "bridge_app": { "handlers": ["file_handler"], "propagate": False, "level": "INFO"},
        "client_manager": { "handlers": ["file_handler"], "propagate": False, "level": "INFO"},
        "capability_registry": { "handlers": ["file_handler"], "propagate": False, "level": "INFO"},
        "config_loader": { "handlers": ["file_handler"], "propagate": False, "level": "INFO"},
        __name__: { "handlers": ["file_handler"], "propagate": False, "level": "INFO"},
        # Capture mcp library logs and send them to file only
        "mcp": { "handlers": ["file_handler"], "propagate": False, "level": "INFO"},
    },
    "root": {
        "handlers": ["file_handler"], # Root logger also to file
        "level": "WARNING", # Set root to WARNING to catch unconfigured loggers but be less verbose
    },
}

def setup_logging(log_level_str: str) -> Tuple[str, str]:
    log_level_validated = log_level_str.upper()
    valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    if log_level_validated not in valid_levels:
        print(f"警告: 无效的日志级别 '{log_level_str}'. 将使用 'INFO'.")
        log_level_validated = 'INFO'

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dynamic_log_filename = os.path.join(LOG_DIR, f"log_{timestamp}_{log_level_validated}.log")

    logging_config = copy.deepcopy(BASE_LOGGING_CONFIG)
    logging_config['handlers']['file_handler']['filename'] = dynamic_log_filename

    # Apply the chosen log level to our application loggers and mcp
    app_loggers = ["bridge_app", "client_manager", "capability_registry", "config_loader", __name__, "mcp"]
    for logger_name in app_loggers:
        if logger_name in logging_config['loggers']:
            logging_config['loggers'][logger_name]['level'] = log_level_validated
        else: # Should not happen if BASE_LOGGING_CONFIG is complete
            logging_config['loggers'][logger_name] = {
                "handlers": ["file_handler"],
                "propagate": False,
                "level": log_level_validated
            }
    
    # Adjust uvicorn levels based on general log_level, but access logs are less verbose by default
    logging_config['loggers']['uvicorn']['level'] = log_level_validated
    logging_config['loggers']['uvicorn.error']['level'] = log_level_validated
    if log_level_validated == 'DEBUG':
        logging_config['loggers']['uvicorn.access']['level'] = 'INFO' # Show access logs if debugging everything
    else:
        logging_config['loggers']['uvicorn.access']['level'] = 'WARNING'


    # Set root logger level - this affects libraries not explicitly configured if they propagate
    # If we want to be very strict about only our loggers, root could be higher (e.g., CRITICAL)
    # But WARNING is a reasonable default for libraries.
    logging_config['root']['level'] = log_level_validated if log_level_validated == 'DEBUG' else 'WARNING'


    try:
        logging.config.dictConfig(logging_config)
        # This print is for initial setup confirmation, goes to console.
        print(f"日志系统已初始化。文件日志级别: {log_level_validated}, 日志文件: {dynamic_log_filename}")
    except Exception as e:
        print(f"应用日志配置时发生错误: {e}", file=sys.stderr)
        sys.exit(1)

    return dynamic_log_filename, log_level_validated

def main():
    try:
        from bridge_app import SERVER_NAME, SERVER_VERSION as BRIDGE_APP_SERVER_VERSION
    except ImportError as e:
        print(f"错误：无法从 bridge_app.py 导入必要的组件: {e}", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description=f"启动 {SERVER_NAME} v{BRIDGE_APP_SERVER_VERSION}")
    parser.add_argument('--host', type=str, default='0.0.0.0', help='主机地址')
    parser.add_argument('--port', type=int, default=9000, help='端口')
    parser.add_argument(
        '--log-level',
        type=str,
        default='info',
        choices=['debug', 'info', 'warning', 'error', 'critical'],
        help='设置文件日志级别 (默认为 info)')

    args = parser.parse_args()
    actual_log_file, configured_log_level = setup_logging(args.log_level)

    module_logger = logging.getLogger(__name__) # For main.py's own file logs
    module_logger.info(f"---- Uvicorn 启动日志 (文件级别: {configured_log_level}) ----")

    if hasattr(bridge_app, 'app') and bridge_app.app:
        bridge_app.app.state.host = args.host
        bridge_app.app.state.port = args.port
        bridge_app.app.state.actual_log_file = actual_log_file
        bridge_app.app.state.file_log_level_configured = configured_log_level
        module_logger.debug("已将 host, port, actual_log_file, file_log_level_configured 存储到 app.state")
    else:
        module_logger.error("无法在 bridge_app 中找到 'app' 对象来存储应用状态。")
        print("错误: bridge_app.py 未正确初始化 Starlette 应用。", file=sys.stderr)
        sys.exit(1)
    
    # Uvicorn's log_level here primarily affects its built-in console handlers *if* log_config were not None
    # or if its loggers were not reconfigured by dictConfig.
    # Since we use dictConfig to point uvicorn loggers to our file handler and set propagate=False,
    # this uvicorn log_level parameter has less direct impact on what appears on console from uvicorn itself.
    # The main control is ensuring no console handlers are active for uvicorn loggers in our dictConfig.
    uvicorn.run(
        "bridge_app:app",
        host=args.host,
        port=args.port,
        log_config=None, # Crucial: use our dictConfig setup
        # log_level=args.log_level.lower() # This can be kept, but its effect is mostly on Uvicorn's initial state
                                        # before our dictConfig fully takes over its named loggers.
                                        # Setting it to a higher level like 'warning' might reduce initial Uvicorn chatter
                                        # if any escapes before dictConfig.
        log_level="warning" # Try setting Uvicorn's own default to warning to minimize its direct console output
    )

if __name__ == "__main__":
    main()

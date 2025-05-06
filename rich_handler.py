import logging
import os
import threading
from datetime import datetime
from typing import Optional, Type, List, Dict, Any, Tuple, Union

from rich.console import Console
from rich.highlighter import ReprHighlighter

from rich.text import Text
from rich.theme import Theme
from rich.traceback import Traceback
from rich.panel import Panel
from rich.box import ROUNDED
from rich.pretty import pretty_repr
from rich.markup import escape

CUSTOM_THEME = Theme({
    "logging.time": "cyan",
    "logging.level.debug": "bold bright_blue",
    "logging.level.info": "bold bright_green",
    "logging.level.warning": "bold bright_yellow",
    "logging.level.error": "bold bright_red",
    "logging.level.critical": "bold white on bright_red",
    "logging.logger": "bold bright_magenta",
    "logging.module": "blue",
    "logging.funcName": "green",
    "logging.lineno": "cyan",
    "logging.message": "default",
    "traceback.border": "bright_red",
    "panel.border.debug": "blue",
    "panel.border.info": "green",
    "panel.border.warning": "yellow",
    "panel.border.error": "red",
    "panel.border.critical": "bright_red",
    "logging.context": "italic yellow",
    "logging.process_thread": "blue",
})

LOG_LEVEL_ICONS = {
    logging.DEBUG: "⚙️",
    logging.INFO: "ℹ️",
    logging.WARNING: "⚠️",
    logging.ERROR: "❌",
    logging.CRITICAL: "🔥",
}


class ContextFilter(logging.Filter):
    """
    一个简单的日志过滤器，用于将上下文信息（如 server_name）添加到 LogRecord。
    """

    def __init__(self, context_info: Dict[str, Any], name: str = ''):
        super().__init__(name)

        self._context = threading.local()

        for key, value in context_info.items():
            setattr(self._context, key, value)

    def set_context(self, **kwargs):
        """在当前线程设置上下文信息"""
        for key, value in kwargs.items():
            setattr(self._context, key, value)

    def clear_context(self, *args):
        """在当前线程清除指定的上下文键"""
        for key in args:
            if hasattr(self._context, key):
                delattr(self._context, key)

    def filter(self, record: logging.LogRecord) -> bool:

        record.context_info = getattr(self._context, '__dict__', {})
        return True


class ModernRichHandler(logging.Handler):
    """
    一个使用 Rich 库提供现代化、多彩、结构化日志输出的 logging Handler。
    (v2: 增加上下文显示支持)

    特点:
    - 使用 Panel 包裹每条日志，根据级别显示不同边框颜色。
    - Panel 标题包含时间戳、级别图标/名称、记录器名称、进程/线程 ID，以及可选上下文。
    - 日志消息中可选包含代码位置（模块、函数、行号）。
    - 对字典/列表类型的日志消息使用 pretty_repr 美化。
    - 使用 Rich 的 Traceback 美化异常输出，并用 Panel 包裹。
    - 可配置时间格式、代码位置显示、Panel 内边距、上下文显示。
    - 自适应终端宽度。
    """

    def __init__(
        self,
        level: int = logging.NOTSET,
        console: Optional[Console] = None,
        markup: bool = True,
        rich_tracebacks: bool = True,
        tracebacks_width: Optional[int] = None,
        tracebacks_extra_lines: int = 3,
        tracebacks_theme: Optional[str] = None,
        tracebacks_word_wrap: bool = False,
        tracebacks_show_locals: bool = False,
        tracebacks_suppress: Optional[list] = None,
        show_path: bool = False,
        show_code_location: bool = True,
        show_context: bool = True,
        time_format: str = "%H:%M:%S",
        panel_padding: Union[int, Tuple[int, int], Tuple[int, int, int,
                                                         int]] = (0, 1),
        box_style=ROUNDED,
    ):
        """
        初始化 ModernRichHandler。
        ... (其他参数文档省略) ...
        Args:
            show_context (bool): 是否在 Panel 标题中显示来自 LogRecord 的上下文信息. 默认 True.
        """
        super().__init__(level=level)
        self.console = console or Console(theme=CUSTOM_THEME)
        self.highlighter = ReprHighlighter()
        self.markup = markup
        self.rich_tracebacks = rich_tracebacks
        self.tracebacks_width = tracebacks_width
        self.tracebacks_extra_lines = tracebacks_extra_lines
        self.tracebacks_theme = tracebacks_theme
        self.tracebacks_word_wrap = tracebacks_word_wrap
        self.tracebacks_show_locals = tracebacks_show_locals
        self.tracebacks_suppress = tracebacks_suppress or []
        self.show_path = show_path
        self.show_code_location = show_code_location
        self.show_context = show_context
        self.time_format = time_format
        self.panel_padding = panel_padding
        self.box_style = box_style

    def emit(self, record: logging.LogRecord) -> None:
        """
        格式化并发出日志记录，使用 Panel 包裹。
        """
        try:
            original_msg = record.msg
            log_time = datetime.fromtimestamp(record.created)
            log_level = record.levelno
            logger_name = record.name
            level_name = record.levelname
            level_icon = LOG_LEVEL_ICONS.get(log_level, "•")
            level_style = f"logging.level.{level_name.lower()}"
            border_style_name = f"panel.border.{level_name.lower()}"

            border_style = "dim"
            try:

                if hasattr(self.console, 'theme') and isinstance(
                        self.console.theme, Theme):
                    if border_style_name in self.console.theme.styles:
                        border_style = border_style_name

            except Exception as check_theme_err:

                print(f"Error checking theme styles: {check_theme_err}")

            title_text = Text()
            title_text.append(log_time.strftime(self.time_format),
                              style="logging.time")
            title_text.append(" | ")
            title_text.append(f"{level_icon} {level_name}", style=level_style)
            title_text.append(" | ")
            title_text.append(f"{logger_name}", style="logging.logger")
            if self.show_context and hasattr(
                    record, 'context_info') and record.context_info:
                context_str = " ".join(f"{k}={v}"
                                       for k, v in record.context_info.items())
                title_text.append(f" [{escape(context_str)}]",
                                  style="logging.context")
            pid = os.getpid()
            tid = threading.get_ident()
            short_tid = str(tid)[-5:]
            title_text.append(f" [P:{pid} T:{short_tid}]", style="dim blue")
            if self.show_path:
                pathname = record.pathname
                lineno = record.lineno
                filename = os.path.basename(pathname)
                title_text.append(f" @ {filename}:{lineno}",
                                  style="dim italic")

            content_text = Text()
            if self.show_code_location:
                module_name = record.module
                func_name = record.funcName
                line_no = record.lineno
                content_text.append(f"[{module_name}", style="logging.module")
                content_text.append(f":{func_name}", style="logging.funcName")
                content_text.append(f":{line_no}] ", style="logging.lineno")

            if isinstance(original_msg, (dict, list, tuple)):
                message_repr = pretty_repr(original_msg, expand_all=False)
                message_text = Text(message_repr, style="logging.message")
            else:
                formatted_msg = self.format(record)
                if self.markup:
                    message_text = Text.from_markup(formatted_msg,
                                                    style="logging.message")
                else:
                    message_text = Text(formatted_msg, style="logging.message")
                    message_text = self.highlighter(message_text)

            content_text.append(message_text)

            self.console.print(
                Panel(content_text,
                      title=title_text,
                      title_align="left",
                      border_style=border_style,
                      box=self.box_style,
                      padding=self.panel_padding,
                      expand=True))

            if record.exc_info and self.rich_tracebacks:
                exc_type, exc_value, exc_traceback = record.exc_info
                if exc_type and exc_value and exc_traceback:
                    traceback = Traceback.from_exception(
                        exc_type,
                        exc_value,
                        exc_traceback,
                        width=self.tracebacks_width,
                        extra_lines=self.tracebacks_extra_lines,
                        theme=self.tracebacks_theme,
                        word_wrap=self.tracebacks_word_wrap,
                        show_locals=self.tracebacks_show_locals,
                        suppress=self.tracebacks_suppress,
                    )
                    self.console.print(
                        Panel(traceback,
                              border_style="traceback.border",
                              box=ROUNDED,
                              title="Traceback",
                              title_align="left"))

        except Exception:

            self.handleError(record)

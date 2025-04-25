# MCP Gateway

## 许可证

本项目采用 GNU General Public License v3.0 许可证 - 查看[LICENSE](LICENSE)文件了解更多详情。

## 项目概述

MCP Gateway 是一个基于 Python 构建的应用程序。它扮演着**中央网关**的角色，能够连接并聚合来自多个后端 MCP 服务器（无论这些服务器使用 Stdio 还是 SSE 协议进行通信）所提供的能力。最终，它通过一个统一的 **SSE** 端点 (`/sse`) 将这些聚合后的能力暴露给上游的 MCP 客户端。

**核心优势:**

1.  **简化客户端配置:** MCP 客户端只需连接到 MCP Gateway 这一个地址，即可访问所有后端服务的功能，无需单独配置每个后端服务器。
2.  **能力聚合与编排:** 聚合来自不同源、具备多样化能力的 MCP 工具，为构建专注于特定任务领域、功能更强大的定制化智能体提供了基础。

## 项目文件结构

```plaintext
.
├── config.json                 # 核心配置文件：定义要连接和管理的后端 MCP 服务器。
├── main.py                     # 程序入口：解析命令行参数，设置日志，并启动 Web 服务器。
├── bridge_app.py               # Starlette 应用核心：处理 MCP 请求的转发、SSE 连接管理。
├── client_manager.py           # 客户端管理器：负责建立和维护与后端 MCP 服务器的连接会话。
├── capability_registry.py      # 能力注册表：动态发现、注册并管理所有后端 MCP 服务器提供的能力。
├── config_loader.py            # 配置加载器：负责加载并严格验证 config.json 文件的格式和内容。
├── errors.py                   # 自定义异常：定义项目特定的错误类型，如配置错误、后端服务器错误。
├── rich_handler.py             # Rich 日志处理器：提供美化的、结构化的控制台日志输出。
├── servers/                    # 存放内置/示例的后端 MCP 服务器脚本。
│   ├── bash_server.py          # <-- 内置 Bash 命令执行工具 (Linux/macOS/WSL)
│   ├── cmd_server.py           # <-- 内置 Windows CMD 命令执行工具 (Windows Only)
│   ├── powershell_server.py    # <-- 内置 Windows PowerShell 命令执行工具 (Windows Only)
│   └── wmi_server.py           # <-- 内置 Windows WMI 查询工具 (Windows Only)
└── logs/                       # 日志目录：存放运行时生成的日志文件 (自动创建)。
```

## 内置 MCP Server

本项目自带了四个可以直接使用的后端 MCP Server 工具，无需额外配置即可在 `config.json` 中启用：

- **Bash 命令执行工具 (`bash_server.py`)**: 在 Linux, macOS 或 WSL 环境下执行 Bash 命令。
- **Windows CMD 命令执行工具 (`cmd_server.py`)**: 在 Windows 环境下执行 CMD 命令。
- **Windows PowerShell 命令执行工具 (`powershell_server.py`)**: 在 Windows 环境下执行 PowerShell 命令。
- **Windows WMI 查询工具 (`wmi_server.py`)**: 在 Windows 环境下执行 WMI 查询。

## 安装与设置

本项目使用 Python 编写，推荐使用 `uv` 进行环境和依赖管理。

1.  **克隆仓库**

    ```bash
    git clone https://github.com/trtyr/MCP-Gateway.git
    cd MCP-Gateway
    ```

2.  **创建并激活虚拟环境**

    ```bash
    # 创建虚拟环境
    uv venv

    # 激活虚拟环境
    # Linux/macOS
    source .venv/bin/activate
    # Windows (Command Prompt/PowerShell)
    .venv\Scripts\activate
    ```

3.  **安装依赖**
    ```bash
    # 根据 pyproject.toml 安装所有必需的依赖项
    uv sync
    ```

完成以上步骤后，项目即可运行。

## 快速启动

### 获取项目帮助

你可以使用 `-h` 或 `--help` 参数查看所有可用的启动选项：

```bash
# Windows
uv run python .\main.py -h
# Linux/macOS
uv run python ./main.py -h
```

输出结果类似：

```plaintext
usage: main.py [-h] [--host HOST] [--port PORT] [--log-level {debug,info,warning,error,critical}] [--reload]

启动 MCP_Bridge_Server v3.0.0

options:
  -h, --help            show this help message and exit
  --host HOST           主机地址 (默认: 0.0.0.0)
  --port PORT           端口 (默认: 9000)
  --log-level {debug,info,warning,error,critical}
                        设置文件日志级别 (默认为 info)
  --reload              启用自动重载 (开发时使用)
```

### 启动项目

使用 `uv run python main.py` 启动服务器，可以指定 host, port 和 log-level：

```bash
# 监听所有网络接口的 9000 端口，日志级别设置为 debug
uv run python .\main.py --host 0.0.0.0 --port 9000 --log-level debug
```

启动后，你会看到类似下图的 Rich 美化控制台输出，显示服务器状态、连接信息和加载的工具：

![](./img/1.png)

### MCP 客户端连接

启动 MCP Gateway 后，你可以使用任何兼容 MCP 的客户端（如 Cline, Cursor, Claude Desktop 或自定义客户端）连接到 Gateway 提供的 SSE 端点。

默认地址为 `http://<服务器IP地址>:9000/sse` (如果使用默认端口)。

**示例 (使用 MCP Inspector 连接):**

1.  选择 `SSE` 连接类型。
2.  输入 Gateway 的 SSE URL (例如 `http://127.0.0.1:9000/sse`)。
3.  点击 `Connect`。

![](./img/2.png)

连接成功后，你可以在客户端中看到通过 Gateway 聚合的所有后端 MCP 工具：

![](./img/3.png)

### 日志

运行时日志会自动保存在项目根目录下的 `logs` 文件夹中。日志文件名包含时间戳和日志级别，方便追溯问题。

```
logs/
├── log_20240801_103000_INFO.log
└── log_20240801_110000_DEBUG.log
...
```

![](./img/4.png)

## 配置文件 (`config.json`)

核心配置文件 `config.json` 位于项目根目录，用于定义 MCP Gateway 需要连接和管理的后端 MCP 服务器。

每个条目代表一个后端服务器，键是**你为该后端服务器指定的唯一名称**（这个名称将作为其能力的**前缀**），值是一个包含服务器配置的对象。

支持两种类型的后端服务器连接：

- **`stdio`**: 通过标准输入/输出 (stdin/stdout) 与本地启动的 MCP 服务器进程通信。
- **`sse`**: 通过 Server-Sent Events (SSE) 协议与远程或本地运行的 MCP 服务器通信。

### Stdio 类型配置

适用于需要 Gateway 启动和管理其生命周期的本地 MCP 服务器进程。

**配置字段:**

- `type` (必须): 固定为 `"stdio"`。
- `command` (必须): 用于启动服务器进程的可执行命令（例如 `python`, `uv`, `node`, 或脚本/可执行文件的绝对路径）。
- `args` (必须): 传递给 `command` 的参数列表 (List of strings)。
- `env` (可选): 为子进程设置的环境变量字典 (Dict[str, str])。如果省略，子进程将继承 Gateway 的环境。

**示例:**

```json
{
  "powershell": {
    "type": "stdio",
    "command": "python",
    "args": ["servers/powershell_server.py"]
  },
  "my_custom_tool": {
    "type": "stdio",
    "command": "/path/to/my/custom_mcp_server",
    "args": ["--port", "ignored_for_stdio", "--some-flag"],
    "env": {
      "API_KEY": "your_secret_key"
    }
  }
}
```

**工作原理:** 当 MCP Gateway 启动时，它会使用指定的 `command` 和 `args` (以及可选的 `env`) 启动一个子进程。Gateway 通过该子进程的标准输入和标准输出与后端 MCP 服务器进行通信。当 Gateway 关闭时，它会尝试终止这些子进程。

### SSE 类型配置

适用于连接到已经运行的 MCP 服务器（本地或远程），或者需要 Gateway 启动一个本地 SSE 服务器进程后再连接的情况。

**配置字段:**

- `type` (必须): 固定为 `"sse"`。
- `url` (必须): 后端 MCP 服务器的 SSE 端点 URL (完整的 HTTP/HTTPS 地址)。
- `command` (可选): 如果指定，Gateway 会在启动时运行此命令来启动本地 SSE 服务器。
- `args` (可选, 仅当 `command` 指定时): 传递给 `command` 的参数列表。
- `env` (可选, 仅当 `command` 指定时): 为本地启动的子进程设置的环境变量。

**示例 1: 连接到已运行的远程 SSE 服务器**

```json
{
  "remote_search_service": {
    "type": "sse",
    "url": "https://mcp.example.com/search/sse"
  }
}
```

**示例 2: Gateway 启动本地 SSE 服务器并连接**

```json
{
  "local_sse_server": {
    "type": "sse",
    "url": "http://127.0.0.1:8080/sse",
    "command": "uv",
    "args": ["run", "python", "servers/my_local_sse_app.py", "--port", "8080"],
    "env": { "MODE": "production" }
  }
}
```

**工作原理:**

- **仅提供 `url`**: Gateway 直接尝试连接到指定的 `url`。
- **提供 `url`, `command`, `args`**: Gateway 首先使用 `command` 和 `args` 启动一个本地进程（期望该进程监听 `url` 对应的地址和端口），然后等待一小段时间（`LOCAL_SSE_STARTUP_DELAY` 定义在 `client_manager.py` 中），最后尝试连接到 `url`。当 Gateway 关闭时，它会尝试终止这个本地进程。

## 配置添加示例

以下是如何将第三方 MCP 服务器添加到 `config.json` 的示例。

### Stdio 示例: Playwright MCP

假设你想集成 Playwright 的 MCP 服务器 (`@playwright/mcp`)。

1.  **了解启动方式**: Playwright MCP 通常使用 `npx @playwright/mcp@latest` 启动。这是一个通过 `npx` 执行的 Node.js 包。

2.  **配置 `config.json`**:

    ```json
    {
      // ... 其他服务器配置 ...
      "playwright": {
        "type": "stdio",
        "command": "npx",
        "args": ["@playwright/mcp@latest"]
      }
      // ... 其他服务器配置 ...
    }
    ```

    这里，`command` 是 `npx`，`args` 是 Playwright MCP 的包名和版本。

3.  **重启 Gateway**: 保存 `config.json` 并重启 MCP Gateway。

启动后，你应该能在控制台日志和客户端中看到名为 `playwright/...` 的工具（例如 `playwright/browse`）。

![](./img/5.png)

![](./img/6.png)

![](./img/7.png)

### SSE 示例: ENScan_GO (本地启动)

假设你想集成 ENScan_GO，它是一个 Go 程序，可以通过 `./enscan --mcp` 启动，并在 `http://localhost:8080` 提供 SSE 服务。

1.  **获取可执行文件**: 下载 ENScan_GO 的可执行文件（例如 `enscan-v1.2.1-windows-amd64.exe`）并将其放置在可访问的位置（例如 `servers/` 目录或系统 PATH 中）。

2.  **配置 `config.json`**:

    ```json
    {
      // ... 其他服务器配置 ...
      "enscan": {
        "type": "sse",
        "url": "http://127.0.0.1:8080/sse", // ENScan_GO 监听的地址
        // 注意：确保路径分隔符在 Windows 上正确，或使用绝对路径
        "command": "servers/enscan-v1.2.1-windows-amd64.exe", // 可执行文件路径
        "args": ["--mcp"] // 启动参数
      }
      // ... 其他服务器配置 ...
    }
    ```

    这里，我们指定了 `type` 为 `sse`，提供了它监听的 `url`，并且通过 `command` 和 `args` 告诉 Gateway 如何启动这个本地 SSE 服务器。

3.  **重启 Gateway**: 保存 `config.json` 并重启 MCP Gateway。

Gateway 会先启动 ENScan_GO 进程，然后连接到 `http://127.0.0.1:8080/sse`。启动后，你应该能看到名为 `enscan/...` 的工具。

![](./img/8.png)

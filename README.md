# MCP Gateway

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for more details.

## Project Overview

MCP Gateway is an application built with Python. It acts as a **central gateway** that connects to and aggregates capabilities from multiple backend MCP servers (whether they communicate via Stdio or SSE protocols). Ultimately, it exposes these aggregated capabilities to upstream MCP clients through a unified **SSE** endpoint (`/sse`).

**Core Advantages:**

1.  **Simplified Client Configuration:** MCP clients only need to connect to the single address of the MCP Gateway to access the functionalities of all backend services, eliminating the need to configure each backend server individually.
2.  **Capability Aggregation & Orchestration:** Aggregates MCP tools with diverse capabilities from various sources, providing a foundation for building more powerful, customized agents focused on specific task domains.

## Project File Structure

```plaintext
.
├── config.json                     # Core configuration file: Defines the backend MCP servers to connect to and manage.
├── main.py                         # Program entry point: Parses command-line arguments, sets up logging, and starts the web server.
├── bridge_app.py                   # Starlette application core: Handles forwarding of MCP requests and SSE connection management.
├── client_manager.py               # Client manager: Responsible for establishing and maintaining connection sessions with backend MCP servers.
├── capability_registry.py          # Capability registry: Dynamically discovers, registers, and manages capabilities provided by all backend MCP servers.
├── config_loader.py                # Configuration loader: Responsible for loading and strictly validating the format and content of the `config.json` file.
├── errors.py                       # Custom exceptions: Defines project-specific error types, such as configuration errors and backend server errors.
├── rich_handler.py                 # Rich logging handler: Provides beautified, structured console log output.
├── servers/                        # Contains built-in/example backend MCP server scripts.
│   ├── bash_server.py              # <-- Built-in Bash command execution tool (Linux/macOS/WSL)
│   ├── cmd_server.py               # <-- Built-in Windows CMD command execution tool (Windows Only)
│   ├── powershell_server.py        # <-- Built-in Windows PowerShell command execution tool (Windows Only)
│   └── wmi_server.py               # <-- Built-in Windows WMI query tool (Windows Only)
└── logs/                           # Log directory: Stores runtime log files (created automatically).
```

## Built-in MCP Servers

This project comes with four backend MCP Server tools that can be used directly and enabled in `config.json` without additional configuration:

- **Bash Command Execution Tool (`bash_server.py`)**: Executes Bash commands in Linux, macOS, or WSL environments.
- **Windows CMD Command Execution Tool (`cmd_server.py`)**: Executes CMD commands in Windows environments.
- **Windows PowerShell Command Execution Tool (`powershell_server.py`)**: Executes PowerShell commands in Windows environments.
- **Windows WMI Query Tool (`wmi_server.py`)**: Executes WMI queries in Windows environments.

> If you encounter the following error in a Linux environment:
>
> ```
> error: Distribution `pywin32==310 @ registry+https://pypi.org/simple` can't be installed because it doesn't have a source distribution or wheel for the current platform>
> ```
>
> Please uninstall the `wmi` module: `uv remove wmi`

## Installation and Setup

This project is written in Python. Using `uv` for environment and dependency management is recommended.

1.  **Clone Repository**

    ```bash
    git clone https://github.com/trtyr/MCP-Gateway.git
    cd MCP-Gateway
    ```

2.  **Create and Activate Virtual Environment**

    ```bash
    # Create virtual environment
    uv venv

    # Activate virtual environment
    # Linux/macOS
    source .venv/bin/activate
    # Windows (Command Prompt/PowerShell)
    .venv\Scripts\activate
    ```

3.  **Install Dependencies**
    ```bash
    # Install all required dependencies based on pyproject.toml
    uv sync
    ```

After completing these steps, the project is ready to run.

## Quick Start

### Get Project Help

You can use the `-h` or `--help` argument to view all available startup options:

```bash
# Windows
uv run python .\main.py -h
# Linux/macOS
uv run python ./main.py -h
```

The output will be similar to this:

```plaintext
usage: main.py [-h] [--host HOST] [--port PORT] [--log-level {debug,info,warning,error,critical}]

Start MCP_Bridge_Server v3.0.0

options:
  -h, --help            show this help message and exit
  --host HOST           Host address (default: 0.0.0.0)
  --port PORT           Port (default: 9000)
  --log-level {debug,info,warning,error,critical}
                        Set file logging level (default: info)
```

### Start the Project

Use `uv run python main.py` to start the server. You can specify the `host`, `port`, and `log-level`:

```bash
# Listen on all network interfaces on port 9000, set log level to debug
uv run python .\main.py --host 0.0.0.0 --port 9000 --log-level debug
```

After starting, you will see a Rich beautified console output similar to the image below, showing the server status, connection information, and loaded tools:

![](./img/1.png)

### MCP Client Connection

After starting MCP Gateway, you can use any MCP-compatible client (such as Cline, Cursor, Claude Desktop, or a custom client) to connect to the SSE endpoint provided by the Gateway.

The default address is `http://<Server_IP_Address>:9000/sse` (if using the default port).

**Example (Using ChatWise Connect):**

1.  Select `SSE` connection type.
2.  Enter the Gateway's SSE URL (e.g., `http://127.0.0.1:9000/sse`).
3.  Click `Connect`.

![](./img/2.png)

After a successful connection, you can see all backend MCP tools aggregated through the Gateway in the client:

![](./img/3.png)

### Logs

Runtime logs are automatically saved in the `logs` folder in the project root directory. Log filenames include timestamps and log levels, making it easy to trace issues.

```
logs/
├── log_20240801_103000_INFO.log
└── log_20240801_110000_DEBUG.log
...
```

![](./img/4.png)

## Configuration File (`config.json`)

The core configuration file `config.json` is located in the project root directory. It defines the backend MCP servers that MCP Gateway needs to connect to and manage.

Each entry represents a backend server. The key is the **unique name you assign to that backend server** (this name will be used as the **prefix** for its capabilities), and the value is an object containing the server's configuration.

Two types of backend server connections are supported:

- **`stdio`**: Communicates with a locally started MCP server process via standard input/output (stdin/stdout).
- **`sse`**: Communicates with a remote or locally running MCP server via the Server-Sent Events (SSE) protocol.

### Stdio Type Configuration

Suitable for local MCP server processes whose lifecycle needs to be managed by the Gateway.

**Configuration Fields:**

- `type` (required): Must be `"stdio"`.
- `command` (required): The executable command used to start the server process (e.g., `python`, `uv`, `node`, or the absolute path to a script/executable).
- `args` (required): A list of arguments (List of strings) passed to the `command`.
- `env` (optional): A dictionary of environment variables (Dict[str, str]) to set for the child process. If omitted, the child process inherits the Gateway's environment.

**Example:**

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

**How it Works:** When MCP Gateway starts, it uses the specified `command` and `args` (along with optional `env`) to launch a child process. The Gateway communicates with the backend MCP server through this child process's standard input and output. When the Gateway shuts down, it attempts to terminate these child processes.

### SSE Type Configuration

Suitable for connecting to already running MCP servers (local or remote), or cases where the Gateway needs to start a local SSE server process before connecting.

**Configuration Fields:**

- `type` (required): Must be `"sse"`.
- `url` (required): The SSE endpoint URL of the backend MCP server (full HTTP/HTTPS address).
- `command` (optional): If specified, the Gateway will run this command at startup to launch the local SSE server.
- `args` (optional, only when `command` is specified): A list of arguments passed to the `command`.
- `env` (optional, only when `command` is specified): Environment variables to set for the locally launched child process.

**Example 1: Connecting to an already running remote SSE server**

```json
{
  "remote_search_service": {
    "type": "sse",
    "url": "https://mcp.example.com/search/sse"
  }
}
```

**Example 2: Gateway starts a local SSE server and connects**

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

**How it Works:**

- **Only `url` provided**: The Gateway directly attempts to connect to the specified `url`.
- **`url`, `command`, `args` provided**: The Gateway first uses `command` and `args` to start a local process (expecting this process to listen on the address and port corresponding to `url`). It then waits for a short period (`LOCAL_SSE_STARTUP_DELAY` defined in `client_manager.py`) before attempting to connect to the `url`. When the Gateway shuts down, it attempts to terminate this local process.

## Configuration Addition Examples

Here are examples of how to add third-party MCP servers to `config.json`.

### Stdio Example: Playwright MCP

Suppose you want to integrate Playwright's MCP server (`@playwright/mcp`).

1.  **Understand Startup Method**: Playwright MCP is typically started using `npx @playwright/mcp@latest`. This is a Node.js package executed via `npx`.

2.  **Configure `config.json`**:

    ```json
    {
      // ... other server configurations ...
      "playwright": {
        "type": "stdio",
        "command": "npx",
        "args": ["@playwright/mcp@latest"]
      }
      // ... other server configurations ...
    }
    ```

    Here, `command` is `npx`, and `args` contains the Playwright MCP package name and version.

3.  **Restart Gateway**: Save `config.json` and restart MCP Gateway.

After starting, you should see tools named `playwright/...` (e.g., `playwright/browse`) in the console logs and your client.

![](./img/5.png)

![](./img/6.png)

![](./img/7.png)

### SSE Example: ENScan_GO (Local Start)

Suppose you want to integrate ENScan_GO, a Go program that can be started with `./enscan --mcp` and provides an SSE service at `http://localhost:8080`.

1.  **Get Executable File**: Download the ENScan_GO executable (e.g., `enscan-v1.2.1-windows-amd64.exe`) and place it in an accessible location (e.g., the `servers/` directory or in your system PATH).

2.  **Configure `config.json`**:

    ```json
    {
      // ... other server configurations ...
      "enscan": {
        "type": "sse",
        "url": "http://127.0.0.1:8080/sse", // Address ENScan_GO listens on
        // Note: Ensure path separators are correct on Windows, or use an absolute path
        "command": "servers/enscan-v1.2.1-windows-amd64.exe", // Path to the executable
        "args": ["--mcp"] // Startup arguments
      }
      // ... other server configurations ...
    }
    ```

    Here, we specify `type` as `sse`, provide the `url` it listens on, and use `command` and `args` to tell the Gateway how to start this local SSE server.

3.  **Restart Gateway**: Save `config.json` and restart MCP Gateway.

The Gateway will first start the ENScan_GO process, then connect to `http://127.0.0.1:8080/sse`. After starting, you should see tools named `enscan/...`.

![](./img/8.png)

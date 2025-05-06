import asyncio
import logging
from typing import Dict, List, Tuple, Optional, Type, Union, Any, cast

from mcp import types as mcp_types
from mcp import ClientSession

logger = logging.getLogger(__name__)

CAPABILITY_FETCH_TIMEOUT = 10.0 # Seconds

class CapabilityRegistry:

    def __init__(self):
        self._aggregated_tools: List[mcp_types.Tool] = []
        self._aggregated_resources: List[mcp_types.Resource] = []
        self._aggregated_prompts: List[mcp_types.Prompt] = []

        # Stores: prefixed_capability_name -> (server_name, original_capability_name)
        self._routing_map: Dict[str, Tuple[str, str]] = {}
        # Stores: original_capability_name -> server_name (to detect duplicates by original name)
        self._original_name_map: Dict[str, str] = {}
        logger.info("Capability注册表 CapabilityRegistry 已初始化。") # CapabilityRegistry initialized.

    async def _discover_and_register_capability_type(
        self,
        server_name: str,
        session: ClientSession,
        capability_type_name: str, # e.g., "tools", "resources", "prompts"
        list_method_name: str,     # e.g., "list_tools", "list_resources"
        mcp_type_class: Union[Type[mcp_types.Tool], Type[mcp_types.Resource], Type[mcp_types.Prompt]],
        target_list: List[Any], # The list to append to (_aggregated_tools, etc.)
        capability_prefix: str # Prefix to add to capability names for uniqueness
    ):
        """
        Generic helper to discover and register a specific type of capability.
        """
        logger.debug(f"[{server_name}] 开始发现 {capability_type_name}...") # Starting discovery of {capability_type_name}...
        try:
            list_method = getattr(session, list_method_name)
            logger.debug(f"[{server_name}] 请求 {capability_type_name} 列表 (超时 {CAPABILITY_FETCH_TIMEOUT}s)...") # Requesting {capability_type_name} list...
            
            # The list_xxx methods in mcp.py ClientSession return a result object
            # (e.g., ListToolsResult) which has a .tools attribute, or just a list.
            list_result = await asyncio.wait_for(list_method(), timeout=CAPABILITY_FETCH_TIMEOUT)
            
            original_capabilities: List[Any] = []
            if hasattr(list_result, capability_type_name) and isinstance(getattr(list_result, capability_type_name), list):
                original_capabilities = getattr(list_result, capability_type_name)
            elif isinstance(list_result, list): # Some SDK versions might return a direct list
                original_capabilities = list_result
            elif list_result is None: # Handle cases where None is returned
                logger.warning(f"[{server_name}] {list_method_name}() 返回了 None，预期为列表或包含 '{capability_type_name}' 属性的对象。") # {list_method_name}() returned None...
                original_capabilities = []
            else:
                logger.warning(
                    f"[{server_name}] {list_method_name}() 返回了未知类型: {type(list_result)}，无法解析 {capability_type_name} 列表。原始值: {list_result!r}"
                ) # {list_method_name}() returned unknown type...
                original_capabilities = []

            logger.debug(f"[{server_name}] 从返回结果中解析到 {len(original_capabilities)} 个原始 {capability_type_name}。") # Parsed X original {capability_type_name}.

            registered_count = 0
            for cap_item_any in original_capabilities:
                # Ensure the item is of the expected MCP type
                if not isinstance(cap_item_any, mcp_type_class):
                    logger.warning(
                        f"[{server_name}] 发现了一个非 {mcp_type_class.__name__} 类型的对象，已跳过: {cap_item_any!r}" # Discovered a non-{type} object, skipped.
                    )
                    continue
                
                # Type cast for MyPy after isinstance check
                cap_item = cast(Union[mcp_types.Tool, mcp_types.Resource, mcp_types.Prompt], cap_item_any)

                if not cap_item.name:
                    logger.warning(
                        f"[{server_name}] 发现了一个没有名称的 {capability_type_name[:-1]}，已跳过: {cap_item!r}" # Discovered a {type} without a name, skipped.
                    )
                    continue

                original_item_name = cap_item.name
                prefixed_item_name = f"{capability_prefix}{original_item_name}"

                # Check for duplicates based on the original name across all servers
                if original_item_name in self._original_name_map:
                    existing_server_for_original = self._original_name_map[original_item_name]
                    if existing_server_for_original != server_name : # If another server already registered this original name
                        logger.warning(
                            f"[{server_name}] 发现原始名称为 '{original_item_name}' 的 {capability_type_name[:-1]} 与服务器 '{existing_server_for_original}' 中的重复。"
                            f"将使用前缀 '{capability_prefix}' 创建唯一名称 '{prefixed_item_name}'。"
                        ) # Discovered {type} with original name '{original_item_name}' duplicates one from server '{existing_server_for_original}'. Will use prefix.
                    # If it's the same server, it might be an issue with the backend providing duplicates,
                    # but the prefixed name will still be unique if prefixes are unique per server.
                else:
                    self._original_name_map[original_item_name] = server_name
                
                # Check for duplicates based on the prefixed name (should be globally unique)
                if prefixed_item_name in self._routing_map:
                    # This case should ideally not happen if prefixes are unique per server.
                    # If it does, it means two different original items from (potentially) different servers
                    # resulted in the same prefixed name, or a single server provided duplicates
                    # that somehow still clashed after prefixing (unlikely with good prefixing).
                    existing_server_for_prefixed, _ = self._routing_map[prefixed_item_name]
                    logger.error(
                        f"[{server_name}] 致命冲突：前缀化后的 {capability_type_name[:-1]} 名称 '{prefixed_item_name}' (来自原始名称 '{original_item_name}') "
                        f"与已由服务器 '{existing_server_for_prefixed}' 注册的名称冲突。将忽略来自 '{server_name}' 的此项。"
                        "请检查服务器名称或能力前缀逻辑以确保唯一性。"
                    ) # Fatal conflict: prefixed {type} name '{prefixed_item_name}' conflicts...
                    continue
                
                # Create a new capability item with the prefixed name to ensure uniqueness
                # The description and other attributes are copied from the original.
                # For mcp_types.Tool, inputSchema is important.
                # For mcp_types.Prompt, arguments and messages are important.
                if mcp_type_class == mcp_types.Tool:
                    new_cap_item = mcp_types.Tool(name=prefixed_item_name, description=cap_item.description, inputSchema=getattr(cap_item, 'inputSchema', None))
                elif mcp_type_class == mcp_types.Resource:
                    new_cap_item = mcp_types.Resource(name=prefixed_item_name, description=cap_item.description, mime_type=getattr(cap_item, 'mime_type', None))
                elif mcp_type_class == mcp_types.Prompt:
                    new_cap_item = mcp_types.Prompt(name=prefixed_item_name, description=cap_item.description, arguments=getattr(cap_item, 'arguments', None), messages=getattr(cap_item, 'messages', None))
                else:
                    logger.error(f"[{server_name}] 不支持的 mcp_type_class: {mcp_type_class}") # Unsupported mcp_type_class
                    continue


                target_list.append(new_cap_item)
                self._routing_map[prefixed_item_name] = (server_name, original_item_name)
                registered_count += 1
            
            if registered_count > 0:
                logger.info(f"[{server_name}] 成功注册 {registered_count} 个唯一的 {capability_type_name} (使用前缀 '{capability_prefix}')。") # Successfully registered X unique {capability_type_name} (using prefix '{prefix}').
            else:
                logger.info(f"[{server_name}] 未发现或注册任何新的 {capability_type_name}。") # No new {capability_type_name} discovered or registered.

        except asyncio.TimeoutError:
            logger.error(
                f"[{server_name}] 调用 {list_method_name}() 超时 (超过 {CAPABILITY_FETCH_TIMEOUT}s)。" # Calling {list_method_name}() timed out.
            )
        except mcp_types.Error as e: # Catch MCP specific errors from the backend
            logger.error(
                f"[{server_name}] 调用 {list_method_name}() 时发生 MCP 错误: Type={e.type}, Msg='{e.message}'", # MCP error calling {list_method_name}()
                exc_info=False # No need for full stack trace for known MCP errors unless debugging SDK
            )
        except Exception: # Catch any other unexpected errors
            logger.exception(f"[{server_name}] 发现 {capability_type_name} 时发生未知错误。") # Unknown error discovering {capability_type_name}.


    async def discover_and_register(self, sessions: Dict[str, ClientSession]):
        logger.info(f"开始从 {len(sessions)} 个活动会话中发现并注册Capability...") # Starting capability discovery from X active sessions...
        self._aggregated_tools.clear()
        self._aggregated_resources.clear()
        self._aggregated_prompts.clear()
        self._routing_map.clear()
        self._original_name_map.clear()

        discovery_tasks = []
        for server_name, session in sessions.items():
            if not session:
                logger.warning(f"跳过服务器 '{server_name}'，因为它没有提供有效的会话。") # Skipping server X as it has no valid session.
                continue
            
            # Define a unique prefix for capabilities from this server to avoid name collisions.
            # A simple prefix is the server_name itself followed by a separator.
            # Ensure server_name doesn't contain characters problematic for MCP names if used directly.
            # For simplicity, we'll assume server_name is safe or MCP names are flexible.
            # A more robust prefixing might involve sanitizing server_name or using a hash.
            capability_prefix = f"{server_name}_" # Example prefix

            discovery_tasks.append(
                self._discover_and_register_capability_type(
                    server_name, session, "tools", "list_tools", mcp_types.Tool, self._aggregated_tools, capability_prefix
                )
            )
            discovery_tasks.append(
                self._discover_and_register_capability_type(
                    server_name, session, "resources", "list_resources", mcp_types.Resource, self._aggregated_resources, capability_prefix
                )
            )
            discovery_tasks.append(
                self._discover_and_register_capability_type(
                    server_name, session, "prompts", "list_prompts", mcp_types.Prompt, self._aggregated_prompts, capability_prefix
                )
            )

        # Gather all discovery tasks concurrently
        await asyncio.gather(*discovery_tasks, return_exceptions=True) # return_exceptions=True to not stop all on one failure
        
        logger.info("所有后端服务器的Capability发现尝试已完成。") # Capability discovery attempts for all backends completed.
        logger.info(f"聚合发现: {len(self._aggregated_tools)} 个工具, "
                    f"{len(self._aggregated_resources)} 个资源, "
                    f"{len(self._aggregated_prompts)} 个提示。") # Aggregated discovery: X tools, Y resources, Z prompts.

    def get_aggregated_tools(self) -> List[mcp_types.Tool]:
        return self._aggregated_tools

    def get_aggregated_resources(self) -> List[mcp_types.Resource]:
        return self._aggregated_resources

    def get_aggregated_prompts(self) -> List[mcp_types.Prompt]:
        return self._aggregated_prompts

    def resolve_capability(self, prefixed_capability_name: str) -> Optional[Tuple[str, str]]:
        """
        Resolves a prefixed capability name to the original server and original capability name.
        Returns (server_name, original_capability_name) or None if not found.
        """
        return self._routing_map.get(prefixed_capability_name)

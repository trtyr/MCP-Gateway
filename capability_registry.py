import asyncio
import logging
from typing import Dict, List, Tuple, Optional, Type, Union, Any, cast

from mcp import types as mcp_types
from mcp import ClientSession
from errors import CapabilityConflictError  

logger = logging.getLogger(__name__)

CAPABILITY_FETCH_TIMEOUT = 10.0  


class CapabilityRegistry:

    def __init__(self):
        self._aggregated_tools: List[mcp_types.Tool] = []
        self._aggregated_resources: List[mcp_types.Resource] = []
        self._aggregated_prompts: List[mcp_types.Prompt] = []

        
        self._routing_map: Dict[str, Tuple[str, str]] = {}
        logger.info("Capability注册表 CapabilityRegistry 已初始化。")

    async def _discover_and_register_capability_type(
        self,
        server_name: str,
        session: ClientSession,
        capability_type_name: str,  
        list_method_name: str,  
        mcp_type_class: Union[Type[mcp_types.Tool], Type[mcp_types.Resource],
                              Type[mcp_types.Prompt]],
        target_list: List[
            Any]  
        
    ):
        """
        Generic helper to discover and register a specific type of capability.
        Uses original capability names. If a name collision occurs with a capability
        from a *different* server, the new one is skipped and a warning is logged.
        """
        logger.debug(f"[{server_name}] 开始发现 {capability_type_name}...")
        try:
            list_method = getattr(session, list_method_name)
            logger.debug(
                f"[{server_name}] 请求 {capability_type_name} 列表 (超时 {CAPABILITY_FETCH_TIMEOUT}s)..."
            )

            list_result = await asyncio.wait_for(
                list_method(), timeout=CAPABILITY_FETCH_TIMEOUT)

            original_capabilities: List[Any] = []
            
            if hasattr(list_result, capability_type_name) and isinstance(
                    getattr(list_result, capability_type_name), list):
                original_capabilities = getattr(list_result,
                                                capability_type_name)
            
            elif isinstance(list_result, list):
                original_capabilities = list_result
            elif list_result is None:
                logger.warning(
                    f"[{server_name}] {list_method_name}() 返回了 None，预期为列表或包含 '{capability_type_name}' 属性的对象。"
                )
                original_capabilities = []
            else:
                logger.warning(
                    f"[{server_name}] {list_method_name}() 返回了未知类型: {type(list_result)}，无法解析 {capability_type_name} 列表。原始值: {list_result!r}"
                )
                original_capabilities = []

            logger.debug(
                f"[{server_name}] 从返回结果中解析到 {len(original_capabilities)} 个原始 {capability_type_name}。"
            )

            registered_count = 0
            for cap_item_any in original_capabilities:
                if not isinstance(cap_item_any, mcp_type_class):
                    logger.warning(
                        f"[{server_name}] 发现了一个非 {mcp_type_class.__name__} 类型的对象，已跳过: {cap_item_any!r}"
                    )
                    continue

                cap_item = cast(
                    Union[mcp_types.Tool, mcp_types.Resource,
                          mcp_types.Prompt], cap_item_any)

                if not cap_item.name:
                    logger.warning(
                        f"[{server_name}] 发现了一个没有名称的 {capability_type_name[:-1]}，已跳过: {cap_item!r}"
                    )
                    continue

                exposed_name = cap_item.name  

                if exposed_name in self._routing_map:
                    existing_server, _ = self._routing_map[exposed_name]
                    if existing_server != server_name:
                        logger.warning(
                            f"冲突: {capability_type_name[:-1]} '{exposed_name}' 已由服务器 '{existing_server}' 注册。"
                            f"来自服务器 '{server_name}' 的同名 {capability_type_name[:-1]} 将被忽略。"
                        )
                        
                        
                        continue  
                    else:
                        
                        logger.warning(
                            f"[{server_name}] 多次提供了同名的 {capability_type_name[:-1]}: '{exposed_name}'。仅注册第一个实例。"
                        )
                        continue  

                
                
                
                target_list.append(cap_item)
                self._routing_map[exposed_name] = (
                    server_name, cap_item.name
                )  
                registered_count += 1

            if registered_count > 0:
                logger.info(
                    f"[{server_name}] 成功注册 {registered_count} 个唯一的 {capability_type_name}。"
                )
            else:
                logger.info(
                    f"[{server_name}] 未发现或注册任何新的 {capability_type_name}。")

        except asyncio.TimeoutError:
            logger.error(
                f"[{server_name}] 调用 {list_method_name}() 超时 (超过 {CAPABILITY_FETCH_TIMEOUT}s)。"
            )
        except mcp_types.Error as e:
            logger.error(
                f"[{server_name}] 调用 {list_method_name}() 时发生 MCP 错误: Type={e.type}, Msg='{e.message}'",
                exc_info=False)
        except Exception:
            logger.exception(
                f"[{server_name}] 发现 {capability_type_name} 时发生未知错误。")

    async def discover_and_register(self, sessions: Dict[str, ClientSession]):
        logger.info(f"开始从 {len(sessions)} 个活动会话中发现并注册Capability...")
        self._aggregated_tools.clear()
        self._aggregated_resources.clear()
        self._aggregated_prompts.clear()
        self._routing_map.clear()
        

        discovery_tasks = []
        for server_name, session in sessions.items():
            if not session:
                logger.warning(f"跳过服务器 '{server_name}'，因为它没有提供有效的会话。")
                continue

            
            discovery_tasks.append(
                self._discover_and_register_capability_type(
                    server_name, session, "tools", "list_tools",
                    mcp_types.Tool, self._aggregated_tools))
            discovery_tasks.append(
                self._discover_and_register_capability_type(
                    server_name, session, "resources", "list_resources",
                    mcp_types.Resource, self._aggregated_resources))
            discovery_tasks.append(
                self._discover_and_register_capability_type(
                    server_name, session, "prompts", "list_prompts",
                    mcp_types.Prompt, self._aggregated_prompts))

        await asyncio.gather(*discovery_tasks, return_exceptions=True)

        logger.info("所有后端服务器的Capability发现尝试已完成。")
        logger.info(f"聚合发现: {len(self._aggregated_tools)} 个工具, "
                    f"{len(self._aggregated_resources)} 个资源, "
                    f"{len(self._aggregated_prompts)} 个提示。")

    def get_aggregated_tools(self) -> List[mcp_types.Tool]:
        return self._aggregated_tools

    def get_aggregated_resources(self) -> List[mcp_types.Resource]:
        return self._aggregated_resources

    def get_aggregated_prompts(self) -> List[mcp_types.Prompt]:
        return self._aggregated_prompts

    def resolve_capability(
            self, exposed_capability_name: str) -> Optional[Tuple[str, str]]:
        """
        Resolves an exposed capability name to the original server and original capability name on that server.
        Returns (server_name_providing_it, original_capability_name_on_that_server) or None if not found.
        """
        return self._routing_map.get(exposed_capability_name)

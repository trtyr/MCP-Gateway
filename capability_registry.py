import asyncio
import logging
from typing import Dict, List, Tuple, Optional

from mcp import types as mcp_types

from mcp import ClientSession

logger = logging.getLogger(__name__)


class CapabilityRegistry:

    def __init__(self):

        self._aggregated_tools: List[mcp_types.Tool] = []
        self._aggregated_resources: List[mcp_types.Resource] = []
        self._aggregated_prompts: List[mcp_types.Prompt] = []
        self._routing_map: Dict[str, Tuple[str, str]] = {}
        logger.info("Capability注册表 CapabilityRegistry 已初始化。")

    async def discover_and_register(self, sessions: Dict[str, ClientSession]):
        logger.info(f"开始从 {len(sessions)} 个活动会话中发现并注册Capability...")
        self._aggregated_tools.clear()
        self._aggregated_resources.clear()
        self._aggregated_prompts.clear()
        self._routing_map.clear()

        tasks = []
        for server_name, session in sessions.items():
            if not session:
                logger.warning(f"跳过服务器 '{server_name}'，因为它没有提供有效的会话。")
                continue
            tasks.append(
                asyncio.create_task(self._discover_single_server(
                    server_name, session),
                                    name=f"discover_{server_name}"))

        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("所有后端服务器的Capability发现尝试已完成。")
        logger.info(f"聚合发现: {len(self._aggregated_tools)} 个工具, "
                    f"{len(self._aggregated_resources)} 个资源, "
                    f"{len(self._aggregated_prompts)} 个提示。")

    async def _discover_single_server(self, server_name: str,
                                      session: ClientSession):

        logger.debug(f"[{server_name}] 开始发现Capability...")
        timeout_duration = 10.0

        logger.debug(f"[{server_name}] 开始发现工具...")
        try:
            logger.debug(f"[{server_name}] 请求工具列表 (超时 {timeout_duration}s)...")

            list_tools_result = await asyncio.wait_for(
                session.list_tools(), timeout=timeout_duration)
            logger.info(
                f"[{server_name}] list_tools() 调用成功，原始返回: {list_tools_result!r}"
            )

            original_tools: List[mcp_types.Tool] = []
            if hasattr(list_tools_result, 'tools') and isinstance(
                    list_tools_result.tools, list):
                original_tools = list_tools_result.tools
            elif isinstance(list_tools_result, list):
                original_tools = list_tools_result
            elif list_tools_result is None:
                logger.warning(
                    f"[{server_name}] list_tools() 返回了 None，预期为列表或包含 'tools' 属性的对象。"
                )
                original_tools = []
            else:
                logger.warning(
                    f"[{server_name}] list_tools() 返回了未知类型: {type(list_tools_result)}，无法解析工具列表。原始值: {list_tools_result!r}"
                )
                original_tools = []

            logger.debug(
                f"[{server_name}] 从返回结果中解析到 {len(original_tools)} 个原始工具。")

            registered_count = 0
            for tool in original_tools:
                if not isinstance(tool, mcp_types.Tool):
                    logger.warning(
                        f"[{server_name}] 发现了一个非 Tool 类型的对象，已跳过: {tool!r}")
                    continue
                if not tool.name:
                    logger.warning(
                        f"[{server_name}] 发现了一个没有名称的工具，已跳过: {tool!r}")
                    continue

                prefixed_name = f"{server_name}/{tool.name}"

                prefixed_tool = mcp_types.Tool(name=prefixed_name,
                                               description=tool.description,
                                               inputSchema=tool.inputSchema)
                self._aggregated_tools.append(prefixed_tool)
                self._routing_map[prefixed_name] = (server_name, tool.name)
                registered_count += 1

            if registered_count > 0:
                logger.info(f"[{server_name}] 成功注册 {registered_count} 个工具。")
            else:
                logger.info(f"[{server_name}] 未发现或注册任何工具。")

        except asyncio.TimeoutError:
            logger.error(
                f"[{server_name}] 调用 list_tools() 超时 (超过 {timeout_duration}s)。"
            )
        except mcp_types.Error as e:
            logger.error(
                f"[{server_name}] 调用 list_tools() 时发生 MCP 错误: Type={e.type}, Msg='{e.message}'",
                exc_info=True)
        except Exception as e:

            logger.exception(f"[{server_name}] 发现工具时发生未知错误: {e}")

        logger.debug(f"[{server_name}] 开始发现资源...")
        try:
            logger.debug(f"[{server_name}] 请求资源列表 (超时 {timeout_duration}s)...")
            list_resources_result = await asyncio.wait_for(
                session.list_resources(), timeout=timeout_duration)
            logger.info(
                f"[{server_name}] list_resources() 调用成功，原始返回: {list_resources_result!r}"
            )

            original_resources: List[mcp_types.Resource] = []

            if hasattr(list_resources_result, 'resources') and isinstance(
                    list_resources_result.resources, list):
                original_resources = list_resources_result.resources
            elif isinstance(list_resources_result, list):
                original_resources = list_resources_result
            elif list_resources_result is None:
                logger.warning(
                    f"[{server_name}] list_resources() 返回了 None，预期为列表或包含 'resources' 属性的对象。"
                )
                original_resources = []
            else:
                logger.warning(
                    f"[{server_name}] list_resources() 返回了未知类型: {type(list_resources_result)}，无法解析资源列表。原始值: {list_resources_result!r}"
                )
                original_resources = []

            logger.debug(
                f"[{server_name}] 从返回结果中解析到 {len(original_resources)} 个原始资源。")

            registered_count = 0
            for resource in original_resources:
                if not isinstance(resource, mcp_types.Resource):
                    logger.warning(
                        f"[{server_name}] 发现了一个非 Resource 类型的对象，已跳过: {resource!r}"
                    )
                    continue
                if not resource.name:
                    logger.warning(
                        f"[{server_name}] 发现了一个没有名称的资源，已跳过: {resource!r}")
                    continue

                prefixed_name = f"{server_name}/{resource.name}"
                prefixed_resource = mcp_types.Resource(
                    name=prefixed_name,
                    description=resource.description,
                    inputSchema=resource.inputSchema,
                    return_content_type=resource.return_content_type)
                self._aggregated_resources.append(prefixed_resource)
                self._routing_map[prefixed_name] = (server_name, resource.name)
                registered_count += 1

            if registered_count > 0:
                logger.info(f"[{server_name}] 成功注册 {registered_count} 个资源。")
            else:
                logger.info(f"[{server_name}] 未发现或注册任何资源。")

        except asyncio.TimeoutError:
            logger.error(
                f"[{server_name}] 调用 list_resources() 超时 (超过 {timeout_duration}s)。"
            )
        except mcp_types.Error as e:
            logger.error(
                f"[{server_name}] 调用 list_resources() 时发生 MCP 错误: Type={e.type}, Msg='{e.message}'",
                exc_info=True)
        except Exception as e:
            logger.exception(f"[{server_name}] 发现资源时发生未知错误: {e}")

        logger.debug(f"[{server_name}] 开始发现提示...")
        try:
            logger.debug(f"[{server_name}] 请求提示列表 (超时 {timeout_duration}s)...")
            list_prompts_result = await asyncio.wait_for(
                session.list_prompts(), timeout=timeout_duration)
            logger.info(
                f"[{server_name}] list_prompts() 调用成功，原始返回: {list_prompts_result!r}"
            )

            original_prompts: List[mcp_types.Prompt] = []

            if hasattr(list_prompts_result, 'prompts') and isinstance(
                    list_prompts_result.prompts, list):
                original_prompts = list_prompts_result.prompts
            elif isinstance(list_prompts_result, list):
                original_prompts = list_prompts_result
            elif list_prompts_result is None:
                logger.warning(
                    f"[{server_name}] list_prompts() 返回了 None，预期为列表或包含 'prompts' 属性的对象。"
                )
                original_prompts = []
            else:
                logger.warning(
                    f"[{server_name}] list_prompts() 返回了未知类型: {type(list_prompts_result)}，无法解析提示列表。原始值: {list_prompts_result!r}"
                )
                original_prompts = []

            logger.debug(
                f"[{server_name}] 从返回结果中解析到 {len(original_prompts)} 个原始提示。")

            registered_count = 0
            for prompt in original_prompts:
                if not isinstance(prompt, mcp_types.Prompt):
                    logger.warning(
                        f"[{server_name}] 发现了一个非 Prompt 类型的对象，已跳过: {prompt!r}")
                    continue
                if not prompt.name:
                    logger.warning(
                        f"[{server_name}] 发现了一个没有名称的提示，已跳过: {prompt!r}")
                    continue

                prefixed_name = f"{server_name}/{prompt.name}"
                prefixed_prompt = mcp_types.Prompt(
                    name=prefixed_name,
                    description=prompt.description,
                    inputSchema=prompt.inputSchema)
                self._aggregated_prompts.append(prefixed_prompt)
                self._routing_map[prefixed_name] = (server_name, prompt.name)
                registered_count += 1

            if registered_count > 0:
                logger.info(f"[{server_name}] 成功注册 {registered_count} 个提示。")
            else:
                logger.info(f"[{server_name}] 未发现或注册任何提示。")

        except asyncio.TimeoutError:
            logger.error(
                f"[{server_name}] 调用 list_prompts() 超时 (超过 {timeout_duration}s)。"
            )
        except mcp_types.Error as e:
            logger.error(
                f"[{server_name}] 调用 list_prompts() 时发生 MCP 错误: Type={e.type}, Msg='{e.message}'",
                exc_info=True)
        except Exception as e:
            logger.exception(f"[{server_name}] 发现提示时发生未知错误: {e}")

        logger.debug(f"[{server_name}] Capability发现完成。")

    def get_aggregated_tools(self) -> List[mcp_types.Tool]:

        return self._aggregated_tools

    def get_aggregated_resources(self) -> List[mcp_types.Resource]:

        return self._aggregated_resources

    def get_aggregated_prompts(self) -> List[mcp_types.Prompt]:

        return self._aggregated_prompts

    def resolve_capability(self,
                           prefixed_name: str) -> Optional[Tuple[str, str]]:

        return self._routing_map.get(prefixed_name)

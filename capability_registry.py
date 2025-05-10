import asyncio
import logging
from typing import Dict, List, Tuple, Optional, Type, Union, Any, cast

from mcp import types as mcp_types
from mcp import ClientSession

logger = logging.getLogger(__name__)

CAP_FETCH_TIMEOUT = 10.0


class CapabilityRegistry:
    """负责发现、注册和路由来自多个后端服务器的 MCP 能力。"""

    def __init__(self):

        self._tools: List[mcp_types.Tool] = []
        self._resources: List[mcp_types.Resource] = []
        self._prompts: List[mcp_types.Prompt] = []

        self._route_map: Dict[str, Tuple[str, str]] = {}
        logger.info("能力注册表 CapabilityRegistry 已初始化。")

    async def _discover_caps_by_type(self, svr_name: str,
                                     session: ClientSession, cap_type: str,
                                     list_method_name: str,
                                     mcp_cls: Union[Type[mcp_types.Tool],
                                                    Type[mcp_types.Resource],
                                                    Type[mcp_types.Prompt]],
                                     agg_list: List[Any]):
        """
        通用辅助函数，用于发现和注册特定类型的 MCP 能力。
        如果发生名称冲突（不同服务器提供了同名能力），新的能力将被忽略并记录警告。
        TODO: 考虑使冲突解决策略可配置 (例如, 自动加前缀)。
        """
        logger.debug(f"[{svr_name}] 开始发现 {cap_type}...")
        try:
            list_method = getattr(session, list_method_name)
            logger.debug(
                f"[{svr_name}] 请求 {cap_type} 列表 (超时 {CAP_FETCH_TIMEOUT}s)...")

            list_result = await asyncio.wait_for(list_method(),
                                                 timeout=CAP_FETCH_TIMEOUT)

            orig_caps: List[Any] = []

            if hasattr(list_result, cap_type) and isinstance(
                    getattr(list_result, cap_type), list):
                orig_caps = getattr(list_result, cap_type)
            elif isinstance(list_result, list):
                orig_caps = list_result
            elif list_result is None:
                logger.info(
                    f"[{svr_name}] {list_method_name}() 返回了 None，视为没有 {cap_type}。"
                )
                orig_caps = []
            else:
                logger.warning(
                    f"[{svr_name}] {list_method_name}() 返回了未知类型: {type(list_result)}，无法解析 {cap_type} 列表。原始值: {list_result!r}"
                )
                orig_caps = []

            logger.debug(
                f"[{svr_name}] 从返回结果中解析到 {len(orig_caps)} 个原始 {cap_type}。")

            registered_count = 0
            for cap_item_raw in orig_caps:

                if not isinstance(cap_item_raw, mcp_cls):
                    logger.warning(
                        f"[{svr_name}] 发现了一个非 {mcp_cls.__name__} 类型的对象，已跳过: {cap_item_raw!r}"
                    )
                    continue

                cap_item = cast(
                    Union[mcp_types.Tool, mcp_types.Resource,
                          mcp_types.Prompt], cap_item_raw)

                if not cap_item.name:
                    logger.warning(
                        f"[{svr_name}] 发现了一个没有名称的 {cap_type[:-1]}，已跳过: {cap_item!r}"
                    )
                    continue

                exp_cap_name = cap_item.name

                if exp_cap_name in self._route_map:
                    exist_svr_name, _ = self._route_map[exp_cap_name]
                    if exist_svr_name != svr_name:
                        logger.warning(
                            f"冲突: {cap_type[:-1]} '{exp_cap_name}' 已由服务器 '{exist_svr_name}' 注册。"
                            f"来自服务器 '{svr_name}' 的同名 {cap_type[:-1]} 将被忽略。")

                        continue
                    else:
                        logger.warning(
                            f"[{svr_name}] 多次提供了同名的 {cap_type[:-1]}: '{exp_cap_name}'。仅注册第一个实例。"
                        )
                        continue

                agg_list.append(cap_item)
                self._route_map[exp_cap_name] = (svr_name, cap_item.name)
                registered_count += 1

            if registered_count > 0:
                logger.info(
                    f"[{svr_name}] 成功注册 {registered_count} 个唯一的 {cap_type}。")
            else:
                logger.info(f"[{svr_name}] 未发现或注册任何新的 {cap_type}。")

        except asyncio.TimeoutError:
            logger.error(
                f"[{svr_name}] 调用 {list_method_name}() 超时 (超过 {CAP_FETCH_TIMEOUT}s)。"
            )
        except mcp_types.Error as mcp_e:
            logger.error(
                f"[{svr_name}] 调用 {list_method_name}() 时发生 MCP 错误: Type={mcp_e.type}, Msg='{mcp_e.message}'",
                exc_info=False)
        except Exception:
            logger.exception(f"[{svr_name}] 发现 {cap_type} 时发生未知错误。")

    async def discover_and_register(self, sessions: Dict[str, ClientSession]):
        """从所有活动的后端会话中发现并注册 MCP 能力。"""
        logger.info(f"开始从 {len(sessions)} 个活动会话中发现并注册能力...")

        self._tools.clear()
        self._resources.clear()
        self._prompts.clear()
        self._route_map.clear()

        discover_tasks = []
        for svr_name, session in sessions.items():
            if not session:
                logger.warning(f"跳过服务器 '{svr_name}'，因为它没有提供有效的会话。")
                continue

            discover_tasks.append(
                self._discover_caps_by_type(svr_name, session, "tools",
                                            "list_tools", mcp_types.Tool,
                                            self._tools))
            discover_tasks.append(
                self._discover_caps_by_type(svr_name, session, "resources",
                                            "list_resources",
                                            mcp_types.Resource,
                                            self._resources))
            discover_tasks.append(
                self._discover_caps_by_type(svr_name, session, "prompts",
                                            "list_prompts", mcp_types.Prompt,
                                            self._prompts))

        await asyncio.gather(*discover_tasks, return_exceptions=True)

        logger.info("所有后端服务器的能力发现尝试已完成。")
        logger.info(f"聚合发现: {len(self._tools)} 个工具, "
                    f"{len(self._resources)} 个资源, "
                    f"{len(self._prompts)} 个提示。")
        logger.debug(f"当前路由表: {self._route_map}")

    def get_aggregated_tools(self) -> List[mcp_types.Tool]:
        """获取所有聚合后的工具列表。"""
        return self._tools

    def get_aggregated_resources(self) -> List[mcp_types.Resource]:
        """获取所有聚合后的资源列表。"""
        return self._resources

    def get_aggregated_prompts(self) -> List[mcp_types.Prompt]:
        """获取所有聚合后的提示列表。"""
        return self._prompts

    def resolve_capability(self,
                           exp_cap_name: str) -> Optional[Tuple[str, str]]:
        """
        根据暴露给客户端的能力名称，解析出原始后端服务器名称和在该服务器上的原始能力名称。
        返回: (后端服务器名, 原始能力名) 或 None (如果未找到)。
        """
        return self._route_map.get(exp_cap_name)

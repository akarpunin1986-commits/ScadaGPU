"""САНЁК v4 — Tool registry and tool implementations."""
from services.sanek_v4.tools.registry import ToolRegistry

# Global registry instance
registry = ToolRegistry()

# Import tool modules to register them (Phase 1)
import services.sanek_v4.tools.data           # noqa: F401
import services.sanek_v4.tools.scada          # noqa: F401
import services.sanek_v4.tools.knowledge      # noqa: F401

# Phase 2+3 tools
import services.sanek_v4.tools.bitrix         # noqa: F401
import services.sanek_v4.tools.modbus_tools   # noqa: F401
import services.sanek_v4.tools.code_executor  # noqa: F401
import services.sanek_v4.tools.schema         # noqa: F401

# Self-learning tools
import services.sanek_v4.tools.learning_tools # noqa: F401

# Company structure
import services.sanek_v4.tools.company       # noqa: F401

# Task Manager tools
import services.sanek_v4.tools.task_tools  # noqa: F401


async def execute_tool(name: str, args: dict) -> dict:
    """Execute a registered tool by name."""
    return await registry.execute(name, args)


def get_tool_definitions() -> list[dict]:
    """Get all tool definitions in Anthropic format."""
    return registry.get_definitions()

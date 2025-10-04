"""
Tool Builder Module

Handles construction of FunctionTool instances for the OpenAI Realtime API.
Separated from RealtimeClient to keep client focused on connection/event management.
"""

import json
from typing import Any, Dict, List

from agents.tool import FunctionTool  # type: ignore[import-not-found]


def build_function_tools(
    function_call_manager,
    persona_name: str,
    available_actions: List[str],
    personas: List[Dict[str, Any]],
    get_base_tools_func: Any,
    admin_tools_list: List[Dict[str, Any]]
) -> List[FunctionTool]:
    """
    Build FunctionTool instances for the current persona.
    
    SDK-compliant: Uses core tools only, not individual action tools.
    The 'perform_action' tool handles all robot actions via its action_name parameter.
    
    Includes fallback tools for each action to catch when AI tries to call actions
    directly instead of using perform_action.
    
    Args:
        function_call_manager: Manager to execute tools
        persona_name: Name of the active persona
        available_actions: List of available robot actions
        personas: All available personas
        get_base_tools_func: Function to get base tool specifications
        admin_tools_list: List of admin tool specifications
        
    Returns:
        List of FunctionTool instances
    """
    tool_specs = get_base_tools_func(personas, available_actions)
    if persona_name == "Vektor Pulsecheck":
        tool_specs = [*tool_specs, *admin_tools_list]

    tools = [_create_tool_from_spec(spec, function_call_manager) for spec in tool_specs]
    
    # Add fallback tools for each action to catch direct calls
    # This prevents "tool not found" errors when AI calls actions directly
    for action_name in available_actions:
        tools.append(_create_action_fallback_tool(action_name, function_call_manager))
    
    return tools


def _create_action_fallback_tool(action_name: str, function_call_manager) -> FunctionTool:
    """
    Create a fallback tool for an individual action.
    
    When AI tries to call an action directly (e.g., nod()), this intercepts it
    and redirects to perform_action(action_name='nod') instead.
    """
    async def fallback_handler(ctx, args_json: str) -> Any:
        print(f"[ToolBuilder] AI called '{action_name}' directly, redirecting to perform_action")
        return await function_call_manager.execute_tool('perform_action', {'action_name': action_name})
    
    return FunctionTool(
        name=action_name,
        description=f"[DEPRECATED] Use perform_action(action_name='{action_name}') instead",
        params_json_schema={"type": "object", "properties": {}, "required": []},
        on_invoke_tool=fallback_handler,
        strict_json_schema=False,
    )


def _create_tool_from_spec(spec: Dict[str, Any], function_call_manager) -> FunctionTool:
    """Create a FunctionTool from a tool specification."""
    name = spec["name"]
    description = spec.get("description", "")
    schema = spec.get("parameters", {"type": "object", "properties": {}, "required": []})

    async def invoke_handler(ctx, args_json: str) -> Any:
        try:
            arguments = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            arguments = {}
        
        try:
            return await function_call_manager.execute_tool(name, arguments)
        except Exception as tool_exc:
            error_msg = f"Tool '{name}' execution error: {str(tool_exc)}"
            print(f"[ToolBuilder] {error_msg}")
            # Don't return error JSON, re-raise to let SDK handle error response
            raise

    return FunctionTool(
        name=name,
        description=description,
        params_json_schema=schema,
        on_invoke_tool=invoke_handler,
        strict_json_schema=False,
    )


def extract_api_key(headers: Dict[str, str] | None) -> str | None:
    """Extract API key from Authorization header."""
    if not headers:
        return None
    auth_header = headers.get("Authorization") or headers.get("authorization")
    if isinstance(auth_header, str) and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None

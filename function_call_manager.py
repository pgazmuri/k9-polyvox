import json
import os
import sys
import signal
from typing import Any, Dict, Optional

class FunctionCallManager:
    """
    Interprets function call messages from the GPT model and routes them
    to the correct local Python functions in ActionManager.
    """

    def __init__(self, action_manager, client):
        """
        :param action_manager: an instance of ActionManager
        :param reconnect_callback: function to force a new connection (and optionally switch persona)
        """
        self.action_manager = action_manager
        self.client = client

    async def handle_function_call(self, function_call):
        """
        Parses the function call message, executes the correct action, 
        and returns a string result to be sent back to the GPT model.
        """
        print(f"[FunctionCallManager] Handling function call: {function_call}")
        try:
            func_name = function_call['name']
            raw_arguments = function_call.get('arguments')
            arguments: Dict[str, Any]
            if isinstance(raw_arguments, str) and raw_arguments:
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    arguments = {}
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            else:
                arguments = {}

            return await self.execute_tool(func_name, arguments)
        except Exception as e:
            import traceback
            error_message = f"[FunctionCallManager] Error: {e}"
            stack_trace = traceback.format_exc()
            
            print(error_message)
            print(stack_trace)
            return f"{error_message}\n{stack_trace}"

    async def execute_tool(self, func_name: str, arguments: Optional[Dict[str, Any]] = None):
        arguments = arguments or {}

        if func_name == 'look_and_see':
            question = arguments.get("question", "")
            print(f"[FunctionCallManager] Persona: {self.client.persona}")
            result = await self.action_manager.take_photo(persona=self.client.persona, question=question, client=self.client)
            print(f"[FunctionCallManager] look_and_see triggered image send: {result}")
            return result

        if func_name == 'get_system_status':
            return await self.get_system_status()

        if func_name == 'shut_down':
            print("[FunctionCallManager] Shutting down...")
            try:
                script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'main.py'))
                python_executable = sys.executable

                print(f"Sending SIGTERM to process {os.getpid()} to initiate shutdown.")
                os.kill(os.getpid(), signal.SIGTERM)
                return json.dumps({"status": "success", "message": "shutdown initiated"})
            except Exception as e:
                print(f"[FunctionCallManager] Error during pull/restart: {e}")
                return json.dumps({"status": "error", "message": str(e)})

        if func_name == 'pull_latest_code_and_restart':
            print("[FunctionCallManager] Attempting to pull latest code and restart...")
            try:
                script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'main.py'))
                python_executable = sys.executable

                print("Pulling latest code...")
                os.system("git pull")

                print(f"Scheduling restart: {python_executable} {script_path}")
                os.system(f'(sleep 8; "{python_executable}" "{script_path}")')

                print(f"Sending SIGTERM to process {os.getpid()} to initiate shutdown.")
                os.kill(os.getpid(), signal.SIGTERM)

                return json.dumps({"status": "success", "message": "Pull successful, shutdown initiated, restart scheduled."})
            except Exception as e:
                print(f"[FunctionCallManager] Error during pull/restart: {e}")
                return json.dumps({"status": "error", "message": str(e)})

        if func_name == 'get_awareness_status':
            return await self.get_awareness_status()

        if func_name == 'set_volume':
            volume_level = arguments.get("volume_level", 1)
            return await self.set_volume(volume_level)

        if func_name == 'set_goal':
            self.action_manager.state.goal = arguments.get(
                "goal",
                "You are unsure of your goal. Ask a question or make a statement in keeping with your persona and the current state.",
            )
            self.client.persona["default_motivation"] = self.action_manager.state.goal
            print(f"[FunctionCallManager] Goal set to: {self.action_manager.state.goal}")
            return "success"

        if func_name == 'create_new_persona':
            persona_description = arguments.get("persona_description", None)
            return await self.create_new_persona(persona_description)

        if func_name == 'perform_action':
            action_name = arguments.get("action_name", "")
            return await self.perform_action(action_name)

        if func_name == 'switch_persona':
            persona_name = arguments.get("persona_name", "Vektor Pulsecheck")
            if self.client.persona['name'] == persona_name:
                return "You are already in this persona."
            print(f"[FunctionCallManager] Switching persona to: {persona_name}")
            await self.action_manager.handle_persona_switch_effects(persona_name, self.client)
            result = "persona_switched"
            print(f"[FunctionCallManager] Result of 'switch_persona': {result}")
            return result

        # Check if it might be an action that was called as a tool by mistake
        available_actions = self.action_manager.get_available_actions()
        if func_name in available_actions:
            print(f"[FunctionCallManager] '{func_name}' is not a tool, executing as action instead")
            return await self.perform_action(func_name)

        result = json.dumps({
            "status": "error",
            "message": f"Unknown function '{func_name}'. Use 'perform_action' with action_name parameter for robotic actions."
        })
        print(f"[FunctionCallManager] Unknown function call: {func_name}")
        return result

    async def shut_down(self):
        """
        Shuts down the robot dog for maintenance.
        """
        print("[FunctionCallManager] Shutting down...")
        os.kill(os.getpid(), signal.SIGTERM)

    async def get_system_status(self):
        """
        Retrieves sensor and system status, including body pitch, battery voltage, CPU utilization, last sound direction, and more.
        """
        result = self.action_manager.get_status()
        print(f"[FunctionCallManager] Result of 'get_system_status': {result}")
        return result

    async def get_awareness_status(self):
        """
        Retrieves text telling you what the robot dog just noticed.
        """
        print("[FunctionCallManager] Getting awareness status...")
        
        # Check if there's a pending stimulus to deliver
        if self.action_manager.state.pending_stimulus:
            stimulus = self.action_manager.state.pending_stimulus
            self.action_manager.state.pending_stimulus = None  # Clear it after reading
            print(f"[FunctionCallManager] Delivering pending stimulus: {stimulus}")
            return stimulus
        
        result = self.action_manager.state.goal
        print(f"[FunctionCallManager] Result of 'get_awareness_status': {result}")
        return result

    async def set_volume(self, volume_level):
        """
        Sets the speech volume.
        """
        self.action_manager.state.volume = volume_level
        print(f"[FunctionCallManager] Volume set to: {self.action_manager.state.volume}")
        return "success"

    async def set_goal(self, goal):
        """
        Sets a new goal or motivation for the robot dog.
        """
        self.action_manager.state.goal = goal
        print(f"[FunctionCallManager] Goal set to: {self.action_manager.state.goal}")
        return "success"

    async def create_new_persona(self, persona_description):
        """
        Generates and switches to a new persona based on the description provided.
        """
        print(f"[FunctionCallManager] Requesting ActionManager to create new persona: {persona_description}")
        result = await self.action_manager.create_new_persona_action(persona_description, self.client)
        return result

    async def perform_action(self, action_name):
        """
        Performs one or more robotic actions simultaneously.
        """
        if hasattr(self.client, "enqueue_action") and callable(self.client.enqueue_action):
            result = await self.client.enqueue_action(action_name, source="perform_action_tool")
            print(f"[FunctionCallManager] Result of 'perform_action': {result}")
            return result

        await self.action_manager.perform_action(action_name)
        print(f"[FunctionCallManager] Result of 'perform_action': success")
        return "success"

    async def switch_persona(self, persona_name):
        """
        Switches the robot's personality to a specified persona.
        """
        print(f"[FunctionCallManager] Switching persona to: {persona_name}")
        await self.action_manager.handle_persona_switch_effects(self.reconnect, persona_name)
        print(f"[FunctionCallManager] Result of 'switch_persona': persona_switched")
        return "persona_switched"

#  Define base tools available to all personas
def get_base_tools(personas, available_actions):
    return [
    {
        "type": "function",
        "name": "perform_action",
        "description": "Performs one or more robotic actions simultaneously (comma-separated). Essential for expressing the persona physically.",
        "parameters": {
            "type": "object",
            "properties": {
                "action_name": {
                    "type": "string",
                    "description": f"The name of the action(s) to perform. Available actions: {', '.join(available_actions)}"
                }
            },
            "required": ["action_name"]
        }
    },
    {
        "type": "function",
        "name": "get_system_status",
        "description": "Retrieves sensor and system status, including body pitch, battery voltage, cpu utilization, last sound direction and more.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "get_awareness_status",
        "description": "Retrieves text telling you what the robot dog just noticed.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "look_and_see",
        "description": "This is how you 'Look', 'See', or 'Take a picture'. Takes a picture in whatever direction the head position is in and retrieves text describing what you can see.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "A specific question about what the dog sees, if the user makes such a request."
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "switch_persona",
        "description": "Switches the robot's personality to one of the available personas listed in the instructions.",
        "parameters": {
            "type": "object",
            "properties": {
                "persona_name": {
                    "type": "string",
                    "description": f"The exact name of the persona to switch to. Options: {', '.join([p['name'] for p in personas])}"
                }
            },
            "required": ["persona_name"]
        }
    },
    {
        "type": "function",
        "name": "set_volume",
        "description": "Sets the speech volume.",
        "parameters": {
            "type": "object",
            "properties": {
                "volume_level": {
                    "type": "number",
                    "description": "The volume number. From 0.0 (sound off) to 3.0 (highest volume)."
                }
            },
            "required": ["volume_level"]
        }
    },
    {
        "type": "function",
        "name": "create_new_persona",
        "description": "Generates and switches to a new persona based on the description provided.",
        "parameters": {
            "type": "object",
            "properties": {
                "persona_description": {
                    "type": "string",
                    "description": "A description of the persona, including name and personality traits."
                }
            },
            "required": ["persona_description"]
        }
    },
    {
        "type": "function",
        "name": "set_goal",
        "description": "Sets a new goal or motivation that you will be reminded to pursue.",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The new goal you will be reminded to pursue on occasion."
                }
            },
            "required": ["goal"]
        }
    }
]

admin_tools = [{
                "type": "function",
                "name": "pull_latest_code_and_restart",
                "description": "Pulls the latest code from Git and restarts the robot's process. DO NOT CALL UNLESS EXPLICITLY REQUESTED, AND ALWAYS CONFIRM USER INTENT BEFORE PERFORMING",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
                },
                {
                "type": "function",
                "name": "shut_down",
                "description": "Shuts down your main process. DO NOT CALL UNLESS EXPLICITLY REQUESTED, AND ALWAYS CONFIRM USER INTENT BEFORE PERFORMING",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }]

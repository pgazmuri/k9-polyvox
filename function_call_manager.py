import json
import sys # For quitting the program
from persona_generator import generate_persona

class FunctionCallManager:
    """
    Interprets function call messages from the GPT model and routes them
    to the correct local Python functions in ActionManager.
    """

    def __init__(self, action_manager, reconnect_callback, client):
        """
        :param action_manager: an instance of ActionManager
        :param reconnect_callback: function to force a new connection (and optionally switch persona)
        """
        self.action_manager = action_manager
        self.reconnect = reconnect_callback
        self.client = client

    async def handle_function_call(self, function_call):
        """
        Parses the function call message, executes the correct action, 
        and returns a string result to be sent back to the GPT model.
        """
        try:
            func_name = function_call['name']
            arguments = json.loads(function_call['arguments'])

            if func_name == 'look_and_see':
                question = arguments.get("question", "")
                # You could pass a persona prompt if you want
                result = await self.action_manager.take_photo("", question=question)
                print(f"[FunctionCallManager] Result of 'look_and_see': {result}")
                return result

            elif func_name == 'get_system_status':
                result = self.action_manager.get_status()
                print(f"[FunctionCallManager] Result of 'get_system_status': {result}")
                return result

            elif func_name == 'shut_down':
                print("[FunctionCallManager] Shutting down...")
                sys.exit()
                sys.exit()
                sys.exit()

            elif func_name == 'get_awareness_status':
                return self.action_manager.state.goal

            elif func_name == 'set_volume':
                self.action_manager.state.volume = arguments.get("volume_level", 1)
                print(f"[FunctionCallManager] Volume set to: {self.action_manager.state.volume}")
                result = "success"
                return result
            
            elif func_name == 'set_goal':
                self.action_manager.state.goal = arguments.get("goal", "You are unsure of your goal. Ask what you should do next, or not.")
                print(f"[FunctionCallManager] Goal set to: {self.action_manager.state.goal}")
                result = "success"
                return result
            
            elif func_name == 'create_new_persona':
                persona_description = arguments.get("persona_description", None)
                new_persona = await generate_persona(persona_description)
                await self.client.reconnect(new_persona['name'], new_persona)
                print(f"[FunctionCallManager] Creating new persona: {persona_description}")
                result = "success"
                return result

            elif func_name == 'perform_action':
                action_name = arguments.get("action_name", "")
                await self.action_manager.perform_action(action_name)
                result = "success"
                print(f"[FunctionCallManager] Result of 'perform_action': {result}")
                return result

            elif func_name == 'switch_persona':
                persona_name = arguments.get("persona_name", "Vektor Pulsecheck")
                print(f"[FunctionCallManager] Switching persona to: {persona_name}")
                # Force a reconnect with a new persona
                await self.reconnect(persona_name)
                result = "persona_switched"
                print(f"[FunctionCallManager] Result of 'switch_persona': {result}")
                return result

            else:
                result = f"[FunctionCallManager] Unknown function call: {func_name}"
                print(result)
                return result
        except Exception as e:
            import traceback
            error_message = f"[FunctionCallManager] Error: {e}"
            stack_trace = traceback.format_exc()
            
            print(error_message)
            print(stack_trace)
            return f"{error_message}\n{stack_trace}"

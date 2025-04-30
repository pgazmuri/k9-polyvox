import json
import os
import sys # For quitting the program

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
        try:
            func_name = function_call['name']

            if func_name == 'look_and_see':
                arguments = json.loads(function_call['arguments'])
                question = arguments.get("question", "")
                # You could pass a persona prompt if you want
                result = await self.action_manager.take_photo("", question=question)
                print(f"[FunctionCallManager] Result of 'look_and_see': {result}")
                return result

            elif func_name == 'get_system_status':
                result = self.action_manager.get_status()
                print(f"[FunctionCallManager] Result of 'get_system_status': {result}")
                return result

            elif func_name == 'pull_latest_code_and_restart':
                print("[FunctionCallManager] Shutting down...")
                # pull latest from git, schedule my own restart, and kill my own process with sudo kill -9 $PID
                try:
                    self.action_manager.perform_action("lie")
                    # Pull the latest changes from Git
                    os.system("git pull")

                    # Schedule a restart of the current process after 3 seconds
                    python_executable = sys.executable
                    script_path = sys.argv[0]
                    os.system(f"(sleep 3; {python_executable} {script_path}) &")

                    # Kill the current process
                    os.kill(os.getpid(), 9)
                except Exception as e:
                    print(f"[FunctionCallManager] Error during shutdown: {e}")



            elif func_name == 'get_awareness_status':
                print("[FunctionCallManager] Getting awareness status...")
                result = self.action_manager.state.goal
                print(f"[FunctionCallManager] Result of 'get_awareness_status': {result}")
                return result

            elif func_name == 'set_volume':
                arguments = json.loads(function_call['arguments'])
                self.action_manager.state.volume = arguments.get("volume_level", 1)
                print(f"[FunctionCallManager] Volume set to: {self.action_manager.state.volume}")
                result = "success"
                return result
            
            elif func_name == 'set_goal':
                arguments = json.loads(function_call['arguments'])
                self.action_manager.state.goal = arguments.get("goal", "You are unsure of your goal. Ask a question or make a statement in keeping with your persona and the current state.")
                print(f"[FunctionCallManager] Goal set to: {self.action_manager.state.goal}")
                result = "success"
                return result
            
            elif func_name == 'create_new_persona':
                arguments = json.loads(function_call['arguments'])
                persona_description = arguments.get("persona_description", None)
                print(f"[FunctionCallManager] Requesting ActionManager to create new persona: {persona_description}")
                result = await self.action_manager.create_new_persona_action(persona_description, self.client)
                return result

            elif func_name == 'perform_action':
                arguments = json.loads(function_call['arguments'])
                action_name = arguments.get("action_name", "")
                await self.action_manager.perform_action(action_name)
                result = "success"
                print(f"[FunctionCallManager] Result of 'perform_action': {result}")
                return result

            elif func_name == 'switch_persona':
                arguments = json.loads(function_call['arguments'])
                persona_name = arguments.get("persona_name", "Vektor Pulsecheck")
                if self.client.persona['name'] == persona_name:
                    return "You are already in this persona."
                print(f"[FunctionCallManager] Switching persona to: {persona_name}")
                # Call the new method in ActionManager to handle effects and reconnect
                await self.action_manager.handle_persona_switch_effects(persona_name, self.client)
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

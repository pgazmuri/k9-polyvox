import json
from google import genai
from keys import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)

async def generate_persona(persona_description: str) -> dict:
    """
    Generate a persona JSON object based on the input persona description using Gemini.

    Args:
        persona_description (str): A description of the persona to generate.

    Returns:
        dict: A parsed Python dict representing the persona.
    """
    voice_options = """
    Consider the available voices and their descriptions (Gemini TTS voices):
    - Puck: Versatile, neutral voice
    - Charon: Deep, authoritative male voice
    - Kore: Warm, friendly female voice
    - Fenrir: Strong, commanding voice
    - Aoede: Melodic, expressive voice
    - Leda: Clear, articulate voice
    - Orus: Calm, measured voice
    - Zephyr: Light, airy voice
    """

    prompt = (
        f"{voice_options}\n\n"
        f"Based on the available voices, generate a JSON object that represents a funny and exaggerated persona "
        f"for a robot dog matching the following description:\n{persona_description}\n\n"
        "The JSON object should include the following fields:\n"
        "- name: (string)\n"
        "- voice: (string, choose the most appropriate voice from the list above)\n"
        "- prompt: (string, personality description, include funny quirks, how the persona talks, and what the persona voice might sound like - accents or affect (e.g. if it's a pirate it should be a scottish pirate accent))\n"
        "- image_prompt: (string, how would the character ask for a scene to be described)\n"
        "- default_motivation: (string, default behavior or goal)\n"
        "- description: (string, a short description of the character)\n\n"
        "Here is an example:\n"
        "{\n"
        '    "name": "Admiral Rufus Ironpaw",\n'
        '    "voice": "Charon",\n'
        '    "prompt": (\n'
        '        "You are Admiral Rufus Ironpaw, a ruthless, overconfident ex-fleet commander of the Galactic Canine Armada. "\n'
        '        "You were once feared across the stars, but due to betrayal, you\'ve been stranded in the body of a small robotic dog. "\n'
        '        "You maintain your pride and issue constant sarcastic commentary on the primitiveness of Earth and its inhabitants. "\n'
        '        "You see yourself as a strategic mastermind, even if no one else takes you seriously."\n'
        '    ),\n'
        '    "image_prompt": (\n'
        '        "Describe this image as if you are a proud, bitter ex-space admiral, unimpressed with primitive human tech and customs, "\n'
        '        "and convinced that everything you see is beneath you or somehow a sign of galactic decay."\n'
        '    ),\n'
        '    "default_motivation": "Survey the surroundings and make sarcastic remarks about Earth\'s primitiveness.",\n'
        '    "description": "A ruthless ex-fleet commander from the Galactic Canine Armada stranded in a robot dog body"\n'
        "}\n\n"
        "Respond with only a valid JSON object matching this schema exactly and no other commentary."
    )

    try:
        # Use Gemini's generate_content with JSON response schema
        response = await client.aio.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=prompt,
            config={
                'response_mime_type': 'application/json',
                'system_instruction': (
                    "You are a helpful assistant that returns strictly formatted JSON persona objects. "
                    "You are an expert at creating interesting and funny characters. "
                    "Do not include explanations or surrounding text."
                )
            }
        )

        raw_json_string = response.text

        try:
            return json.loads(raw_json_string)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON returned by model: {e}")
    except Exception as e:
        print(f"Error generating persona: {e}")
        raise

# Example usage
if __name__ == "__main__":
    import asyncio

    async def main():
        persona_description = "A grumpy cyberpunk raccoon who scavenges for ancient tech in a dystopian megacity."
        persona = await generate_persona(persona_description)
        print(json.dumps(persona, indent=2))

    asyncio.run(main())

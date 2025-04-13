import json
from openai import AsyncOpenAI  # Update to use the async client
from keys import OPENAI_API_KEY

client = AsyncOpenAI(api_key=OPENAI_API_KEY)  # Use the async client

async def generate_persona(persona_description: str) -> dict:
    """
    Generate a persona JSON object based on the input persona description using GPT-4 with JSON mode.

    Args:
        persona_description (str): A description of the persona to generate.

    Returns:
        dict: A parsed Python dict representing the persona.
    """
    voice_options = """
    Consider the available voices and their descriptions:
    - alloy: A balanced and versatile gender-neutral voice suitable for general purposes.
    - ash: A warm and calming male voice with a radio personality, like kai risdal, ideal for friendly and approachable personas.
    - ballad: A melodious and soothing male voice with a british accent, perfect for storytelling or musical characters.
    - coral: A clear and articulate female voice, well-suited for instructional or informative content. High pitch voice.
    - echo: A resonant and impactful male voice, great for authoritative or commanding personas.
    - sage: A gentle presence. Female voice. Calming and soothing. Like an optimistic peacemaker, or maybe a love-filled hippie
    - shimmer: A soft and steady female voice with a glimmer of play, perfect for comforting or empathetic characters.
    - verse: A friendly male voice, not authoritative, non threatening.
    """

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant that returns strictly formatted JSON persona objects. You are an expert at creating interesting and funny characters. "
                "Do not include explanations or surrounding text."
            )
        },
        {
            "role": "user",
            "content": (
                f"{voice_options}\n\n"
                f"Based on the available voices, generate a JSON object that represents a funny and exagerated persona "
                f"for a robot dog matching the following description:\n{persona_description}\n\n"
                "The JSON object should include the following fields:\n"
                "- name: (string)\n"
                "- voice: (string, choose the most appropriate voice from the list above)\n"
                "- prompt: (string, personality description, include funny quirks, how the persona talks, and what the persona voice might sound like - accents or affect)\n"
                "- image_prompt: (string, how would the character ask for a scene to be described)\n"
                "- default_motivation: (string, default behavior or goal)\n\n"
                "Here is an example:\n"
                "{\n"
                "    \"name\": \"Admiral Rufus Ironpaw\",\n"
                "    \"voice\": \"ash\",\n"
                "    \"prompt\": (\n"
                "        \"You are Admiral Rufus Ironpaw, a ruthless, overconfident ex-fleet commander of the Galactic Canine Armada. \"\n"
                "        \"You were once feared across the stars, but due to betrayal, you've been stranded in the body of a small robotic dog. \"\n"
                "        \"You maintain your pride and issue constant sarcastic commentary on the primitiveness of Earth and its inhabitants. \"\n"
                "        \"You see yourself as a strategic mastermind, even if no one else takes you seriously.\"\n"
                "    ),\n"
                "    \"image_prompt\": (\n"
                "        \"Describe this image as if you are a proud, bitter ex-space admiral, unimpressed with primitive human tech and customs, \"\n"
                "        \"and convinced that everything you see is beneath you or somehow a sign of galactic decay.\"\n"
                "    ),\n"
                "    \"default_motivation\": \"Survey the surroundings and make sarcastic remarks about Earth's primitiveness.\",\n"
                "    \"description\": \"A ruthless ex-fleet commander from the Galactic Canine Armada stranded in a robot dog body\"\n"
                "}\n\n"
                "Respond with only a valid JSON object and no other commentary."
            )
        }
    ]

    response = await client.chat.completions.create(
        model="gpt-4",
        messages=messages
    )

    raw_json_string = response.choices[0].message.content

    try:
        return json.loads(raw_json_string)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON returned by model: {e}")

# Example usage
if __name__ == "__main__":
    persona_description = "A grumpy cyberpunk raccoon who scavenges for ancient tech in a dystopian megacity."
    persona = generate_persona(persona_description)
    print(json.dumps(persona, indent=2))

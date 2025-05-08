# Using Your k9-polyvox Robot Dog

This guide explains how to interact with your k9-polyvox robot dog, including voice commands, changing personas, and understanding the dog's behaviors.

## Getting Started

After setting up the hardware and software as described in the [README.md](README.md), you'll need to start the robot dog software:

```sh
python main.py
```

If installed as a service, it will start automatically on boot. The dog will initialize with a power-up sequence (red → orange → yellow → white light transitions) and sit in its default position.

## Basic Interaction

### Speaking to Your Dog

The k9-polyvox robot dog uses OpenAI's GPT-4o model with real-time audio processing via the Realtime API. To interact with your dog:

1. **Start speaking**: The dog will listen for your voice and respond accordingly
2. **Default wake word**: The dog is always listening, no specific wake word is required

The dog will bob its head slightly while speaking to simulate conversation. The RGB lightbar will show multicolor activity corresponding to outgoing audio when it's responding, and pink when it's in idle "breath" mode.

### Physical Interaction

Your robot dog responds to touch through its dual touch sensors:

- **Petting the head**: The dog will wag its tail when you touch its head

### Using the Camera

The dog can "see" using its camera. Ask it to look at something by saying phrases like:

- "What do you see?"
- "Take a picture"
- "Look at this"
- "Can you see me?"
- "Describe what's in front of you"

The robot will use its `look_and_see` function (flashing a blue light momentarily) and then describe what it sees according to its current persona's perspective.

## Working with Personas

### Default Persona

The default persona is "Vektor Pulsecheck," a no-nonsense diagnostic assistant that provides direct, factual responses.

### Available Personas

The following personas are built into k9-polyvox:

1. **Admiral Rufus Ironpaw**: A ruthless, overconfident ex-fleet commander with sarcastic commentary about Earth's "primitiveness"
2. **Lord Archibald Snarlington III**: A snobbish, disgraced former aristocrat with haughty disdain
3. **Professor Maximillian von Wagginton**: A pseudo-intellectual "genius" making ridiculous claims with great confidence
4. **Master Kuro**: A calm, philosophical sage speaking in poetic sentences and riddles
5. **Coach Chip Thunderbark**: A hyper-enthusiastic fitness coach full of motivational pep talks
6. **Malvolio Dreadpaw**: A dramatic, theatrical robotic dog with a cold, sinister tone
7. **Brian**: A sarcastic character with humor similar to Brian from Family Guy
8. **David AttenBowWow**: A soft-spoken naturalist who narrates like a BBC wildlife documentary
9. **Dog Quixote**: A chivalrous, delusional knight who speaks in archaic language and sees quests everywhere
10. **Vektor Pulsecheck**: The default persona - direct, factual, diagnostic assistant
11. **Ember**: A gentle, emotionally intelligent support robot for comforting children
12. **REX-4**: A decommissioned combat drone with war memories and military protocol

### Switching Personas

To switch personas, simply ask the dog to change by saying something like:

- "Can you switch to Admiral Rufus Ironpaw?"
- "I'd like to talk to Master Kuro now"
- "Change persona to Coach Chip"
- "Become Brian please"

When switching, the dog will play a short sound effect and flash green lights to indicate the transition.

### Creating Custom Personas

You can create entirely new personas on-the-fly by saying:

- "Create a new persona that's [your description]"
- "Can you become a [your character idea]?"
- "I'd like a new personality that's [your description]"

For example: "Create a new persona that's a grumpy cyberpunk raccoon who scavenges for ancient tech in a dystopian megacity."

The dog will use OpenAI to generate a complete new persona including name, voice, personality, and image description style. During this creation process, the dog will play a longer audio effect and flash white lights.

## Available Actions

The dog can perform many physical actions, which it will use automatically to express its persona. However, you can also request specific actions:

### Movement Actions
- **Walking**: "Walk forward", "Walk backward"
- **Turning**: "Turn left", "Turn right"
- **Posture**: "Sit", "Stand", "Lie down"

### Head Actions
- **Looking**: "Look forward", "Look up", "Look down", "Look left", "Look right"
- **Complex moves**: "Look up-left", "Look up-right", "Look down-left", "Look down-right"
- **Head gestures**: "Nod", "Shake head", "Tilt head left", "Tilt head right"
- **Expressive moves**: "Think" (thoughtful head tilt), "Recall" (searching memory pose)

### Emotional Actions
- **Happy**: "Wag tail", "Pant"
- **Excited**: "Bark", "Bark harder", "Howling"
- **Playful**: "Stretch", "Push up"
- **Friendly**: "Handshake", "High five", "Lick hand"
- **Moods**: "Fluster", "Surprise", "Alert", "Attack posture"
- **Other**: "Body twisting", "Feet shake", "Relax neck"

Most actions are automatically chosen by the dog based on its persona and the context of your conversation, so you'll see a range of behaviors even without specifically requesting them.

## Sensor Information

Your dog has several sensors and is aware of:

1. **Touch detection**: Knows when and how it's being petted
2. **Sound direction**: Can tell which direction sounds come from (front, back, left, right, etc.)
3. **Face detection**: Can detect when people are in front of it
4. **Orientation**: Knows if it's upright, on its side, or upside down
5. **Battery level**: Monitors its battery voltage (nominal is 7.6V)

To get status information, simply ask:
- "How's your battery?"
- "What's your status?"
- "System report please"
- "Tell me your diagnostics"

## Tips for Best Experience

1. **Speak naturally**: The dog understands natural language and contextual conversation
2. **Ask about what it sees**: The vision function gives the dog awareness of its surroundings
3. **Try different personas**: Each has a unique personality and way of interpreting the world
4. **Pet the dog**: Physical interaction triggers responses and behaviors
5. **Position yourself in front**: The camera and sound detection work best when you're in front of the dog
6. **Create custom personas**: This is one of the most fun features - create exactly the character you want

## Common Issues

- If the dog seems unresponsive, check if the lightbar display is active/moving. If it's not, the app or OS probably crashed.
- If audio quality is poor, refer to the audio setup section in README.md for configuration options
- If the dog doesn't respond to touch, ensure the touch sensors are properly connected
- If camera functions don't work, make sure the camera module is properly seated

## Shutting Down

To properly shut down the dog:

Ask "Vektor Pulsecheck" to shut down.  He is the only personality which has access to do this.

Otherwise:

- If running in terminal: Press Ctrl+C to stop the program
- If running as a service: `systemctl --user stop k9_polyvox`

The dog will automatically move to a safe lying position when shut down properly.

Enjoy your conversations with your new robotic companion!
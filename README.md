# PiDog PolyVox

PiDog PolyVox is an advanced, persona-driven robot dog project for the [SunFounder PiDog](https://www.sunfounder.com/products/pidog) platform. It features real-time speech, persona switching, robotic actions, and integration with OpenAI's GPT models. The project is designed for Raspberry Pi and leverages the official PiDog hardware and software stack.

## Features

- Real-time conversation and audio streaming with OpenAI GPT models
- Multiple, switchable robot dog personas with unique behaviors and voices
- Physical actions: head/leg/tail movement, lightbar effects, and sound playback
- Sensor integration: touch, sound direction, face detection, and more
- OLED display support (optional)
- Modular action and audio management

## Hardware Requirements

- [SunFounder PiDog](https://www.sunfounder.com/products/pidog) kit (with all servos, sensors, and lightbar)
- Raspberry Pi 4 (recommended) with Raspberry Pi OS
- (Optional) SSD1306 128x64 OLED display (I2C, for status/messages)

## Software Setup

### 1. Install PiDog Software (SunFounder Official)

Follow the official [SunFounder PiDog software setup guide](https://docs.sunfounder.com/projects/pidog/en/latest/software/installation.html):

```sh
# Clone the official PiDog repository
git clone https://github.com/sunfounder/pidog.git
cd pidog
sudo pip3 install .
```

Make sure you can run the PiDog demo scripts and that your hardware is working.

### 2. Clone This Repository

```sh
git clone https://github.com/pgazmuri/k9-polyvox
cd k9-polyvox
```

### 3. Install Python Dependencies

It's recommended to use Python 3.7+.

```sh
sudo pip install -r requirements.txt --break-system-packages
```

### 4. Configure API Keys

Create a `keys.py` file in the project root with your OpenAI API key:

```python
OPENAI_API_KEY = "sk-..."
```

### 5. (Optional) Disable Audio or Display

- **Disable PiDog Speaker:** If you don't have the PiDog speaker or want to skip audio output, set the following environment variable:
  ```sh
  export DISABLE_PIDOG_SPEAKER=1
  ```
- **Disable OLED Display:** If you don't have the SSD1306 OLED display, set:
  ```sh
  export DISABLE_PIDOG_DISPLAY=1
  ```
  This will skip display initialization and speed up startup.
- **Use Mock Actions:** For development or testing without a physical PiDog, you can use mock actions:
  ```sh
  export USE_MOCK_ACTIONS=1
  ```
  This replaces real robot actions with mock implementations, allowing you to test the software without actual hardware movement.

You can add these to your `.bashrc` or set them inline when running:

```sh
DISABLE_PIDOG_DISPLAY=1 python main.py
```

## Running the Project

Start the main program:

```sh
python main.py
```

The robot will boot, connect to OpenAI, and begin interacting. Use Ctrl+C to stop.

## Troubleshooting

- If you see errors related to the display or speaker, ensure the correct environment variables are set.
- Make sure your PiDog hardware is powered and connected.
- The app will use your default audio source and sink.  You can use pactl to view and set devices.

## License

See [LICENSE](LICENSE) for details.

---

For more information, see the [SunFounder PiDog documentation](https://docs.sunfounder.com/projects/pidog/en/latest/) and the comments in each source file.
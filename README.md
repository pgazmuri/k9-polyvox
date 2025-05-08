# k9-polyvox

k9-polyvox is a persona-driven robot dog project for the [SunFounder PiDog](https://www.sunfounder.com/products/pidog) platform. It features real-time speech, persona switching, robotic actions, and integration with OpenAI's GPT models for vision interpretation and persona creation. The project is designed for Raspberry Pi and leverages the official PiDog hardware and software stack.

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
- (Optional/Experimental) SSD1306 128x64 OLED display (I2C, for status/messages)

## Software Setup

### 1. Install PiDog Software (SunFounder Official)

Follow the official [SunFounder PiDog software setup guide](https://pidog.rtfd.io/):

Be sure to perform the steps to [Install All the Modules](https://docs.sunfounder.com/projects/pidog/en/latest/python/python_start/install_all_modules.html);

Make sure you can run the PiDog demo scripts and that your hardware is working.

### 2. Clone This Repository

```sh
cd ~/
git clone https://github.com/pgazmuri/k9-polyvox
cd k9-polyvox
```

### 3. Install Python Dependencies

It's recommended to use Python 3+

```sh
sudo pip install -r requirements.txt --break-system-packages
```

### 4. Configure API Keys

Edit the `keys.py` file in the project root with your OpenAI API key:

```python
OPENAI_API_KEY = "sk-..."
```

### 5. (Optional) Disable Audio or Display

- **Disable PiDog Speaker:** If your PiDog speaker is broken or you want to use a bluetooth speaker instead (recommended), set the following environment variable:
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
  This replaces real robot actions with mock implementations, allowing you to test the software without servo movement. This is useful when you want the dog to stay still, but also extends the lifetime of servos and reduces battery usage during development/testing.

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

## Installing as a Service

The project includes a script to install k9-polyvox as a user-level systemd service that starts automatically when you log in. Start by customizing the environment variables by editing the installer script:

```sh
nano ~/.config/systemd/user/k9_polyvox.service
```

Update settings as needed:

```sh
Environment=DISABLE_PIDOG_SPEAKER=0
Environment=DISABLE_PIDOG_DISPLAY=1
```

Then run the script to install as a service with those variables:

```sh
bash install_k9_service.sh ~/k9-polyvox/main.py
```

### Service Features:

- **User-level service**: Runs under your user account, not as root
- **Automatic startup**: Service starts when you log in
- **Pipewire compatible**: Designed to work with modern Pipewire audio system
- **Preconfigured environment**: Sets these variables by default:
  - `DISABLE_PIDOG_SPEAKER=0` (Uses PiDog's built-in speaker)
  - `DISABLE_PIDOG_DISPLAY=1` (Disables OLED display by default)

### Controlling the Service

```sh
# View real-time logs
journalctl --user -u k9_polyvox -f

# Stop the service
systemctl --user stop k9_polyvox

# Start the service
systemctl --user start k9_polyvox

# Disable automatic startup
systemctl --user disable k9_polyvox
```

### Customizing Environment Variables

To change the default environment variables after the service has been installed, edit the service file:

```sh
nano ~/.config/systemd/user/k9_polyvox.service
```

Modify the `Environment=` lines, then reload and restart:

```sh
systemctl --user daemon-reload
systemctl --user restart k9_polyvox
```



## Troubleshooting

- If you see errors related to the display or speaker, ensure the correct environment variables are set.
- Make sure your PiDog hardware is powered and connected.
- The app will use your default audio source and sink.  You can use pactl to view and set devices.

## License

See [LICENSE](LICENSE) for details.

---

For more information, see the [SunFounder PiDog documentation](https://docs.sunfounder.com/projects/pidog/en/latest/) and the comments in each source file.

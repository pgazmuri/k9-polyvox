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

## Audio Setup

Since my PiDog speaker failed, I switched to an external bluetooth speaker and separate wireless USB microphone. I moved to running pipewire in user mode, so sudo is no longer required for audio output.

There is some complexity around bluetooth devices and profiles, so I recommend getting default speaker and microphone working and tested before trying to run polyvox.

k9-polyvox is intended to run using default pipewire sources and sinks. It expects audio input at 48khz and outputs audio at 24khz currently, so the "headset" bluetooth profile will not work until that is updated to handle 24khz input.

To setup bluetooth devices, [Use Bluetoothctl](https://www.makeuseof.com/manage-bluetooth-linux-with-bluetoothctl/).

Be sure to set the profile to a2dp using "pactl set-card-profile". This profile is for high quality audio output, but doesn't support microphone input (hence my use of a separate USB mic). 
The headset profile is not currently supported as it expects a different sample rate, though I intend to add support for this.

You can install pipewire and set default sources and sinks using the cli:

```sh
# Install PipeWire (on Debian/Ubuntu systems)
sudo apt install pipewire pipewire-audio-client-libraries pipewire-pulse

# List available audio output devices (sinks)
pactl list short sinks

# List available audio input devices (sources)
pactl list short sources

# Get detailed information about a specific sink
pactl list sinks | less

# Get detailed information about a specific source
pactl list sources | less

# Set default audio output device (sink)
pactl set-default-sink sink_name
# Example: pactl set-default-sink bluez_sink.XX_XX_XX_XX_XX_XX.a2dp_sink

# Set default audio input device (source)
pactl set-default-source source_name
# Example: pactl set-default-source alsa_input.usb-Generic_USB_Audio_200901010001-00.mono-fallback

# Test audio output
paplay /usr/share/sounds/alsa/Front_Center.wav

# Test audio input (record for 5 seconds and play back)
parecord --channels=1 --format=s16le --rate=48000 test.wav --duration=5 && paplay test.wav
```

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
  *Important:* If you leave the speaker enabled, microphone input will be ignored while the dog is speaking. This is to avoid feedback where the dog will otherwise interrupt itself.  If you disable the speaker, you will be able to "interrupt" the dog mid-speech.

  It's recommended that you use a wireless usb mic with a mute button, so you can unmute to give a command or interrupt the dog without feedback cuasing issues.

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

The robot will boot, connect to OpenAI, and begin interacting. Use Ctrl+C to stop, or ask "Vector" to shut down.

### Web Control Center

The runtime now embeds a FastAPI web server that exposes telemetry, command, and awareness controls. By default it listens on `0.0.0.0:8080`, and can be customized via:

- `K9_WEB_HOST` – interface to bind (default `0.0.0.0`)
- `K9_WEB_PORT` – HTTP port (default `8080`)
- `K9_WEB_API_TOKEN` – optional bearer token for securing REST/WebSocket calls

The server will serve any production build dropped into `web/static`. To build the new React dashboard locally:

1. Install a recent Node.js runtime (v18+ recommended).
2. Install dependencies and run the development server:
  ```sh
  cd web/ui
  npm install
  npm run dev
  ```
  Configure `VITE_API_BASE` and `VITE_API_TOKEN` in a `.env.local` file if you proxy to a remote robot.
3. Build static assets for deployment:
  ```sh
  npm run build
  cp -r dist/* ../static/
  ```

With a build in place, browse to `http://<robot-ip>:8080/` to access the PiDog Control Center UI. The dashboard provides:

- Live awareness of loop status, posture, and attitude
- Camera tile that shows the most recent frame (with an ambient placeholder if no feed is available)
- Real-time event stream and timeline derived from the backend event bus
- Command console to toggle awareness/sensor loops, trigger preset actions, and enqueue custom awareness prompts

## Interacting with the dog

See the [user guide](USING_K9-POLYVOX.md) to learn how to interact with k9-polyvox.

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

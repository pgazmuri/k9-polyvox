import os
import textwrap
import time
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw, ImageFont

# --- Device Setup ---
if os.environ.get("DISABLE_PIDOG_DISPLAY") == "1":
    print("Display is disabled. Skipping initialization.")
else:
    try:
        serial = i2c(port=1, address=0x3C)
        device = ssd1306(serial, width=128, height=64)
        font = ImageFont.load_default()
        # Define the height of the top (yellow) region
        YELLOW_REGION_HEIGHT = 16 # Common for 128x64 two-color OLEDs
    except Exception as e:
        print(f"Error initializing OLED display: {e}")
        print("Display functions will not work.")
        device = None
        font = None
        YELLOW_REGION_HEIGHT = 0

# --- Constants ---
LINE_HEIGHT = 10 # Approx height for default font
PADDING = 2

def display_status(status_dict):
    """
    Displays 'Status:' header in the top (yellow) region and key-value pairs
    below in the bottom (blue) region.

    :param status_dict: Dictionary of status items (string: string/number).
    """
    if not device or not font:
        print("Display not initialized. Cannot display status.")
        return

    image = Image.new("1", (device.width, device.height))
    draw = ImageDraw.Draw(image)

    # --- Draw Header in Yellow Region ---
    header_text = "Status:"
    # Center the header text horizontally within padding
    header_width = draw.textlength(header_text, font=font)
    header_x = PADDING #(device.width - header_width) // 2 # Option to center
    header_y = PADDING
    # Ensure header fits in yellow region (adjust font/padding if needed)
    if header_y + LINE_HEIGHT <= YELLOW_REGION_HEIGHT:
        draw.text((header_x, header_y), header_text, font=font, fill=255)

    # --- Draw Status Items in Blue Region ---
    # Start drawing below the yellow region
    y_text = YELLOW_REGION_HEIGHT + PADDING

    for key, value in status_dict.items():
        # Stop if we run out of screen space in the blue region
        if y_text + LINE_HEIGHT > device.height - PADDING:
            break

        text_line = f"{key}: {value}"
        draw.text((PADDING, y_text), text_line, font=font, fill=255)
        y_text += LINE_HEIGHT

    device.display(image)

def display_message(title, description):
    """
    Displays the title in the top (yellow) region and the word-wrapped
    description below in the bottom (blue) region.

    :param title: The title string.
    :param description: The description string.
    """
    if not device or not font:
        print("Display not initialized. Cannot display message.")
        return

    image = Image.new("1", (device.width, device.height))
    draw = ImageDraw.Draw(image)

    # --- Draw Title in Yellow Region ---
    title_y = PADDING
    # Ensure title fits in yellow region
    if title_y + LINE_HEIGHT <= YELLOW_REGION_HEIGHT:
         # Center the title horizontally
         title_width = draw.textlength(title, font=font)
         title_x = (device.width - title_width) // 2
         draw.text((title_x, title_y), title, font=font, fill=255)

    # --- Draw Description in Blue Region (Word Wrapped) ---
    # Start drawing below the yellow region
    y_text = YELLOW_REGION_HEIGHT + PADDING

    char_width_estimate = 6
    max_chars_per_line = (device.width - 2 * PADDING) // char_width_estimate
    wrapped_description = textwrap.wrap(description, width=max_chars_per_line)

    for line in wrapped_description:
        # Stop if we run out of screen space in the blue region
        if y_text + LINE_HEIGHT > device.height - PADDING:
            break
        draw.text((PADDING, y_text), line, font=font, fill=255)
        y_text += LINE_HEIGHT

    device.display(image)

# --- Example Usage ---
if __name__ == "__main__":
    print("Testing display_manager with dedicated yellow region...")
    if device:
        try:
            status = {
                "IP Addr": "192.168.1.105",
                "Mode": "Active",
                "Battery": "85%",
                "Temp": "35C",
                "Voltage": "7.8V", # This might get cut off depending on font/lines
            }
            print("Displaying status...")
            display_status(status)
            time.sleep(5)

            print("Displaying message...")
            title_text = "System Alert!"
            desc_text = "Battery level critical. Please connect charger immediately. Performance may be reduced."
            display_message(title_text, desc_text)
            time.sleep(5)

            print("Clearing display.")
            device.clear()

        except Exception as e:
            print(f"An error occurred during testing: {e}")
        finally:
            try:
                device.clear()
            except:
                pass
    else:
        print("Device not initialized, skipping tests.")
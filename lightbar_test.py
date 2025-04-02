#!/usr/bin/env python3

import time
import statistics
import random
from pidog import Pidog  # Import the actual PiDog library

def test_lightbar_update_rate(my_dog, test_durations, frequencies):
    """
    Cycles through multiple frequencies of updates to see what
    maximum reliable rate we can achieve for each test period.

    :param my_dog: An instance of the PiDog object.
    :param test_durations: (list) durations in seconds to run each frequency test.
    :param frequencies: (list) frequencies (Hz) to try updating the bar.
    """

    for freq in frequencies:
        period = 1.0 / freq
        for duration in test_durations:
            update_times = []
            start_time = time.perf_counter()
            end_time = start_time + duration
            iteration = 0

            # Test loop
            while True:
                now = time.perf_counter()
                if now >= end_time:
                    break

                # Change color randomly
                r = random.randint(0, 255)
                g = random.randint(0, 255)
                b = random.randint(0, 255)
                # Optionally vary brightness for extra stress
                brightness = random.uniform(0.0, 1.0)

                # Convert RGB to hex color
                color = "#{:02x}{:02x}{:02x}".format(r, g, b)

                # Record the time before update
                t_before = time.perf_counter()
                
				# Actual hardware call using set_mode
                print("Setting lightbar mode at time: ", t_before)
                print("Brightness and color: ", brightness, color)
                r_scaled = min(int(r * brightness), 255)
                g_scaled = min(int(g * brightness), 255)
                b_scaled = min(int(b * brightness), 255)
                color = "#{:02x}{:02x}{:02x}".format(r_scaled, g_scaled, b_scaled)
                # my_dog.rgb_strip.set_mode(
                #     style="bark",  # Example style
                #     color="#ff0000",
                #     bps=.01,  # Blinks per second (can be adjusted as needed)
                #     brightness=brightness
                # )
                print("Scaled color: ", color)
                my_dog.rgb_strip.display([[r_scaled, g_scaled, b_scaled]]*my_dog.rgb_strip.light_num)
                #read_key = input("Press Enter to continue...")
                print("Set")
                # Record how long the update took
                t_after = time.perf_counter()
                update_times.append(t_after - t_before)

                iteration += 1

                # Sleep only if there's time left in this period
                elapsed = t_after - now
                sleep_time = period - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

            actual_updates = iteration
            total_duration = time.perf_counter() - start_time
            achieved_freq = actual_updates / total_duration
            avg_update_time = statistics.mean(update_times) if update_times else 0

            print(f"Frequency target: {freq} Hz | Test Duration: {duration}s")
            print(f"  - Performed {actual_updates} updates in {total_duration:.3f}s")
            print(f"  - Achieved ~{achieved_freq:.2f} Hz")
            print(f"  - Average time per update call: {avg_update_time * 1000:.2f} ms")
            print("-" * 50)

def main():
    # Initialize the real PiDog object
    my_dog = Pidog()

    # Frequencies you want to test (in Hz)
    test_frequencies = [60]

    # How long to test each frequency, you can expand or shorten:
    test_durations = [5]  # single duration (3s), or [3, 5, 10] for multiple

    print("Starting PiDog LightBar frequency test...")
    print("Sertting initial state")
    my_dog.rgb_strip.set_mode(
                    style="monochromatic",  # Example style
                    color="#ff0000",
                    bps=0,  # Blinks per second (can be adjusted as needed)
                    brightness=0
                )
    ready = input("Press Enter to start the test...")

    try:
        test_lightbar_update_rate(my_dog, test_durations, test_frequencies)
    except KeyboardInterrupt:
        print("Test interrupted.")
    finally:
        my_dog.close()  # Ensure the PiDog object is properly closed

if __name__ == "__main__":
    main()
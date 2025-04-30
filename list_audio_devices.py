import pyaudio
import sys

def get_device_index():
    p = pyaudio.PyAudio()
    info = p.get_host_api_info_list()
    # Iterate through devices and print their indices
    for i in range(p.get_device_count()):
        device_info = p.get_device_info_by_index(i)
        print(f"Device ID: {i} - {device_info['name']}")
    p.terminate()

if __name__ == "__main__":
    get_device_index()
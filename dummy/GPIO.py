def setmode(mode):
    print(f"GPIO setmode({mode}) called")
def setup(pin, direction):
    print(f"GPIO setup(pin={pin}, direction={direction}) called")
def input(pin):
    print(f"GPIO input(pin={pin}) called")
    return False # Default return value
def output(pin, value):
    print(f"GPIO output(pin={pin}, value={value}) called")
def cleanup():
    print("GPIO cleanup() called")

BCM = "BCM"
BOARD = "BOARD"
OUT = "OUT"
IN = "IN"
# Add other functions as needed
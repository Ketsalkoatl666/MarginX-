# from gpiozero import OutputDevice
# import time

# step = OutputDevice(24)

# while True:
#     step.on()
#     print("HIGH")
#     time.sleep(1)

#     step.off()
#     print("LOW")
#     time.sleep(1)

from gpiozero import OutputDevice
import time

step = OutputDevice(17)
direction = OutputDevice(27)

try:
    while True:
        step.on()
        direction.on()
        print("GPIO17 and GPIO27 HIGH (3.3 V)")
        time.sleep(3)

        step.off()
        direction.off()
        print("GPIO17 and GPIO27 LOW (0 V)")
        time.sleep(3)
finally:
    step.close()
    direction.close()

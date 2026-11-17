from gpiozero import Button
from time import sleep

CUP_PIN = 16
COVER_PIN = 6


def main():
    cup = Button(
        CUP_PIN,
        pull_up=True,
        bounce_time=0.05
    )

    cover = Button(
        COVER_PIN,
        pull_up=True,
        bounce_time=0.05
    )

    try:
        while True:
            print(
                f"Cup: {cup.is_pressed} | "
                f"Cover: {cover.is_pressed}"
            )
            sleep(0.3)

    finally:
        cup.close()
        cover.close()


if __name__ == "__main__":
    main()
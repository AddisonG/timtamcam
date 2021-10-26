#!/usr/bin/env python3
"""
timtamcam
"""
import os
import sys
import cv2
import json
import time
import logging
import requests
import argparse
import imageio

from slack.errors import SlackApiError

import RPi.GPIO as GPIO
from hx711 import HX711

from SlackBot import SlackBot

# Bot User OAuth Token (Install App Page)
with open("bot_token.txt", "r") as token_file:
    bot_token = token_file.readline().strip()


LOGFILE_FORMAT = '%(asctime)-15s %(module)s %(levelname)s %(message)s'
STDOUT_FORMAT  = '%(asctime)s [%(levelname)s] - %(message)s'

logger = logging.getLogger(__name__)
logging.basicConfig(filename='timtamcam.log', level=logging.INFO, format=LOGFILE_FORMAT)

class TimTamCam(SlackBot):
    """
    Watches the Tim Tams. Ever vigilant.
    """

    def __init__(self, ip_address):
        self.setup_logging()
        logger.info("Tim Tam Bot starting!")

        super().__init__(bot_token)

        # The script directory
        script_dir = os.path.dirname(os.path.realpath(__file__))

        # Make sure we're in the bots channel
        logger.info("Joining the bots channel")
        self.bot_channel = json.load(open(f"{script_dir}/bot_channel.json"))
        self.join_channel_by_id(self.bot_channel["id"])

        logger.info("Setting up the scales")
        self.setup_scales()

        # Watch (loop)
        self.monitor_weight()


    def setup_scales(self):
        # GPIO port 5 = DATA and 6 = CLOCK
        self.hx = HX711(5, 6)
        self.hx.set_reading_format("MSB", "MSB")
        self.hx.set_reference_unit(464)
        self.hx.reset()
        self.hx.tare()

    def setup_logging(self):
        # Log to a file
        logger.setLevel(logging.INFO)

        # Log to stdout
        formatter = logging.Formatter(fmt=STDOUT_FORMAT)
        log_handler_stdout = logging.StreamHandler(sys.stdout)
        log_handler_stdout.setFormatter(formatter)
        logger.addHandler(log_handler_stdout)

    def alert(self, num_timtams: float):
        # Hardcode the IP address
        ip = "192.168.252.134"
        username = "opengear"
        password = "default"

        # stream1 is 1080p, stream2 is 360p
        stream_url = f"rtsp://{username}:{password}@{ip}/stream1"

        try:
            self.record_gif(stream_url, 5)
        except Exception as e:
            logger.error("Failed to take photo!")
            logger.error(e)
            return

        try:
            self.send_file(self.bot_channel, "/tmp/timtam-thief.gif", f"Timtam tampering detected! Someone took {int(num_timtams)} Tim Tams!")

            # self.send_message("Timtams tampering detected!", self.bot_channel)
        except SlackApiError as api_error:
            logger.error(api_error)
        except requests.exceptions.RequestException as e:
            raise SystemExit(e)


    def record_gif(self, ip, num_frames):
        logger.info("Recording a gif of the thief")
        cap = cv2.VideoCapture(ip)
        stream_fps = int(cap.get(cv2.CAP_PROP_FPS))
        # stream_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        # stream_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

        frames = 0
        images = []
        # Record several frames
        while cap.isOpened() and len(images) < num_frames:
            ret, frame = cap.read()
            frames += 1

            # Record at 1 FPS
            if (frames % stream_fps) == 0:
                self.camera_check(cap, ret, frame)

                # Save a single image
                # cv2.imwrite("/tmp/timtam-thief.jpg", frame)

                # Convert to RGB for gifs
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                images.append(rgb_frame)

        # Write frames to gif
        logger.debug("Saving timtam thief image.")
        imageio.mimsave('/tmp/timtam-thief.gif', images, duration=0.3)
        logger.info("Saved gif")

        cap.release()

    def camera_check(self, cap, ret, frame):
        if not cap.isOpened() or not ret or frame is None or frame.size == 0:
            cap.release()
            raise SystemExit("Camera is unreachable, or had other error.")


    def monitor_weight(self):
        logger.info("Now monitoring Tim Tams")
        timtam_weight = 18.3
        museli_bar = 32

        previous = None

        while True:
            try:
                weight = self.hx.get_weight(5)
                if previous is not None:
                    timtam_change = round((previous - weight) / timtam_weight, 0)
                    if timtam_change > 0.8:
                        # Someone has taken 80% or more of a timtam. Close enough!
                        self.alert(timtam_change)

                # No idea why we do this
                self.hx.power_down()
                self.hx.power_up()

                previous = weight
                time.sleep(0.1)

            except (KeyboardInterrupt, SystemExit) as e:
                logger.error(str(e))
                GPIO.cleanup()
                return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="timtamcam",
        description="Watches the Tim Tams. Ever vigilant.",
    )

    # TODO - DYNAMICALLY FIND THE IP ADDRESS OF THE CAMERA

    parser.add_argument("--ip", "-i", type=str, required=True,
        help="The IP address of the camera.")
    parser.add_argument("--debug", "-x", action='store_true',
        help="Enable debugging,")

    # sys.argv[1:]
    args = parser.parse_args()

    bot = TimTamCam(args.ip)

    exit(0)


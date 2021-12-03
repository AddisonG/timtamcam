#!/usr/bin/env python3

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

import RPi.GPIO
from hx711 import HX711

from slackbot import SlackBot
from network_scanner import find_ip_by_mac

# Bot User OAuth Token (Install App Page)
with open("bot_token.txt", "r") as token_file:
    bot_token = token_file.readline().strip()


LOGFILE_FORMAT = '%(asctime)-15s %(module)s %(levelname)s: %(message)s'
STDOUT_FORMAT  = '%(asctime)s [%(levelname)s] - %(message)s'

logger = logging.getLogger(__name__)
logging.basicConfig(filename='timtamcam.log', level=logging.INFO, format=LOGFILE_FORMAT)


class TimTamCam(SlackBot):
    """
    Watches the Tim Tams. Ever vigilant.
    """

    def __init__(self):
        self.setup_logging()
        logger.info("Tim Tam Bot starting!")

        super().__init__(bot_token)

        # The script directory (where this file, config, etc, is stored)
        self.script_dir = os.path.dirname(os.path.realpath(__file__))

        # Get the IP address of the camera
        self.load_camera_url()

        # Make sure we're in the bots channel
        logger.info("Joining the bots channel")
        self.bot_channel = json.load(open(f"{self.script_dir}/bot_channel.json"))
        self.join_channel_by_id(self.bot_channel["id"])

        self.mask = None
        # The mask is SUBTRACTED, then the border is then ADDED
        # self.mask = cv2.imread(f"{self.script_dir}/halloween-mask.png", cv2.IMREAD_COLOR)
        # self.border = cv2.imread(f"{self.script_dir}/halloween-border.png", cv2.IMREAD_COLOR)

    def load_camera_url(self):
        logger.info("Attempting to find camera IP by MAC address")
        with open(f"{self.script_dir}/camera.json") as cam_file:
            cam_details = json.load(cam_file)
            network = cam_details["network"]
            username = cam_details["username"]
            password = cam_details["password"]
            mac = cam_details["mac"]

        camera_ip = find_ip_by_mac(network, mac)

        if not camera_ip:
            raise RuntimeError("Could not find camera URL")

        logger.info(f"Found camera '{mac}' at '{camera_ip}'.")

        # stream1 is 1080p, stream2 is 360p
        self.stream_url = f"rtsp://{username}:{password}@{camera_ip}/stream1"

    def setup_scales(self):
        # GPIO port 5 = DATA and 6 = CLOCK
        self.hx = HX711(5, 6)
        self.hx.set_reading_format("MSB", "MSB")
        self.hx.set_reference_unit(446)
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
        try:
            self.record_gif(5, 2)
        except Exception as e:
            logger.error("Failed to take photo!")
            logger.error(e)

            # Try to recover the camera
            try:
                self.load_camera_url()
                self.record_gif(5, 2)
                logger.info("Successfully recovered from bad camera!")
            except Exception:
                self.send_message(self.bot_channel, "Timtams tampering detected! But the camera is disconnected...")
                return

        try:
            self.send_file(self.bot_channel, "/tmp/timtam-thief.gif", f"Timtam tampering detected! Someone took {round(num_timtams, 0)} Tim Tams!")
        except SlackApiError as api_error:
            logger.error(api_error)
        except requests.exceptions.RequestException as e:
            raise SystemExit(e)


    def record_gif(self, duration, fps):
        logger.info("Recording a gif of the thief")
        cap = cv2.VideoCapture(self.stream_url)
        stream_fps = int(cap.get(cv2.CAP_PROP_FPS))
        # stream_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        # stream_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

        frames = 0
        images = []
        # Record several frames
        while cap.isOpened() and len(images) < (duration * fps):
            ret, frame = cap.read()
            frames += 1

            if (frames % (stream_fps // fps)) == 0:
                self.camera_check(cap, ret, frame)

                # Save a single image
                # cv2.imwrite("/tmp/timtam-thief.jpg", frame)

                if self.mask is not None:
                    # Add overlay
                    frame = cv2.subtract(frame, self.mask)
                    frame = cv2.addWeighted(frame, 1, self.border, 1, 0)

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
            logger.error("Critical camera error")
            raise RuntimeError("Camera is unreachable, or had other error.")


    def monitor_weight(self):
        logger.info("Now monitoring Tim Tams")
        timtam_weight = 18.3

        item = timtam_weight

        previous = None
        while True:
            try:
                weight = self.hx.get_weight(15)
                logger.debug(f"Weight: {weight}")
                if previous is not None:
                    timtam_change = round((previous - weight) / item, 1)
                    if timtam_change > 0.8:
                        # Someone has taken 80% or more of a timtam. Close enough!
                        self.alert(timtam_change)
                        previous = None
                        continue

                previous = weight

            except (KeyboardInterrupt, SystemExit) as e:
                logger.error(str(e))
                RPi.GPIO.cleanup()
                return

    # This function is run as part of the daemon
    def run(self):
        logger.info("Setting up the scales")
        self.setup_scales()

        # Watch (loop)
        self.monitor_weight()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="timtamcam",
        description="Watches the Tim Tams. Ever vigilant.",
    )

    # parser.add_argument("--mac", "-m", type=str, required=True,
    #     help="The MAC address of the camera.")
    parser.add_argument("--debug", "-x", action='store_true',
        help="Enable debugging,")

    # sys.argv[1:]
    args = parser.parse_args()

    bot = TimTamCam()
    bot.run()

    exit(0)

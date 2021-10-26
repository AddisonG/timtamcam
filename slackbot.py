#!/usr/bin/env python3

import logging
import backoff
from typing import Union

from slack import WebClient
from slack.errors import SlackApiError


LOGFILE_FORMAT = '%(asctime)-15s %(module)s %(levelname)s %(message)s'
logger = logging.getLogger(__name__)
logging.basicConfig(filename='timtamcam.log', level=logging.INFO, format=LOGFILE_FORMAT)


class SlackBot():
    """
    Generic Slackbot implementation that allows sending messages to users,
    channels, and other basic functionality.

    Based off Lachlan Archibald's excellent implementation from ogdevicebot.
    """

    def __init__(self, token: str):
        if not token or not token.startswith("xoxb"):
            raise RuntimeError("Valid bot token needed - must start with 'xoxb'")
        self.client = WebClient(token=token)
        if not self.client:
            raise RuntimeError("Slack web client could not start")

    def send_file(self, channels: Union[list, str, dict], file_location: str, message: str = None, title: str = None):
        if type(channels) is list:
            channels = channels.join(",")
        if type(channels) is dict:
            channels = channels.get("id")

        self.client.files_upload(
            channels=channels,
            file=file_location,
            initial_comment=message,
            title=title,
            # filetype="png",
            # filename="file name when downloaded",
        )

    def join_channel_by_id(self, channel_id: str):
        self.client.conversations_join(channel=channel_id)

    def join_channel_by_name(self, channel_name: str):
        all_channels = self.client.conversations_list(limit=1000)["channels"]
        matching_channel = next(filter(lambda x: x["name"] == channel_name, all_channels), None)
        if not matching_channel:
            raise RuntimeError(f"Could not find channel with name '{channel_name}'.")
        self.join_channel_by_id(matching_channel["id"])

    def get_all_users(self):
        return self.client.users_list(limit=1000)["members"]

    def send_message(self, recipient: Union[str, dict], message: str):
        """
        Send a message to a given Slack user or channel
        """
        if not recipient:
            logger.error("Recipient data not provided")
            return

        if recipient is dict:
            r_name = recipient['name']
            r_id = recipient['id']
        else:
            r_name = "???"
            r_id = recipient

        logger.info(f"Sending message to '{r_name}' ({r_id}): \"{message}\"")
        response = self.client.chat_postMessage(channel=r_id, text=message)
        if not response['ok']:
            logger.info(f"Failed to send message to '{r_name}' ({r_id}): \"{message}\"")

    def delete_messages(self):
        """
        Delete all direct messages (only) sent by this bot
        """
        logger.info("Deleting direct messages sent by bot")

        @backoff.on_exception(backoff.expo, SlackApiError, max_time=60)
        def delete_message(message, conversation):
            try:
                logger.debug(f"Message: <{message['text']}>")
                logger.debug(f"Deleting message <{message['ts']}> from conversation <{conversation['id']}>")
                self.client.chat_delete(channel=conversation['id'], ts=message['ts'])['ok']
            except SlackApiError as api_error:
                # if we encounter ratelimiting, raise the exception to backoff
                if api_error.response["error"] == "ratelimited":
                    raise
                # if it's anything else, log and continue.
                logger.error(api_error)

        try:
            # get all conversations (single person direct messages only) from this bot
            conversations = self.client.conversations_list(types="im")['channels']
            logger.debug("Retrieved <%d> conversations", len(conversations))
            for conversation in conversations:
                # for each conversation, delete all messages
                messages = self.client.conversations_history(channel=conversation['id'])['messages']
                logger.debug("Retrieved <%d> messages in conversation <%s>",
                            len(messages), conversation['id'])
                for message in messages:
                    delete_message(message, conversation)
        except SlackApiError as api_error:
            logger.error(api_error)

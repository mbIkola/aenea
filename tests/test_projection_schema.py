"""Validate the declared projection against the locked Telethon schema."""

import inspect
import json
import unittest
from datetime import UTC, datetime

from aenea_telegram.normalization import _FIELDS, normalize_message
from telethon.tl import types


class ProjectionSchemaTests(unittest.TestCase):
    def test_declared_constructors_and_fields_exist_in_supported_sdk(self):
        for name, fields in _FIELDS.items():
            with self.subTest(constructor=name):
                constructor = getattr(types, name, None)
                self.assertIsNotNone(constructor, f"Unknown declared constructor: {name}")
                parameters = set(inspect.signature(constructor).parameters)
                self.assertFalse(set(fields) - parameters - {"option_hex"})
                # Every source field is either projected, encoded, or deliberately
                # excluded. An SDK update requires an explicit schema review.
                accounted_elsewhere = {
                    "MessageMediaPoll": {"results"},  # snapshot
                    "MessageMediaWidget": {"payload"},  # opaque binary
                    "Photo": {"access_hash", "file_reference"},
                    "Document": {"access_hash", "file_reference"},
                    "DocumentAttributeAudio": {"waveform"},
                    "Poll": {"closed", "close_date", "hash"},  # snapshot
                    "PollAnswer": {"option"},  # option_hex
                    "PollAnswerVoters": {"option"},  # option_hex
                    "GeoPoint": {"access_hash"},
                    "MessageActionPaymentSentMe": {"payload"},
                    "InputGroupCall": {"access_hash"},
                    "InputStickerSetID": {"access_hash"},
                    "PhotoCachedSize": {"bytes"},
                    "PhotoStrippedSize": {"bytes"},
                    "PhotoPathSize": {"bytes"},
                }
                self.assertEqual(parameters - set(fields), accounted_elsewhere.get(name, set()))

    def normalize(self, **fields):
        message = types.MessageService(
            id=1, peer_id=types.PeerChat(2), date=datetime(2026, 11, 24, tzinfo=UTC), **fields
        )
        return json.loads(normalize_message(message, source_account_id=3, chat_id=-2).metadata_json)

    def test_supported_service_and_entity_fields_are_not_silently_lost(self):
        metadata = self.normalize(
            action=types.MessageActionGiveawayLaunch(stars=42),
            entities=[types.MessageEntityDiffReplace(offset=0, length=1, old_text="before")],
        )
        self.assertEqual(metadata["content"]["action"]["stars"], 42)
        self.assertEqual(metadata["content"]["entities"][0]["old_text"], "before")

    def test_webview_service_text_is_retained(self):
        metadata = self.normalize(action=types.MessageActionWebViewDataSent("submitted"))
        self.assertEqual(metadata["content"]["action"]["text"], "submitted")

    def test_widget_keeps_declared_content_without_binary_payload(self):
        metadata = self.normalize(
            media=types.MessageMediaWidget(
                width=320,
                height=200,
                payload=b"private-binary",
                widget_id=42,
                public_data='{"title":"widget"}',
            )
        )
        media = metadata["content"]["media"]
        self.assertEqual(media["widget_id"], 42)
        self.assertEqual(media["width"], 320)
        self.assertIn("widget", media["public_data"])
        self.assertNotIn("private-binary", json.dumps(metadata))

    def test_keyboard_type_retains_safe_url(self):
        metadata = self.normalize(
            reply_markup=types.ReplyInlineMarkup(
                rows=[
                    types.KeyboardButtonRow(
                        [
                            types.KeyboardButton(
                                "Open", types.ButtonTypeSimpleWebView("https://example.test")
                            )
                        ]
                    )
                ]
            )
        )
        button = metadata["content"]["reply_markup"]["rows"][0]["buttons"][0]
        self.assertEqual(button["type"]["url"], "https://example.test")

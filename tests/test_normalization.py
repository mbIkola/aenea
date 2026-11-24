"""Offline tests for the explicitly bounded Telethon projection."""

import json
import unittest
from datetime import UTC, datetime

from aenea_telegram.normalization import normalize_message
from telethon.tl import types


class NormalizeMessageTests(unittest.TestCase):
    def _message(self, **kwargs):
        return types.Message(
            id=41,
            peer_id=types.PeerChannel(123),
            date=datetime(2026, 1, 2, tzinfo=UTC),
            message="Привет 🛰 мир",
            **kwargs,
        )

    def _normalize(self, message, **kwargs):
        return normalize_message(
            message,
            source_account_id=9,
            chat_id=-1000000000123,
            received_at=datetime(2026, 1, 3, tzinfo=UTC),
            **kwargs,
        )

    def _metadata(self, result):
        return json.loads(result.metadata_json)

    def test_unicode_entities_keep_telegram_utf16_offsets(self):
        result = self._normalize(
            self._message(entities=[types.MessageEntityBold(offset=8, length=3)])
        )
        self.assertEqual(result.text, "Привет 🛰 мир")
        metadata = self._metadata(result)
        self.assertEqual(metadata["content"]["entities"][0]["offset"], 8)
        self.assertEqual(metadata["content"]["entities"][0]["length"], 3)
        self.assertEqual(result.source, "telegram")
        self.assertEqual(result.metadata_version, 1)

    def test_local_reply_and_topic_are_projected(self):
        result = self._normalize(
            self._message(
                reply_to=types.MessageReplyHeader(
                    reply_to_msg_id=17, reply_to_top_id=12, forum_topic=True
                )
            )
        )
        self.assertEqual(result.reply_to_message_id, 17)
        self.assertEqual(result.topic_id, 12)

    def test_ordinary_discussion_thread_does_not_become_forum_topic(self):
        for forum_topic in (False, None):
            with self.subTest(forum_topic=forum_topic):
                result = self._normalize(
                    self._message(
                        reply_to=types.MessageReplyHeader(
                            reply_to_msg_id=17, reply_to_top_id=12, forum_topic=forum_topic
                        )
                    )
                )
                self.assertIsNone(result.topic_id)
                self.assertEqual(result.reply_to_message_id, 17)
                header = self._metadata(result)["content"]["reply_to"]
                self.assertEqual(header["reply_to_top_id"], 12)

    def test_external_and_scheduled_replies_do_not_make_local_links(self):
        external = self._normalize(
            self._message(
                reply_to=types.MessageReplyHeader(
                    reply_to_msg_id=17, reply_to_peer_id=types.PeerChat(123)
                )
            )
        )
        scheduled = self._normalize(
            self._message(
                reply_to=types.MessageReplyHeader(reply_to_msg_id=17, reply_to_scheduled=True)
            )
        )
        self.assertIsNone(external.reply_to_message_id)
        self.assertEqual(
            self._metadata(external)["content"]["reply_to"]["reply_to_peer_id"]["type"], "chat"
        )
        self.assertIsNone(scheduled.reply_to_message_id)

    def test_unknown_peer_ephemeral_and_external_topic_never_link_locally(self):
        ephemeral = self._normalize(
            self._message(
                reply_to=types.MessageReplyHeader(
                    reply_to_msg_id=17, reply_to_ephemeral=True, reply_to_top_id=10
                )
            )
        )
        external_topic = self._normalize(
            self._message(
                reply_to=types.MessageReplyHeader(
                    reply_to_msg_id=17, reply_to_peer_id=types.PeerUser(55), reply_to_top_id=10
                )
            )
        )
        local_root = self._normalize(
            self._message(reply_to=types.MessageReplyHeader(reply_to_msg_id=17, forum_topic=True))
        )
        self.assertIsNone(ephemeral.reply_to_message_id)
        self.assertIsNone(external_topic.reply_to_message_id)
        self.assertIsNone(external_topic.topic_id)
        self.assertEqual(local_root.topic_id, 17)

    def test_forward_and_document_attributes_preserve_safe_fields_only(self):
        document = types.Document(
            id=88,
            access_hash=444,
            file_reference=b"secret-file-ref",
            date=datetime(2026, 1, 1, tzinfo=UTC),
            mime_type="audio/ogg",
            size=10,
            dc_id=2,
            attributes=[
                types.DocumentAttributeFilename("voice.ogg"),
                types.DocumentAttributeAudio(5, voice=True, waveform=b"wave"),
            ],
        )
        document.file_reference = b"nested-secret"
        result = self._normalize(
            self._message(
                fwd_from=types.MessageFwdHeader(
                    date=datetime(2025, 12, 31, tzinfo=UTC),
                    from_id=types.PeerChannel(77),
                    channel_post=5,
                    post_author="Автор",
                ),
                media=types.MessageMediaDocument(document=document, spoiler=True),
            )
        )
        raw = result.metadata_json
        for forbidden in (
            "access_hash",
            "file_reference",
            "nested-secret",
            "secret-file-ref",
            "wave",
        ):
            self.assertNotIn(forbidden, raw)
        metadata = self._metadata(result)
        self.assertEqual(metadata["content"]["forward"]["post_author"], "Автор")
        self.assertEqual(
            metadata["content"]["media"]["document"]["attributes"][0]["file_name"], "voice.ogg"
        )

    def test_poll_results_go_to_snapshot_but_question_is_stable_content(self):
        media = types.MessageMediaPoll(
            poll=types.Poll(
                id=5,
                question=types.TextWithEntities("Выбор?", []),
                answers=[types.PollAnswer(types.TextWithEntities("Да", []), b"\x01")],
                hash=8,
            ),
            results=types.PollResults(total_voters=3),
        )
        result = self._normalize(self._message(media=media))
        metadata = self._metadata(result)
        self.assertEqual(metadata["content"]["media"]["poll"]["question"]["text"], "Выбор?")
        self.assertEqual(metadata["snapshot"]["poll_results"]["total_voters"], 3)
        self.assertEqual(metadata["content"]["media"]["poll"]["answers"][0]["option_hex"], "01")

    def test_photo_dimensions_and_reaction_counts_are_projected_as_observation(self):
        photo = types.Photo(
            id=12,
            access_hash=999,
            file_reference=b"photo-reference",
            date=datetime(2026, 1, 1, tzinfo=UTC),
            sizes=[types.PhotoSize("m", 640, 480, 1234)],
            dc_id=2,
        )
        result = self._normalize(
            self._message(
                media=types.MessageMediaPhoto(photo=photo),
                reactions=types.MessageReactions(
                    results=[types.ReactionCount(types.ReactionEmoji("👍"), 2)]
                ),
            )
        )
        metadata = self._metadata(result)
        self.assertEqual(metadata["content"]["media"]["photo"]["sizes"][0]["w"], 640)
        self.assertEqual(metadata["content"]["media"]["photo"]["sizes"][0]["h"], 480)
        self.assertEqual(metadata["snapshot"]["reactions"]["results"][0]["count"], 2)
        self.assertNotIn("photo-reference", result.metadata_json)

    def test_known_wrapper_with_unknown_nested_constructor_is_incomplete(self):
        class Game:
            payload = b"not persisted"

        result = self._normalize(self._message(media=types.MessageMediaGame(game=Game())))
        metadata = self._metadata(result)
        self.assertFalse(metadata["content"]["projection_complete"])
        self.assertEqual(metadata["content"]["media"]["game"]["constructor"], "Game")
        self.assertNotIn("not persisted", result.metadata_json)

    def test_contact_geo_web_preview_and_service_action_are_supported(self):
        cases = [
            (types.MessageMediaContact("+410000", "Анна", "Я", "", 7), "contact"),
            (types.MessageMediaGeo(types.GeoPoint(long=8.5, lat=47.3, access_hash=99)), "geo"),
            (
                types.MessageMediaWebPage(
                    types.WebPage(
                        id=3,
                        url="https://example.test",
                        display_url="example.test",
                        hash=0,
                        title="Сайт",
                    )
                ),
                "web_page",
            ),
        ]
        for media, expected in cases:
            with self.subTest(expected=expected):
                result = self._normalize(self._message(media=media))
                media_value = self._metadata(result)["content"]["media"]
                self.assertIn("constructor", media_value)
                if expected == "contact":
                    self.assertEqual(media_value["constructor"], "MessageMediaContact")
                elif expected == "web_page":
                    self.assertIn("webpage", media_value)
                else:
                    self.assertIn(expected, json.dumps(media_value, ensure_ascii=False))
                self.assertNotIn("access_hash", result.metadata_json)

        service = types.MessageService(
            id=42,
            peer_id=types.PeerChat(4),
            date=datetime(2026, 1, 2, tzinfo=UTC),
            action=types.MessageActionChatCreate("Новая группа", [3]),
        )
        result = self._normalize(service)
        self.assertIn("Новая группа", result.metadata_json)

    def test_unknown_constructor_is_named_and_marks_projection_incomplete(self):
        class MessageMediaFuture:
            secret_payload = b"never persist"

        result = self._normalize(self._message(media=MessageMediaFuture()))
        metadata = self._metadata(result)
        self.assertFalse(metadata["content"]["projection_complete"])
        self.assertEqual(metadata["content"]["media"]["constructor"], "MessageMediaFuture")
        self.assertNotIn("never persist", result.metadata_json)
        self.assertEqual(result.text, "Привет 🛰 мир")


if __name__ == "__main__":
    unittest.main()

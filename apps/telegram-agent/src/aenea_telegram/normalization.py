"""Explicit, versioned projection from Telethon TL objects to the Inbox contract.

Allowlisted constructor fields are deliberately spelled out: SDK additions are
not accepted automatically. Unknown nested constructors are named and omitted.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from aenea_contracts import IncomingMessage
from telethon import utils

METADATA_VERSION = 1

# Fixed Telethon 1.46 schema for entities, headers, media and actions. Values
# such as access_hash, file_reference and byte payloads are never listed.
_FIELDS: dict[str, tuple[str, ...]] = {
    "MessageEntityUnknown": ("offset", "length"),
    "MessageEntityMention": ("offset", "length"),
    "MessageEntityHashtag": ("offset", "length"),
    "MessageEntityBotCommand": ("offset", "length"),
    "MessageEntityUrl": ("offset", "length"),
    "MessageEntityEmail": ("offset", "length"),
    "MessageEntityBold": ("offset", "length"),
    "MessageEntityItalic": ("offset", "length"),
    "MessageEntityCode": ("offset", "length"),
    "MessageEntityPre": ("offset", "length", "language"),
    "MessageEntityTextUrl": ("offset", "length", "url"),
    "MessageEntityMentionName": ("offset", "length", "user_id"),
    "InputMessageEntityMentionName": ("offset", "length", "user_id"),
    "MessageEntityPhone": ("offset", "length"),
    "MessageEntityCashtag": ("offset", "length"),
    "MessageEntityUnderline": ("offset", "length"),
    "MessageEntityStrike": ("offset", "length"),
    "MessageEntityBankCard": ("offset", "length"),
    "MessageEntitySpoiler": ("offset", "length"),
    "MessageEntityCustomEmoji": ("offset", "length", "document_id"),
    "MessageEntityBlockquote": ("offset", "length", "collapsed"),
    "MessageEntityFormattedDate": (
        "offset",
        "length",
        "date",
        "day_of_week",
        "long_date",
        "long_time",
        "relative",
        "short_date",
        "short_time",
    ),
    "MessageEntityDiffInsert": ("offset", "length"),
    "MessageEntityDiffReplace": ("offset", "length", "old_text"),
    "MessageEntityDiffDelete": ("offset", "length"),
    "MessageEntityTonAddress": ("offset", "length"),
    "MessageFwdHeader": (
        "imported",
        "saved_out",
        "from_id",
        "from_name",
        "channel_post",
        "post_author",
        "saved_from_peer",
        "saved_from_msg_id",
        "saved_from_id",
        "saved_from_name",
        "date",
        "saved_date",
        "psa_type",
    ),
    "MessageReplyHeader": (
        "reply_to_scheduled",
        "forum_topic",
        "quote",
        "reply_to_ephemeral",
        "reply_to_msg_id",
        "reply_to_peer_id",
        "reply_from",
        "reply_media",
        "reply_to_top_id",
        "quote_text",
        "quote_entities",
        "quote_offset",
        "todo_item_id",
        "quote_rich",
        "poll_option",
    ),
    "MessageReplyStoryHeader": ("peer", "story_id"),
    "MessageMediaEmpty": (),
    "MessageMediaPhoto": ("photo", "spoiler", "ttl_seconds", "video", "live_photo"),
    "MessageMediaDocument": (
        "document",
        "nopremium",
        "spoiler",
        "video",
        "round",
        "voice",
        "video_timestamp",
        "ttl_seconds",
        "alt_documents",
        "video_cover",
    ),
    "MessageMediaGeo": ("geo",),
    "MessageMediaGeoLive": ("geo", "heading", "period", "proximity_notification_radius"),
    "MessageMediaVenue": ("title", "address", "provider", "venue_id", "venue_type", "geo"),
    "MessageMediaContact": ("phone_number", "first_name", "last_name", "vcard", "user_id"),
    "MessageMediaWebPage": ("webpage", "force_large_media", "force_small_media", "manual", "safe"),
    "MessageMediaPoll": ("poll", "attached_media"),
    "MessageMediaDice": ("value", "emoticon", "game_outcome"),
    "MessageMediaGame": ("game",),
    "MessageMediaInvoice": (
        "shipping_address_requested",
        "test",
        "title",
        "description",
        "photo",
        "receipt_msg_id",
        "currency",
        "total_amount",
        "start_param",
        "extended_media",
    ),
    "MessageMediaStory": ("via_mention", "peer", "id", "story"),
    "MessageMediaGiveaway": (
        "only_new_subscribers",
        "winners_are_visible",
        "channels",
        "countries_iso2",
        "prize_description",
        "quantity",
        "months",
        "until_date",
        "stars",
    ),
    "MessageMediaGiveawayResults": (
        "channel_id",
        "launch_msg_id",
        "winners_count",
        "unclaimed_count",
        "winners",
        "until_date",
        "only_new_subscribers",
        "refunded",
        "additional_peers_count",
        "months",
        "stars",
        "prize_description",
    ),
    "MessageMediaPaidMedia": ("stars_amount", "extended_media"),
    "MessageMediaToDo": ("todo", "completions"),
    "MessageMediaVideoStream": ("call", "rtmp_stream"),
    "MessageMediaWidget": (
        "width",
        "height",
        "is_copy",
        "can_query",
        "background_query",
        "public_data",
        "public_data_hash",
        "chat_data",
        "widget_id",
    ),
    "Photo": ("id", "date", "sizes", "video_sizes", "dc_id", "has_stickers"),
    "PhotoSize": ("type", "w", "h", "size"),
    "PhotoSizeProgressive": ("type", "w", "h", "sizes"),
    "PhotoSizeEmpty": ("type",),
    "VideoSize": ("type", "w", "h", "size", "video_start_ts"),
    "Document": (
        "id",
        "date",
        "mime_type",
        "size",
        "attributes",
        "thumbs",
        "video_thumbs",
        "dc_id",
    ),
    "DocumentAttributeFilename": ("file_name",),
    "DocumentAttributeAudio": ("duration", "voice", "title", "performer"),
    "DocumentAttributeVideo": (
        "round_message",
        "supports_streaming",
        "nosound",
        "duration",
        "w",
        "h",
        "preload_prefix_size",
        "video_start_ts",
        "video_codec",
    ),
    "DocumentAttributeImageSize": ("w", "h"),
    "DocumentAttributeSticker": ("mask", "alt", "stickerset", "mask_coords"),
    "DocumentAttributeAnimated": (),
    "DocumentAttributeHasStickers": (),
    "DocumentAttributeCustomEmoji": ("free", "text_color", "alt", "stickerset"),
    "Poll": (
        "id",
        "question",
        "answers",
        "public_voters",
        "multiple_choice",
        "quiz",
        "open_answers",
        "revoting_disabled",
        "shuffle_answers",
        "hide_results_until_close",
        "creator",
        "subscribers_only",
        "close_period",
        "countries_iso2",
    ),
    "PollAnswer": ("text", "option_hex", "media", "added_by", "date"),
    "TextWithEntities": ("text", "entities"),
    "PollResults": (
        "total_voters",
        "has_unread_votes",
        "recent_voters",
        "min",
        "can_view_stats",
        "solution",
        "solution_entities",
        "solution_media",
        "results",
    ),
    "PollAnswerVoters": ("chosen", "correct", "option_hex", "voters", "recent_voters"),
    "MessageReplies": (
        "comments",
        "replies",
        "replies_pts",
        "recent_repliers",
        "channel_id",
        "max_id",
        "read_max_id",
    ),
    "MessageReactions": (
        "results",
        "min",
        "can_see_list",
        "reactions_as_tags",
        "recent_reactions",
        "top_reactors",
    ),
    "MessagePeerReaction": ("peer_id", "date", "reaction", "big", "my", "unread"),
    "ReactionCount": ("reaction", "count", "chosen_order"),
    "ReactionEmoji": ("emoticon",),
    "ReactionCustomEmoji": ("document_id",),
    "GeoPoint": ("long", "lat", "accuracy_radius"),
    "WebPage": (
        "id",
        "url",
        "display_url",
        "has_large_media",
        "video_cover_photo",
        "type",
        "site_name",
        "title",
        "description",
        "photo",
        "embed_url",
        "embed_type",
        "embed_width",
        "embed_height",
        "duration",
        "author",
        "document",
        "cached_page",
        "attributes",
        "hash",
    ),
    "MessageActionEmpty": (),
    "MessageActionChatCreate": ("title", "users"),
    "MessageActionChatEditTitle": ("title",),
    "MessageActionChatEditPhoto": ("photo",),
    "MessageActionChatDeletePhoto": (),
    "MessageActionChatAddUser": ("users",),
    "MessageActionChatDeleteUser": ("user_id",),
    "MessageActionChatJoinedByLink": ("inviter_id",),
    "MessageActionChannelCreate": ("title",),
    "MessageActionChatMigrateTo": ("channel_id",),
    "MessageActionChannelMigrateFrom": ("title", "chat_id"),
    "MessageActionPinMessage": (),
    "MessageActionHistoryClear": (),
    "MessageActionGameScore": ("game_id", "score"),
    "MessageActionPaymentSentMe": (
        "currency",
        "total_amount",
        "info",
        "shipping_option_id",
        "charge",
        "recurring_init",
        "recurring_used",
        "subscription_until_date",
    ),
    "MessageActionPaymentSent": (
        "currency",
        "total_amount",
        "invoice_slug",
        "subscription_until_date",
        "recurring_init",
        "recurring_used",
    ),
    "MessageActionPhoneCall": ("video", "call_id", "reason", "duration"),
    "MessageActionScreenshotTaken": (),
    "MessageActionCustomAction": ("message",),
    "MessageActionContactSignUp": (),
    "MessageActionGeoProximityReached": ("from_id", "to_id", "distance"),
    "MessageActionGroupCall": ("call", "duration"),
    "MessageActionInviteToGroupCall": ("call", "users"),
    "MessageActionSetMessagesTTL": ("period", "auto_setting_from"),
    "MessageActionGroupCallScheduled": ("call", "schedule_date"),
    "MessageActionSetChatTheme": ("theme",),
    "MessageActionTopicCreate": ("title", "icon_color", "icon_emoji_id", "title_missing"),
    "MessageActionTopicEdit": ("title", "icon_emoji_id", "closed", "hidden"),
    "MessageActionChatJoinedByRequest": (),
    "MessageActionWebViewDataSent": ("text",),
    "MessageActionBoostApply": ("boosts",),
    "MessageActionGiveawayLaunch": ("stars",),
    "MessageActionGiveawayResults": ("winners_count", "unclaimed_count", "stars"),
    "MessageActionGiftPremium": (
        "currency",
        "amount",
        "days",
        "crypto_currency",
        "crypto_amount",
        "message",
    ),
    "MessageActionGiftCode": (
        "days",
        "slug",
        "via_giveaway",
        "unclaimed",
        "boost_peer",
        "currency",
        "amount",
        "crypto_currency",
        "crypto_amount",
        "message",
    ),
    "ReplyKeyboardHide": ("selective",),
    "ReplyKeyboardForceReply": ("single_use", "selective", "placeholder"),
    "ReplyKeyboardMarkup": (
        "resize",
        "single_use",
        "selective",
        "persistent",
        "rows",
        "placeholder",
        "force_reply",
    ),
    "ReplyInlineMarkup": ("rows", "force_reply"),
    "KeyboardButtonRow": ("buttons",),
    "KeyboardButton": ("text", "type", "style"),
    "KeyboardButtonStyle": ("bg_primary", "bg_danger", "bg_success", "icon"),
    "ButtonTypeDefault": (),
    "ButtonTypeRequestGeoLocation": (),
    "ButtonTypeRequestPhone": (),
    "ButtonTypeRequestPoll": ("quiz",),
    "ButtonTypeRequestPeer": ("button_id", "peer_type", "max_quantity"),
    "ButtonTypeSimpleWebView": ("url",),
    "InputGroupCall": ("id",),
    "InputStickerSetID": ("id",),
    "InputStickerSetShortName": ("short_name",),
    "InputStickerSetEmpty": (),
    "MaskCoords": ("n", "x", "y", "zoom"),
    "PhotoCachedSize": ("type", "w", "h"),
    "PhotoStrippedSize": ("type",),
    "PhotoPathSize": ("type",),
}


_PEER_FIELDS = {
    "reply_to_peer_id",
    "from_id",
    "saved_from_peer",
    "saved_from_id",
    "peer",
    "added_by",
    "boost_peer",
}


class _Projection:
    def __init__(self, *, snapshot: bool = False) -> None:
        self.complete = True
        self.snapshot = snapshot

    def value(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if _is_peer(value):
            return _peer(value)
        if isinstance(value, datetime):
            return _utc(value).isoformat()
        if isinstance(value, bytes):
            self.complete = False
            return None
        if type(value).__name__ in {"PollAnswer", "PollAnswerVoters"}:
            result = {"constructor": type(value).__name__}
            option = getattr(value, "option", None)
            if isinstance(option, bytes):
                result["option_hex"] = option.hex()
            for field in _FIELDS[type(value).__name__]:
                if field == "option_hex":
                    continue
                child = getattr(value, field, None)
                projected = self.value(child)
                if projected is not None:
                    result[field] = projected
            return result
        if isinstance(value, (list, tuple)):
            return [result for child in value if (result := self.value(child)) is not None]
        name = type(value).__name__
        allowed = _FIELDS.get(name)
        if allowed is None:
            self.complete = False
            return {"constructor": name}
        if name == "WebPage" and not self.snapshot:
            # The linked page can refresh independently of the Telegram message.
            allowed = ("id", "url")
        result: dict[str, Any] = {"constructor": name}
        for field in allowed:
            try:
                child = getattr(value, field)
            except AttributeError:
                continue
            if name == "MessageReplyHeader" and field == "poll_option" and isinstance(child, bytes):
                result["poll_option_hex"] = child.hex()
                continue
            projected = (
                _peer(child) if field in _PEER_FIELDS and _is_peer(child) else self.value(child)
            )
            if projected is not None:
                result[field] = projected
        return result


def normalize_message(
    message: Any, *, source_account_id: int, chat_id: int, received_at: datetime | None = None
) -> IncomingMessage:
    """Normalize one already received Telethon Message or MessageService offline."""
    if type(message).__name__ not in {"Message", "MessageService"}:
        raise TypeError("message must be a Telethon Message or MessageService")
    projection = _Projection()
    text = getattr(message, "message", None)
    text = text if isinstance(text, str) else ""
    sent_date = getattr(message, "date", None)
    if sent_date is None:
        raise ValueError("Telethon message is missing its source date")
    sent_at = _utc(sent_date)
    received = _utc(received_at or datetime.now(UTC))
    reply = getattr(message, "reply_to", None)
    reply_value = projection.value(reply) if reply is not None else None
    reply_peer = getattr(reply, "reply_to_peer_id", None)
    reply_peer_id = _marked_peer(reply_peer)
    reply_id = getattr(reply, "reply_to_msg_id", None)
    local_reply = None
    topic_id = None
    if type(reply).__name__ == "MessageReplyHeader":
        scheduled = bool(getattr(reply, "reply_to_scheduled", False))
        ephemeral = bool(getattr(reply, "reply_to_ephemeral", False))
        same_peer = reply_peer is None or reply_peer_id == chat_id
        if not scheduled and not ephemeral and same_peer:
            local_reply = reply_id
        if (
            same_peer
            and not scheduled
            and not ephemeral
            and bool(getattr(reply, "forum_topic", False))
        ):
            topic_id = getattr(reply, "reply_to_top_id", None)
            if topic_id is None:
                topic_id = reply_id

    snapshot_projection = _Projection(snapshot=True)
    media = getattr(message, "media", None)
    media_value = projection.value(media) if media is not None else None
    poll_results = (
        snapshot_projection.value(getattr(media, "results", None))
        if type(media).__name__ == "MessageMediaPoll"
        else None
    )

    from_peer = getattr(message, "from_id", None)
    peer = getattr(message, "peer_id", None)
    content = {
        "constructor": type(message).__name__,
        "peer": _peer(peer) if _is_peer(peer) else None,
        "from_id": _peer(from_peer) if _is_peer(from_peer) else None,
        "post_author": getattr(message, "post_author", None),
        "via_bot_id": getattr(message, "via_bot_id", None),
        "out": bool(getattr(message, "out", False)),
        "post": bool(getattr(message, "post", False)),
        "service": type(message).__name__ == "MessageService",
        "grouped_id": getattr(message, "grouped_id", None),
        "from_scheduled": bool(getattr(message, "from_scheduled", False)),
        "entities": projection.value(getattr(message, "entities", None) or []),
        "forward": projection.value(getattr(message, "fwd_from", None)),
        "reply_to": reply_value,
        "media": media_value,
        "action": projection.value(getattr(message, "action", None)),
        "reply_markup": projection.value(getattr(message, "reply_markup", None)),
    }
    snapshot = {
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "replies": snapshot_projection.value(getattr(message, "replies", None)),
        "reactions": snapshot_projection.value(getattr(message, "reactions", None)),
        "reactions_are_possible": getattr(message, "reactions_are_possible", None),
        "poll_results": poll_results,
        "edit_date": _date_value(getattr(message, "edit_date", None)),
        "pinned": bool(getattr(message, "pinned", False)),
        "noforwards": bool(getattr(message, "noforwards", False)),
        "mentioned": bool(getattr(message, "mentioned", False)),
        "media_unread": bool(getattr(message, "media_unread", False)),
    }
    content["projection_complete"] = projection.complete
    snapshot["nested_state"] = _nested_state(
        {"media": media, "reply_to": reply}, snapshot_projection
    )
    snapshot["projection_complete"] = snapshot_projection.complete
    metadata = {"content": content, "snapshot": snapshot}
    return IncomingMessage(
        source="telegram",
        source_account_id=source_account_id,
        chat_id=chat_id,
        message_id=int(message.id),
        sender_id=_marked_peer(from_peer),
        text=text,
        sent_at=sent_at,
        received_at=received,
        reply_to_message_id=local_reply,
        reply_to_peer_id=reply_peer_id,
        topic_id=topic_id,
        metadata_version=METADATA_VERSION,
        metadata_json=json.dumps(
            metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _date_value(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value is not None else None


def _is_peer(value: Any) -> bool:
    return type(value).__name__ in {"PeerUser", "PeerChat", "PeerChannel"}


def _peer(value: Any) -> dict[str, Any]:
    name = type(value).__name__
    raw_id = int(
        value.user_id
        if name == "PeerUser"
        else value.chat_id
        if name == "PeerChat"
        else value.channel_id
    )
    return {
        "type": name.removeprefix("Peer").lower(),
        "id": raw_id,
        "marked_id": utils.get_peer_id(value),
    }


def _marked_peer(value: Any) -> int | None:
    return utils.get_peer_id(value) if _is_peer(value) else None


def _nested_state(value: Any, projection: _Projection, path: str = "") -> list[dict[str, Any]]:
    """Collect changing nested state by following constructor allowlists only."""
    found: list[dict[str, Any]] = []
    if value is None:
        return found
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(_nested_state(child, projection, f"{path}.{key}" if path else key))
        return found
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.extend(_nested_state(child, projection, f"{path}[{index}]"))
        return found
    name = type(value).__name__
    if name in {"PollResults", "WebPage"}:
        found.append({"path": path, "state": projection.value(value)})
    elif name == "Poll":
        found.append(
            {
                "path": path,
                "state": {
                    "constructor": name,
                    "closed": bool(getattr(value, "closed", False)),
                    "close_date": _date_value(getattr(value, "close_date", None)),
                    "hash": getattr(value, "hash", None),
                },
            }
        )
    for field in _FIELDS.get(name, ()):
        try:
            child = getattr(value, field)
        except AttributeError:
            continue
        found.extend(_nested_state(child, projection, f"{path}.{field}" if path else field))
    if name == "MessageMediaPoll":
        found.extend(_nested_state(getattr(value, "results", None), projection, f"{path}.results"))
    return found

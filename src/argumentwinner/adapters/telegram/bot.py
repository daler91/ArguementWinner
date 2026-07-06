"""Telegram wiring: the ONLY module that imports python-telegram-bot, lazily
inside run_telegram_bot (mirroring the desktop adapter) so the package stays
importable without the [telegram] extra.

run_polling is synchronous and owns its event loop — call this function
directly, never inside asyncio.run().
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from argumentwinner.adapters.common import split_message
from argumentwinner.container import App
from argumentwinner.core.models import ConversationRef, Participant, Persona

from . import translate
from .cache import CachedMessage, ChatCache
from .combat import CombatManager, is_deliberate_mention
from .suggestion import (
    PendingSuggestion,
    SuggestionRegistry,
    keyboard_spec,
    new_token,
    parse_callback,
    render_full_text,
    render_picker,
)
from .translate import TELEGRAM_LIMIT

log = logging.getLogger(__name__)

_PERSONAS = "logician | savage | diplomat | socratic"


def _parse_persona(args: list[str] | None) -> Persona | None:
    if not args:
        return None
    value = args[0].lower()
    return Persona(value)  # ValueError handled by callers


def run_telegram_bot(app: App) -> None:
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyParameters
        from telegram.constants import ChatAction
        from telegram.error import Forbidden, TelegramError
        from telegram.ext import (
            ApplicationBuilder,
            CallbackQueryHandler,
            CommandHandler,
            MessageHandler,
            filters,
        )
    except ImportError as exc:
        raise RuntimeError(
            "The Telegram adapter needs the 'telegram' extra: pip install -e '.[telegram]'"
        ) from exc

    token = app.settings.telegram_bot_token
    if token is None:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set — get one from @BotFather and put it "
            "in .env (see .env.example)"
        )
    logging.basicConfig(level=logging.INFO)

    cache = ChatCache(maxlen=app.settings.aw_max_context_turns)
    registry = SuggestionRegistry()
    # Filled in post_init once bot.id/username are known (after initialize()).
    state: dict = {}

    def _markup(spec: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(label, callback_data=data) for label, data in row]
                for row in spec
            ]
        )

    # ─── injected IO (also used by the CombatManager) ──────────────────────────

    async def _notify_typing(ref: ConversationRef) -> None:
        kwargs = {"message_thread_id": int(ref.thread_id)} if ref.thread_id else {}
        try:
            await application.bot.send_chat_action(
                chat_id=int(ref.channel_id), action=ChatAction.TYPING, **kwargs
            )
        except TelegramError:
            pass  # a missing typing indicator must never block a reply

    async def _send_to_ref(
        ref: ConversationRef, text: str, reply_to_id: str | None = None
    ) -> str | None:
        """Chunked send into the origin chat; records the bot's own message
        into the cache (polling never delivers it back to us)."""
        chunks = split_message(text, TELEGRAM_LIMIT)
        if not chunks:
            return None
        # Follow-up chunks need the explicit thread id or they land in the
        # General topic of forum groups.
        thread_kwargs = {"message_thread_id": int(ref.thread_id)} if ref.thread_id else {}
        reply_params = (
            ReplyParameters(message_id=int(reply_to_id), allow_sending_without_reply=True)
            if reply_to_id is not None
            else None
        )
        try:
            first = await application.bot.send_message(
                chat_id=int(ref.channel_id),
                text=chunks[0],
                reply_parameters=reply_params,
                **thread_kwargs,
            )
            for chunk in chunks[1:]:
                await application.bot.send_message(
                    chat_id=int(ref.channel_id), text=chunk, **thread_kwargs
                )
        except TelegramError:
            log.exception("send failed for %s", ref)
            return None
        cache.record(
            ref,
            CachedMessage(
                message_id=str(first.message_id),
                author=state["bot_participant"],
                content=text,
                timestamp=datetime.now(UTC),
                reply_to_id=reply_to_id,
            ),
        )
        return str(first.message_id)

    async def _send_combat_reply(
        ref: ConversationRef, record: CachedMessage, text: str
    ) -> str | None:
        return await _send_to_ref(ref, text, reply_to_id=record.message_id)

    # ─── suggestion mode ───────────────────────────────────────────────────────

    async def _run_suggestion(ref, target: CachedMessage, invoker, persona, origin_msg) -> None:
        beneficiary = translate.to_participant(invoker)
        ctx = translate.build_context(
            ref,
            cache.get(ref),
            target,
            bot_id=state["me_id"],
            beneficiary=beneficiary,
            forced_persona=persona,
            voice=app.voice,  # the user sends/copies these as themselves
        )
        try:
            result = await app.engine.suggest(ctx)
        except Exception:  # noqa: BLE001 — never leave the user hanging
            log.exception("suggest failed")
            await origin_msg.reply_text("Couldn't generate a comeback right now — try again.")
            return

        token = new_token()
        pending = PendingSuggestion(
            token=token,
            result=result,
            ref=ref,
            target=target,
            invoker_id=str(invoker.id),
            forced_persona=persona,
            created_at=datetime.now(UTC),
        )
        registry.put(pending)
        text = render_picker(result)
        keyboard = _markup(keyboard_spec(token, len(result.candidates)))

        # No ephemeral messages on Telegram: DM the picker; fall back in-chat
        # when the invoker never /start-ed the bot.
        try:
            sent = await application.bot.send_message(
                chat_id=invoker.id, text=text, reply_markup=keyboard
            )
            if str(origin_msg.chat.id) != str(invoker.id):
                await origin_msg.reply_text("📬 Sent you the options privately.")
        except Forbidden:
            sent = await origin_msg.reply_text(
                text + "\n\n(I can't DM you — /start me in private for private suggestions.)",
                reply_markup=keyboard,
            )
        registry.bind_message(token, str(sent.chat.id), str(sent.message_id))

    async def _edit_picker(pending: PendingSuggestion, text: str, keyboard=None) -> None:
        if pending.picker_chat_id is None or pending.picker_message_id is None:
            return
        try:
            await application.bot.edit_message_text(
                chat_id=int(pending.picker_chat_id),
                message_id=int(pending.picker_message_id),
                text=text,
                reply_markup=keyboard,
            )
        except TelegramError:
            log.warning("couldn't edit picker %s", pending.token)

    # ─── handlers ──────────────────────────────────────────────────────────────

    async def _argue(update, context) -> None:
        msg = update.effective_message
        if msg is None or msg.from_user is None:
            return
        ref = translate.ref_for_message(msg)
        try:
            persona = _parse_persona(context.args)
        except ValueError:
            await msg.reply_text(f"Unknown persona — use one of: {_PERSONAS}")
            return

        target: CachedMessage | None = None
        if msg.reply_to_message is not None:
            target = translate.to_cached(msg.reply_to_message)
            if target is not None:
                cache.record(ref, target)
        if target is None:
            # Same fallback as Discord /argue: latest cached opponent message.
            invoker_id = str(msg.from_user.id)
            target = next(
                (
                    r
                    for r in reversed(cache.get(ref))
                    if r.author.id != invoker_id and not r.author.is_bot
                ),
                None,
            )
        if target is None:
            await msg.reply_text(
                "Reply to the message you want to beat with /argue "
                "(I can only see messages sent while I'm running)."
            )
            return
        await _run_suggestion(ref, target, msg.from_user, persona, msg)

    async def _on_callback(update, context) -> None:
        query = update.callback_query
        if query is None or query.data is None:
            return
        parsed = parse_callback(query.data)
        if parsed is None:
            await query.answer()
            return
        token, action = parsed
        pending = registry.get(token)
        if pending is None:
            await query.answer("This picker expired — run /argue again.")
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except TelegramError:
                pass
            return
        if str(query.from_user.id) != pending.invoker_id:
            await query.answer("Not your picker 🙂")
            return
        if action == "ft":
            await query.answer()
            await application.bot.send_message(
                chat_id=int(pending.picker_chat_id or pending.invoker_id),
                text=render_full_text(pending.result),
            )
            return
        if pending.working:  # double-click guard — set synchronously below
            await query.answer("Working…")
            return
        pending.working = True
        await query.answer()
        try:
            if action.startswith("s") and action[1:].isdigit():
                index = int(action[1:])
                if index >= len(pending.result.candidates):
                    return
                candidate = pending.result.candidates[index]
                sent_id = await _send_to_ref(
                    pending.ref, candidate.text, reply_to_id=pending.target.message_id
                )
                if sent_id is None:
                    warning = "\n\n⚠️ Couldn't send — am I still in that chat?"
                    await _edit_picker(
                        pending,
                        render_picker(pending.result) + warning,
                        keyboard=_markup(keyboard_spec(token, len(pending.result.candidates))),
                    )
                    return
                registry.pop(token)
                await _edit_picker(pending, f"✅ Sent #{index + 1}.")
            elif action == "rr" or action.startswith("p:"):
                forced = Persona(action[2:]) if action.startswith("p:") else pending.forced_persona
                ctx = translate.build_context(
                    pending.ref,
                    cache.get(pending.ref),
                    pending.target,
                    bot_id=state["me_id"],
                    beneficiary=translate.to_participant(query.from_user),
                    forced_persona=forced,
                    voice=app.voice,
                )
                try:
                    result = await app.engine.suggest(ctx)
                except Exception:  # noqa: BLE001
                    log.exception("reroll failed")
                    await _edit_picker(
                        pending,
                        render_picker(pending.result) + "\n\n⚠️ Reroll failed — try again.",
                        keyboard=_markup(keyboard_spec(token, len(pending.result.candidates))),
                    )
                    return
                pending.result = result
                pending.forced_persona = forced
                await _edit_picker(
                    pending,
                    render_picker(result),
                    keyboard=_markup(keyboard_spec(token, len(result.candidates))),
                )
        finally:
            pending.working = False

    async def _combat_start(update, context) -> None:
        msg = update.effective_message
        if msg is None:
            return
        try:
            persona = _parse_persona(context.args)
        except ValueError:
            await msg.reply_text(f"Unknown persona — use one of: {_PERSONAS}")
            return
        opponent_id = None
        reply_to = msg.reply_to_message
        if reply_to is not None and reply_to.from_user is not None:
            opponent_id = str(reply_to.from_user.id)
        text = await state["manager"].start(
            translate.ref_for_message(msg), persona=persona, opponent_id=opponent_id
        )
        await msg.reply_text(text)

    async def _combat_stop(update, context) -> None:
        msg = update.effective_message
        if msg is None:
            return
        await msg.reply_text(await state["manager"].stop(translate.ref_for_message(msg)))

    async def _on_message(update, context) -> None:
        msg = update.message
        if msg is None:
            return
        record = translate.to_cached(msg)
        if record is None:
            return
        ref = translate.ref_for_message(msg)
        cache.record(ref, record)
        await state["manager"].on_message(
            ref,
            record,
            mentions_bot=is_deliberate_mention(msg.text or msg.caption, state["me_username"]),
            is_proxy=msg.sender_chat is not None or msg.via_bot is not None,
        )

    async def _on_edited(update, context) -> None:
        msg = update.edited_message
        if msg is None:
            return
        cache.update(
            translate.ref_for_message(msg), str(msg.message_id), translate.annotate_content(msg)
        )

    async def _post_init(application) -> None:
        # bot.id / bot.username are only populated after initialize(), so the
        # combat manager and handlers are wired here, before polling starts.
        me = application.bot
        state["me_id"] = str(me.id)
        state["me_username"] = me.username or ""
        state["bot_participant"] = Participant(
            id=str(me.id), display_name=me.username or "ArgumentWinner", is_bot=True
        )
        state["manager"] = CombatManager(
            app,
            cache,
            bot_id=state["me_id"],
            bot_participant=state["bot_participant"],
            send_reply=_send_combat_reply,
            notify_typing=_notify_typing,
        )
        application.add_handler(CommandHandler("argue", _argue))
        application.add_handler(CommandHandler("combat_start", _combat_start))
        application.add_handler(CommandHandler("combat_stop", _combat_stop))
        application.add_handler(CallbackQueryHandler(_on_callback, pattern=r"^aw:"))
        application.add_handler(
            MessageHandler(~filters.COMMAND & filters.UpdateType.MESSAGE, _on_message)
        )
        application.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, _on_edited))
        log.info(
            "telegram bot @%s ready (provider: %s%s)",
            state["me_username"],
            app.provider.name,
            ", voice: on" if app.voice else "",
        )

    application = ApplicationBuilder().token(token.get_secret_value()).post_init(_post_init).build()
    application.run_polling(allowed_updates=["message", "edited_message", "callback_query"])

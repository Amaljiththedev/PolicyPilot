"""Run the Slack bot (Socket Mode).

    python scripts/slack_bot.py

Needs SLACK_BOT_TOKEN (xoxb-) and SLACK_APP_TOKEN (xapp-) in .env. Setup: docs/integrations.md
"""
import os
import sys
import threading

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.integrations.slack_bot import answer_event, feedback_from_reaction, format_reply, record_reply


def handle(client: SocketModeClient, req: SocketModeRequest):
    client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))  # ack within 3 s
    if req.type != "events_api":
        return
    event = req.payload.get("event", {})
    threading.Thread(target=process, args=(client.web_client, event), daemon=True).start()


def process(web: WebClient, event: dict):
    db = SessionLocal()
    try:
        if event.get("type") == "reaction_added":
            feedback_from_reaction(db, event)
            return
        if event.get("type") not in ("app_mention", "message"):
            return
        thread = event.get("thread_ts") or event.get("ts")
        try:
            result = answer_event(db, event)
        except RuntimeError as e:             # LLM down / rate limited
            web.chat_postMessage(channel=event["channel"], thread_ts=thread,
                                 text=f"Sorry, I can't answer right now ({e}). Please try again later.")
            return
        if result is None:
            return
        reply = web.chat_postMessage(channel=event["channel"], thread_ts=thread,
                                     text=format_reply(result), unfurl_links=False)
        record_reply(db, result, event["channel"], reply["ts"])
    except Exception as e:
        print(f"[slack] error: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    s = get_settings()
    if not (s.SLACK_BOT_TOKEN and s.SLACK_APP_TOKEN):
        sys.exit("set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env")
    client = SocketModeClient(app_token=s.SLACK_APP_TOKEN, web_client=WebClient(token=s.SLACK_BOT_TOKEN))
    client.socket_mode_request_listeners.append(handle)
    client.connect()
    print("PolicyPilot Slack bot connected (Socket Mode). Ctrl+C to stop.", flush=True)
    threading.Event().wait()

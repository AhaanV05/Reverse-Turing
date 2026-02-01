"""
/chat/{chat-id}: private chat between the two users.
"""

from fastapi import APIRouter, Request
from config import templates, chatsdb, verify_jwt, usersdb, APIKEY, APIKEY1, IST
from core.prompts import AI_PROMPT, STYLE_PROMPT
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from datetime import datetime, timedelta
import os
import asyncio
import html
import time
import httpx
from pymongo import ReturnDocument
import random

chatrouter = APIRouter(
    prefix="/chat",
)

MAX_MESSAGES_PER_USER = 4
MAX_WORDS_PER_MESSAGE = 30
TURN_TIMEOUT_SECONDS = 60
MAX_OUTPUT_TOKENS = 47
MIN_AI_DELAY_SECONDS = 1.5
MAX_AI_DELAY_SECONDS = 10
AVERAGE_WPM = 50
THINK_MIN_SECONDS = 0.6
THINK_MAX_SECONDS = 2.8
BASE_SCORE = 100
MIN_SCORE_CORRECT = 5
GUESS_GRACE_SECONDS = 10
BOUNTY_MULTIPLIER = 0.25
MAX_SCORE = 120
AI_LOCK_SECONDS = 180
AI_NUDGE_SECONDS = 12

current = APIKEY
def word_count(text: str) -> int:
    return len([w for w in text.strip().split() if w])

def trim_to_word_limit(text: str, limit: int) -> str:
    words = [w for w in text.strip().split() if w]
    if len(words) <= limit:
        return text.strip()
    return " ".join(words[:limit])

def count_role(messages, role: str) -> int:
    return sum(1 for m in messages if m.get("role") == role)

def get_counts(chatdetails):
    messages = chatdetails.get("messages", [])
    if chatdetails.get("user2") == "AI":
        return {
            "user1": count_role(messages, "user"),
            "user2": count_role(messages, "assistant"),
        }
    return {
        "user1": count_role(messages, chatdetails.get("user1")),
        "user2": count_role(messages, chatdetails.get("user2")),
    }

def get_user_counts(chatdetails, username: str):
    counts = get_counts(chatdetails)
    if chatdetails.get("user2") == "AI":
        return counts["user1"], counts["user2"]
    if username == chatdetails.get("user1"):
        return counts["user1"], counts["user2"]
    return counts["user2"], counts["user1"]

def non_dev_message_count(chatdetails) -> int:
    return sum(1 for m in chatdetails.get("messages", []) if m.get("role") != "developer")

def can_guess(chatdetails) -> bool:
    if non_dev_message_count(chatdetails) < 2:
        return False
    counts = get_counts(chatdetails)
    return counts["user1"] >= 1 and counts["user2"] >= 1

async def clear_active_chat(chatdetails):
    chat_id = chatdetails.get("_id")
    if not chat_id:
        return
    users = [chatdetails.get("user1"), chatdetails.get("user2")]
    user_ids = [u for u in users if u and u != "AI"]
    if not user_ids:
        return
    await usersdb.update_many(
        {"_id": {"$in": user_ids}, "active_chat": chat_id},
        {"$unset": {"active_chat": ""}}
    )

def get_last_user_message(messages):
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""

def should_ai_speak(chatdetails):
    msgs = [m for m in chatdetails.get("messages", []) if m.get("role") != "developer"]
    now = datetime.now(IST).timestamp()
    if not msgs:
        return chatdetails.get("first") == "AI", False
    last_role = msgs[-1].get("role")
    last_user_ts = chatdetails.get("last_user_ts", 0)
    last_ai_ts = chatdetails.get("last_ai_ts", 0)
    if last_role == "user" and last_user_ts > last_ai_ts:
        return True, False
    if (not chatdetails.get("ai_nudged")) and last_user_ts > 0 and (now - last_user_ts) > AI_NUDGE_SECONDS:
        return True, True
    return False, False

def build_ai_messages(messages):
    extra = {"role": "developer", "content": AI_PROMPT}
    extra_style = {"role": "developer", "content": STYLE_PROMPT}
    cleaned = [m for m in messages if m.get("role") != "developer"]
    return [extra, extra_style] + cleaned

def get_user_message_stats(chatdetails, username: str):
    messages = chatdetails.get("messages", [])
    if chatdetails.get("user2") == "AI":
        role = "user"
    else:
        role = username
    user_messages = [m for m in messages if m.get("role") == role]
    total_words = sum(word_count(m.get("content", "")) for m in user_messages)
    return len(user_messages), total_words

def time_multiplier(time_taken: float) -> float:
    return max(0.4, 1 - (time_taken / 150))

def message_multiplier(messages_used: int) -> float:
    if messages_used <= 1:
        return 1.0
    if messages_used == 2:
        return 0.85
    if messages_used == 3:
        return 0.65
    return 0.45

def word_multiplier(avg_words: float) -> float:
    return max(0.5, 1 - (avg_words / 40))

def compute_score(chatdetails, username: str) -> int:
    now = datetime.now(IST).timestamp()
    session_start = (
        chatdetails.get("guess_unlock_started")
        or chatdetails.get("session_start")
        or chatdetails.get("time")
        or now
    )
    time_taken = max(0, now - session_start)
    msg_count, total_words = get_user_message_stats(chatdetails, username)
    messages_used = max(1, msg_count)
    avg_words = total_words / messages_used
    score = BASE_SCORE * time_multiplier(time_taken) * message_multiplier(messages_used) * word_multiplier(avg_words)
    score = int(round(score))
    return max(MIN_SCORE_CORRECT, score)

def compute_bounty(base_score: int) -> int:
    if base_score >= MAX_SCORE:
        return 0
    bonus = int(round(base_score * BOUNTY_MULTIPLIER))
    return min(bonus, MAX_SCORE - base_score)

def other_username(chatdetails, username: str):
    if chatdetails.get("user2") == "AI":
        return None
    return chatdetails["user2"] if username == chatdetails["user1"] else chatdetails["user1"]

async def finalize_guess_timeout(chatdetails):
    if chatdetails.get("user2") == "AI":
        return
    if chatdetails.get("guess_timeout_handled"):
        return
    guess_lock_until = chatdetails.get("guess_lock_until")
    if not guess_lock_until:
        return
    if datetime.now(IST).timestamp() <= guess_lock_until:
        return
    guesses = chatdetails.get("guesses", {})
    if len(guesses) != 1:
        return
    first_user = next(iter(guesses.keys()))
    first_guess = guesses[first_user]
    other = other_username(chatdetails, first_user)
    if other:
        await usersdb.update_one(
            {"_id": other},
            {"$addToSet": {"judged": chatdetails["_id"]}}
        )
    if first_guess.get("correct"):
        base = int(first_guess.get("score", 0))
        bonus = compute_bounty(base)
        if bonus > 0:
            await usersdb.update_one(
                {"_id": first_user},
                {"$inc": {"score": bonus}}
            )
        await chatsdb.update_one(
            {"_id": chatdetails["_id"]},
            {
                "$set": {
                    "guesses."+first_user+".bounty": bonus,
                    "guesses."+first_user+".final_score": base + bonus,
                    "guess_timeout_handled": True,
                    "active": False
                }
            }
        )
        await clear_active_chat(chatdetails)
        return
    await chatsdb.update_one(
        {"_id": chatdetails["_id"]},
        {"$set": {"guess_timeout_handled": True, "active": False}}
    )
    await clear_active_chat(chatdetails)
def compute_ai_delay(messages, completion: str) -> float:
    last_user = get_last_user_message(messages)
    input_words = word_count(last_user)
    output_words = word_count(completion)
    base_seconds = (max(input_words, output_words) / AVERAGE_WPM) * 60
    think_seconds = random.uniform(THINK_MIN_SECONDS, THINK_MAX_SECONDS)
    jitter = random.uniform(-1.5, 2.5)
    delay = base_seconds + think_seconds + jitter
    return max(MIN_AI_DELAY_SECONDS, min(MAX_AI_DELAY_SECONDS, delay))

def turn_timed_out(chatdetails) -> bool:
    start = chatdetails.get("turn_started")
    if not start:
        return False
    return (datetime.now(IST).timestamp() - start) > TURN_TIMEOUT_SECONDS

async def get_completion(messages):
    global current
    url = "https://openrouter.ai/api/v1/chat/completions"
    current = (APIKEY1 if current == APIKEY else APIKEY)
    headers = {
        "Authorization": f"Bearer {current}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "meta-llama/llama-3.3-70b-instruct",
        "messages": build_ai_messages(messages),
        "max_tokens": MAX_OUTPUT_TOKENS
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise an exception for HTTP errors
        resp = response.json()
        return resp["choices"][0]["message"]["content"]

async def process_chat(x):
    try:
        should_speak, nudged = should_ai_speak(x)
        if not should_speak:
            return
        messages = x["messages"]
        counts = get_counts(x)
        if turn_timed_out(x):
            await chatsdb.update_one(
                {"_id": x["_id"]},
                {"$set": {"active": False}}
            )
            await clear_active_chat(x)
            return
        should_end = counts["user2"] >= MAX_MESSAGES_PER_USER and counts["user1"] >= MAX_MESSAGES_PER_USER
        if should_end:
            await chatsdb.update_one(
                {"_id": x["_id"]},
                {"$set": {"active": False}}
            )
            await clear_active_chat(x)
            return
        await chatsdb.update_one(
            {"_id": x["_id"]},
            {"$set": {"ai_lock_until": datetime.now(IST) + timedelta(seconds=AI_LOCK_SECONDS)}}
        )
        call_started = time.monotonic()
        completion = await get_completion(messages)
        call_elapsed = time.monotonic() - call_started
        completion = trim_to_word_limit(completion, MAX_WORDS_PER_MESSAGE)
        target_delay = compute_ai_delay(messages, completion)
        remaining = max(0.0, target_delay - call_elapsed)
        if remaining:
            await asyncio.sleep(remaining)
        chat_id = x["_id"]
        new_ai_count = counts["user2"] + 1
        should_end = new_ai_count >= MAX_MESSAGES_PER_USER and counts["user1"] >= MAX_MESSAGES_PER_USER
        first_non_dev = non_dev_message_count(x) == 0
        await chatsdb.update_one(
            {"_id": chat_id},
            {
                "$push": {"messages": {"role": "assistant", "content": completion, "sender": "AI"}},
                "$set": {
                    "first": x["user1"],
                    "active": not should_end,
                    "turn_started": datetime.now(IST).timestamp(),
                    "last_ai_ts": datetime.now(IST).timestamp(),
                    **({"ai_nudged": True} if nudged else {}),
                    **({"session_start": datetime.now(IST).timestamp()} if first_non_dev else {})
                }
            }
        )
        if should_end:
            await clear_active_chat(x)
    except Exception as e:
        print(f"Error processing chat {x['_id']}: {e}")
    finally:
        try:
            await chatsdb.update_one(
                {"_id": x["_id"]},
                {"$unset": {"ai_lock_until": "", "ai_lock_owner": ""}}
            )
        except Exception:
            pass

async def claim_one_chat():
    now = datetime.now(IST)
    lock_until = now + timedelta(seconds=AI_LOCK_SECONDS)
    return await chatsdb.find_one_and_update(
        {
            "active": True,
            "first": "AI",
            "$or": [
                {"ai_lock_until": {"$exists": False}},
                {"ai_lock_until": {"$lt": now}}
            ]
        },
        {
            "$set": {
                "ai_lock_until": lock_until,
                "ai_lock_owner": str(os.getpid())
            }
        },
        return_document=ReturnDocument.AFTER
    )

async def get_completion_loop():
    while True:
        try:
            claimed = []
            for _ in range(200):
                x = await claim_one_chat()
                if not x:
                    break
                claimed.append(x)
            tasks = [asyncio.create_task(process_chat(x)) for x in claimed]
            if tasks:
                await asyncio.gather(*tasks)
            await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Error in loop: {e}")

asyncio.create_task(get_completion_loop())

@chatrouter.get("/{chat_id}", response_class=HTMLResponse)
async def get_chat(request: Request, chat_id: str):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "user":
                chatdetails = await chatsdb.find_one({"_id": chat_id})
                if chatdetails:
                    first = chatdetails.get("first")
                    if not first:
                        await chatsdb.update_one(
                            {"_id": chat_id},
                            {"$set": {"first": data["username"], "turn_started": datetime.now(IST).timestamp()}}
                        )
                    
                        return templates.TemplateResponse(
                            "chatroom.html",
                            {
                                "request": request,
                                "chat_id": chat_id,
                                "username": data["username"],
                                "first": True
                            }
                        )

                    if chatdetails.get("turn_started") is None:
                        await chatsdb.update_one(
                            {"_id": chat_id},
                            {"$set": {"turn_started": datetime.now(IST).timestamp()}}
                        )

                    return templates.TemplateResponse(
                        "chatroom.html",
                        {
                            "request": request,
                            "chat_id": chat_id,
                            "username": data["username"],
                            "first": first == data["username"]
                        }
                    )

                    
    return RedirectResponse("/login")

@chatrouter.get("/{chat_id}/send")
async def send_message(request: Request, chat_id: str, message: str):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "user":
                chatdetails = await chatsdb.find_one({"_id": chat_id})
                if chatdetails:
                    if chatdetails["active"] == False:
                        return JSONResponse({"status": "error", "message": "Chat has been ended."}, status_code=400)
                    if turn_timed_out(chatdetails):
                        await chatsdb.update_one(
                            {"_id": chat_id},
                            {"$set": {"active": False}}
                        )
                        await clear_active_chat(chatdetails)
                        return JSONResponse({"status": "error", "message": "Chat timed out."}, status_code=400)
                    if word_count(message) > MAX_WORDS_PER_MESSAGE:
                        return JSONResponse(
                            {"status": "error", "message": f"Word limit is {MAX_WORDS_PER_MESSAGE} words."},
                            status_code=400
                        )
                    user_count, other_count = get_user_counts(chatdetails, data["username"])
                    if user_count >= MAX_MESSAGES_PER_USER:
                        return JSONResponse(
                            {"status": "error", "message": "Message limit reached."},
                            status_code=400
                        )
                    
                    if chatdetails["user2"] == "AI":
                        new_user_count = user_count + 1
                        should_end = new_user_count >= MAX_MESSAGES_PER_USER and other_count >= MAX_MESSAGES_PER_USER
                        first_non_dev = non_dev_message_count(chatdetails) == 0
                        await chatsdb.update_one(
                            {
                                "_id": chat_id
                            },
                            {
                                "$push": {
                                    "messages": {
                                        "role": "user",
                                        "content": message,
                                        "sender": data["username"]
                                    }
                                },
                                "$set": {
                                    "first": "AI",
                                    "active": not should_end,
                                    "last_user_ts": datetime.now(IST).timestamp(),
                                    "turn_started": datetime.now(IST).timestamp(),
                                    **({"session_start": datetime.now(IST).timestamp()} if first_non_dev else {})
                                }
                            }
                        )
                        if should_end:
                            await clear_active_chat(chatdetails)
                        return JSONResponse({"status": "success"})
                    
                    if data["username"] in chatdetails["user1"]:
                        new_user_count = user_count + 1
                        should_end = new_user_count >= MAX_MESSAGES_PER_USER and other_count >= MAX_MESSAGES_PER_USER
                        first_non_dev = non_dev_message_count(chatdetails) == 0
                        await chatsdb.update_one(
                            {
                                "_id": chat_id
                            },
                            {
                                "$push": {
                                    "messages": {
                                        "role": data["username"],
                                        "content": message,
                                        "sender": data["username"]
                                    }
                                },
                                "$set": {
                                    "active": not should_end,
                                    "turn_started": datetime.now(IST).timestamp(),
                                    **({"session_start": datetime.now(IST).timestamp()} if first_non_dev else {})
                                }
                            }
                        )
                        if should_end:
                            await clear_active_chat(chatdetails)
                        return JSONResponse({"status": "success"})
                    elif data["username"] in chatdetails["user2"]:
                        new_user_count = user_count + 1
                        should_end = new_user_count >= MAX_MESSAGES_PER_USER and other_count >= MAX_MESSAGES_PER_USER
                        first_non_dev = non_dev_message_count(chatdetails) == 0
                        await chatsdb.update_one(
                            {
                                "_id": chat_id
                            },
                            {
                                "$push": {
                                    "messages": {
                                        "role": data["username"],
                                        "content": message,
                                        "sender": data["username"]
                                    }
                                },
                                "$set": {
                                    "active": not should_end,
                                    "turn_started": datetime.now(IST).timestamp(),
                                    **({"session_start": datetime.now(IST).timestamp()} if first_non_dev else {})
                                }
                            }
                        )
                        if should_end:
                            await clear_active_chat(chatdetails)
                        return JSONResponse({"status": "success"})
                        
    return JSONResponse({"status": "error", "message": "Invalid token."}, status_code=401)

@chatrouter.get("/{chat_id}/get")
async def get_message(request: Request, chat_id: str):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "user":
                chatdetails = await chatsdb.find_one({"_id": chat_id})
                if chatdetails:
                    await finalize_guess_timeout(chatdetails)
                    if can_guess(chatdetails) and not chatdetails.get("guess_unlock_started"):
                        now = datetime.now(IST).timestamp()
                        await chatsdb.update_one(
                            {"_id": chat_id, "guess_unlock_started": {"$exists": False}},
                            {"$set": {"guess_unlock_started": now}}
                        )
                        chatdetails["guess_unlock_started"] = now
                    if chatdetails["active"] and turn_timed_out(chatdetails):
                        await chatsdb.update_one(
                            {"_id": chat_id},
                            {"$set": {"active": False}}
                        )
                        chatdetails["active"] = False
                        await clear_active_chat(chatdetails)
                    user_count, other_count = get_user_counts(chatdetails, data["username"])
                    guesses = chatdetails.get("guesses", {})
                    user_has_guessed = data["username"] in guesses
                    guess_lock_until = chatdetails.get("guess_lock_until")
                    guess_expired = False
                    if guess_lock_until and datetime.now(IST).timestamp() > guess_lock_until:
                        guess_expired = True
                        await chatsdb.update_one(
                            {"_id": chat_id},
                            {"$set": {"active": False}}
                        )
                        chatdetails["active"] = False
                        await clear_active_chat(chatdetails)
                    othertemplate = """
<div class="other-div">
    <div class="other-text" style="text-align: left !important;">
        {content}
    </div>
</div>
"""
                    usertemplate = """
<div class="user-div">
    <div class="user-text" style="text-align: right !important;">
        {content}
    </div>
</div>
"""
                    ret = ""
                    is_ai_chat = chatdetails.get("user2") == "AI"
                    for x in chatdetails["messages"]:
                        if x["role"] == "developer":
                            continue
                        sender = x.get("sender")
                        if not sender:
                            if is_ai_chat:
                                sender = data["username"] if x["role"] == "user" else "AI"
                            else:
                                sender = x["role"]
                        safe_content = html.escape(x.get("content", ""))
                        if sender == data["username"]:
                            ret += usertemplate.format(content=safe_content)
                        else:
                            ret += othertemplate.format(content=safe_content)
                    return {
                        "status": "success",
                        "messages": ret,
                        "first": chatdetails["first"],
                        "active": chatdetails["active"],
                        "user_count": user_count,
                        "other_count": other_count,
                        "max_messages": MAX_MESSAGES_PER_USER,
                        "max_words": MAX_WORDS_PER_MESSAGE,
                        "turn_started": chatdetails.get("turn_started"),
                        "turn_timeout": TURN_TIMEOUT_SECONDS,
                        "message_count": non_dev_message_count(chatdetails),
                        "can_guess": can_guess(chatdetails),
                        "guess_lock_until": guess_lock_until,
                        "guess_lock_started": chatdetails.get("guess_lock_started"),
                        "guess_window_seconds": GUESS_GRACE_SECONDS,
                        "user_has_guessed": user_has_guessed,
                        "guess_expired": guess_expired
                    }
                    
    return JSONResponse({"status": "error", "message": "Invalid token."}, status_code=401)

@chatrouter.get("/{chat_id}/end")
async def end_chat(request: Request, chat_id: str):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "user":
                chatdetails = await chatsdb.find_one({"_id": chat_id})
                if chatdetails:
                    if data["username"] in chatdetails["user1"]:
                        await chatsdb.update_one(
                            {
                                "_id": chat_id
                            },
                            {
                                "$set": {
                                    "active": False
                                }
                            }
                        )
                        await clear_active_chat(chatdetails)
                        return {"status": "success"}
                    elif data["username"] in chatdetails["user2"]:
                        await chatsdb.update_one(
                            {
                                "_id": chat_id
                            },
                            {
                                "$set": {
                                    "active": False
                                }
                            }
                        )
                        await clear_active_chat(chatdetails)
                        return {"status": "success"}
    return {"status": "error", "message": "Invalid token."}

@chatrouter.get("/{chat_id}/judgement")
async def routerjudgement(request: Request, chat_id: str, judgement: str):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "user":
                chatdetails = await chatsdb.find_one({"_id": chat_id})
                if chatdetails:
                    userdata = await usersdb.find_one({"_id": data["username"]})
                    if not can_guess(chatdetails):
                        return JSONResponse({"url": "/conclusion?verdict=Wait+for+both+people+to+send+a+message&title=Error"})
                    if chat_id in userdata["judged"]:
                        return JSONResponse({"url": "/dashboard"})
                    guesses = chatdetails.get("guesses", {})
                    if data["username"] in guesses:
                        return JSONResponse({"url": "/dashboard"})
                    is_ai_chat = chatdetails["user2"] == "AI"
                    correct = judgement.upper() == ("AI" if is_ai_chat else "HUMAN")
                    now = datetime.now(IST).timestamp()
                    score = compute_score(chatdetails, data["username"]) if correct else 0

                    if is_ai_chat:
                        await chatsdb.update_one(
                            {"_id": chat_id},
                            {
                                "$set": {
                                    "active": False,
                                    f"guesses.{data['username']}": {
                                        "guess": judgement.upper(),
                                        "correct": correct,
                                        "time": now,
                                        "score": score,
                                        "final_score": score
                                    }
                                }
                            }
                        )
                        await clear_active_chat(chatdetails)
                        update = {"$push": {"judged": chat_id}}
                        if correct:
                            update["$inc"] = {"score": score}
                        await usersdb.update_one({"_id": data["username"]}, update)
                        if chatdetails["user2"] == "AI":
                            verdict = "You+Were+Talking+To+An+AI"
                            title = "Congratulations" if correct else "Oh+No"
                            return JSONResponse({"url": f"/conclusion?verdict={verdict}&title={title}"})

                    guess_lock_until = chatdetails.get("guess_lock_until")
                    if guess_lock_until and now > guess_lock_until:
                        await finalize_guess_timeout(chatdetails)
                        return JSONResponse({"url": "/conclusion?verdict=Guess+window+expired&title=Error"})

                    first_guess = not guess_lock_until
                    update_chat = {
                        f"guesses.{data['username']}": {
                            "guess": judgement.upper(),
                            "correct": correct,
                            "time": now,
                            "score": score,
                            "final_score": score
                        },
                        "active": False
                    }
                    if first_guess:
                        update_chat.update({
                            "guess_lock_until": now + GUESS_GRACE_SECONDS,
                            "guess_lock_started": now
                        })
                    await chatsdb.update_one({"_id": chat_id}, {"$set": update_chat})

                    user_update = {"$push": {"judged": chat_id}}
                    if correct:
                        user_update["$inc"] = {"score": score}
                    await usersdb.update_one({"_id": data["username"]}, user_update)
                    await usersdb.update_one(
                        {"_id": data["username"], "active_chat": chat_id},
                        {"$unset": {"active_chat": ""}}
                    )

                    if not first_guess:
                        other = other_username(chatdetails, data["username"])
                        other_guess = guesses.get(other) if other else None
                        if other_guess:
                            other_correct = other_guess.get("correct", False)
                            if correct != other_correct:
                                winner = data["username"] if correct else other
                                base = score if correct else int(other_guess.get("score", 0))
                                bonus = compute_bounty(base)
                                if bonus > 0 and winner:
                                    await usersdb.update_one({"_id": winner}, {"$inc": {"score": bonus}})
                                if winner:
                                    await chatsdb.update_one(
                                        {"_id": chat_id},
                                        {"$set": {
                                            f"guesses.{winner}.bounty": bonus,
                                            f"guesses.{winner}.final_score": base + bonus,
                                            "guess_timeout_handled": True
                                        }}
                                    )
                            else:
                                await chatsdb.update_one(
                                    {"_id": chat_id},
                                    {"$set": {"guess_timeout_handled": True}}
                                )
                            await clear_active_chat(chatdetails)

                    if chatdetails["user2"] == "AI":
                        verdict = "You+Were+Talking+To+An+AI"
                        title = "Congratulations" if correct else "Oh+No"
                        return JSONResponse({"url": f"/conclusion?verdict={verdict}&title={title}"})
                    verdict = "You+Were+Talking+To+A+Human"
                    title = "Congratulations" if correct else "Oh+No"
                    return JSONResponse({"url": f"/conclusion?verdict={verdict}&title={title}"})
    return {"status": "error", "message": "Invalid token.", "url": "/dashboard"}

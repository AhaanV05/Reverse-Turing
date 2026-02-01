"""
/api/login: handle login system.
/api/admin-login
/api/match-making: match making process initiated.
/api/logout: logout system.
/api/create-user
/api/ban
"""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from config import templates, verify_jwt, chatsdb, generate_jwt, IST, no_username_conflict, usersdb, reportsdb, adminlogsdb
from core.prompts import AI_PROMPT
from datetime import datetime
from secrets import token_urlsafe
from uuid import uuid4
from random import choice, random

apirouter = APIRouter(prefix="/api")
MATCH_LOCK_SECONDS = 15


@apirouter.get("/login", response_class=HTMLResponse)
async def api_login(request: Request, username: str, password: str):
    """
    Now don't get me wrong. I know saving password as it is in the database is a bad idea.
    BUT this is a club event, surely everything should be fine.
    """
    user = await usersdb.find_one({"_id": username, "password": password, "type": "user"})
    if user:
        ret = RedirectResponse(url="/dashboard")
        # set a cookie with the token which never expires
        
        ret.set_cookie("token", user["token"], max_age=31536000)
        return ret
    return RedirectResponse(url="/login")
    
@apirouter.get("/admin-login", response_class=RedirectResponse)
async def api_admin_login(request: Request, username: str, password: str):
    user = await usersdb.find_one({"_id": username, "password": password, "type": "admin"})
    if user:
        ret = RedirectResponse(url="/admin/dashboard")
        ret.set_cookie("token", user["token"])
        return ret
    return RedirectResponse(url="/admin/login")

@apirouter.get("/logout", response_class=RedirectResponse)
async def api_logout(request: Request):
    ret = RedirectResponse(url="/")
    ret.delete_cookie("token")
    return ret

@apirouter.get("/create-user", response_class=JSONResponse)
async def api_create_user(request: Request, username: str, password: str):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "admin":
                e = await no_username_conflict(username)
                if not e:
                    return JSONResponse(
                        {
                            "error": "Username already exists."
                        },
                        status_code=400
                    )
                # hush i know how to use hashlib but i dont want to for testing.
                newuser = {
                    "_id": username,
                    "password": password,
                    "token": generate_jwt(username, "user"),
                    "matchmaking": False,
                    "score": 0,
                    "type": "user",
                    "lastpoint": datetime.now(IST).timestamp(),
                    "banned": False,
                    "previous": "",
                    "judged": [],
                }
                await usersdb.insert_one(newuser)
                try:
                    await adminlogsdb.insert_one({
                        "_id": token_urlsafe(16),
                        "admin": data["username"],
                        "action": f"Created user: {username}",
                        "time": datetime.now(IST).timestamp()
                    })
                except:
                    pass
                return JSONResponse(
                    {
                        "success": "User created successfully."
                    }
                )
    return JSONResponse(
        {
            "error": "Unauthorized access."
        },
        status_code=401
    )
    
@apirouter.get("/ban", response_class=JSONResponse)
async def api_ban(request: Request, username: str):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "admin":
                user = await usersdb.find_one({"_id": username})
                if user:
                    await usersdb.update_one({"_id": username}, {"$set": {"banned": True}})
                    try:
                        await adminlogsdb.insert_one({
                            "_id": token_urlsafe(16),
                            "admin": data["username"],
                            "action": f"Banned user: {username}",
                            "time": datetime.now(IST).timestamp()
                        })
                    except:
                        pass
                    return JSONResponse(
                        {
                            "success": "User banned successfully."
                        }
                    )
                return JSONResponse(
                    {
                        "error": "User not found."
                    },
                    status_code=404
                )
    return JSONResponse(
        {
            "error": "Unauthorized access."
        },
        status_code=401
    )

@apirouter.get("/unban", response_class=JSONResponse)
async def api_unban(request: Request, username: str):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "admin":
                user = await usersdb.find_one({"_id": username})
                if user:
                    await usersdb.update_one({"_id": username}, {"$set": {"banned": False}})
                    try:
                        await adminlogsdb.insert_one({
                            "_id": token_urlsafe(16),
                            "admin": data["username"],
                            "action": f"Unbanned user: {username}",
                            "time": datetime.now(IST).timestamp()
                        })
                    except:
                        pass
                    return JSONResponse(
                        {
                            "success": "User unbanned successfully."
                        }
                    )
                return JSONResponse(
                    {
                        "error": "User not found."
                    },
                    status_code=404
                )
    return JSONResponse(
        {
            "error": "Unauthorized access."
        },
        status_code=401
    )

@apirouter.get("/match-making", response_class=JSONResponse)
async def api_match_making(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "user":
                user = await usersdb.find_one({"_id": data["username"]})
                if user:
                    # Block re-queue if user already has an active chat they haven't judged
                    activeroom = await chatsdb.find_one({"active": True, "$or": [
                            {"user1": data["username"]},
                            {"user2": data["username"]}
                        ]
                    })
                    if activeroom and activeroom["_id"] not in user.get("judged", []):
                        await usersdb.update_one(
                            {"_id": data["username"]},
                            {"$set": {"matchmaking": False, "active_chat": activeroom["_id"]}}
                        )
                        return JSONResponse(
                            {
                                "error": "Already in an active chat."
                            },
                            status_code=400
                        )
                    if user["matchmaking"]:
                        return JSONResponse(
                            {
                                "error": "Already in queue."
                            },
                            status_code=400
                        )
                    if user.get("match_target") not in ("AI", "Human"):
                        await usersdb.update_one(
                            {"_id": data["username"]},
                            {"$set": {"matchmaking": True, "match_target": choice(ai_or_human), "human_attempts": 0, "match_lock_until": datetime.now(IST).timestamp()}}
                        )
                    else:
                        await usersdb.update_one({"_id": data["username"]}, {"$set": {"matchmaking": True, "match_lock_until": datetime.now(IST).timestamp()}})
                    return JSONResponse(
                        {
                            "success": "Added to queue."
                        }
                    )
    return JSONResponse(
        {
            "error": "Unauthorized access."
        },
        status_code=401
    )

ai_or_human = ["AI", "Human"]
@apirouter.get("/match-status", response_class=JSONResponse)
async def api_match_status(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "user":
                user = await usersdb.find_one({"_id": data["username"]})
                if user:
                    # Always check if the user is already in an active chat they haven't judged
                    currentchat1 = await chatsdb.find_one({"user1": user["_id"], "active": True})
                    currentchat2 = await chatsdb.find_one({"user2": user["_id"], "active": True})
                    currentchat = currentchat1 or currentchat2
                    if currentchat and currentchat["_id"] not in user.get("judged", []):
                        await usersdb.update_one(
                            {"_id": data["username"]},
                            {"$set": {"matchmaking": False}}
                        )
                        return JSONResponse({"room": currentchat["_id"]})
                    if user["matchmaking"] == False:
                        return RedirectResponse(url="/dashboard")

                    who = user.get("match_target") or choice(ai_or_human)
                    now_ts = datetime.now(IST).timestamp()
                    lock_until = now_ts + MATCH_LOCK_SECONDS
                    self_lock = await usersdb.update_one(
                        {
                            "_id": data["username"],
                            "$or": [{"match_lock_until": {"$exists": False}}, {"match_lock_until": {"$lt": now_ts}}],
                            "matchmaking": True
                        },
                        {"$set": {"match_lock_until": lock_until}}
                    )
                    if self_lock.modified_count == 0:
                        return JSONResponse({"error": "No match found."}, status_code=404)
                    if who == "AI":
                        # if this works, ima kms
                        currentchat = await chatsdb.find_one({"active": True, "$or": [
                                {"user1": data["username"]},
                                {"user2": data["username"]}
                            ]
                        })
                        if currentchat and currentchat["_id"] not in user.get("judged", []):
                            await usersdb.update_one(
                                {"_id": data["username"]},
                                {"$set": {"matchmaking": False}}
                            )
                            return JSONResponse({"room": currentchat["_id"]})
                        chatid = str(uuid4())
                        ai_first = random() < 0.5
                        await chatsdb.insert_one({
                            "_id": chatid,
                            "messages": [
                                {
                                    "role": "developer",
                                    "content": AI_PROMPT,
                                }
                            ],
                            "user1": data["username"],
                            "user2": "AI",
                            "time": datetime.now(IST).timestamp(),
                            "active": True,
                            "first": ("AI" if ai_first else data["username"]),
                                                        "turn_started": datetime.now(IST).timestamp()
                        })
                        await usersdb.update_one(
                            {"_id": data["username"]},
                            {"$set": {"matchmaking": False, "human_attempts": 0, "active_chat": chatid}, "$unset": {"match_target": ""}}
                        )
                        return JSONResponse({"room": chatid})
                    
                    currentchat = await chatsdb.find_one({"active": True, "$or": [
                            {"user1": data["username"]},
                            {"user2": data["username"]}
                        ]
                    })
                    if currentchat and currentchat["_id"] not in user.get("judged", []):
                        await usersdb.update_one(
                            {"_id": data["username"]},
                            {"$set": {"matchmaking": False}}
                        )
                        return JSONResponse({"room": currentchat["_id"]})
                    # Atomically find and update the first matching user
                    matched_user = await usersdb.find_one_and_update(
                        {
                            "matchmaking": True,
                            "banned": False,
                            "$or": [{"active_chat": {"$exists": False}}, {"active_chat": None}],
                            "$or": [{"match_lock_until": {"$exists": False}}, {"match_lock_until": {"$lt": now_ts}}],
                            "_id": {"$ne": data["username"]}
                        },
                        {"$set": {"matchmaking": False, "human_attempts": 0, "match_lock_until": lock_until}, "$unset": {"match_target": ""}},
                    )

                    if matched_user:
                        existing = await chatsdb.find_one({"active": True, "$or": [
                                {"user1": matched_user["_id"]},
                                {"user2": matched_user["_id"]}
                            ]
                        })
                        if existing:
                            await usersdb.update_one(
                                {"_id": matched_user["_id"]},
                                {"$set": {"matchmaking": False, "active_chat": existing["_id"]}, "$unset": {"match_lock_until": ""}}
                            )
                            await usersdb.update_one(
                                {"_id": data["username"]},
                                {"$unset": {"match_lock_until": ""}}
                            )
                            return JSONResponse({"error": "No match found."}, status_code=404)
                        # Update current user's matchmaking status
                        chatid = str(uuid4())
                        await usersdb.update_one(
                            {"_id": data["username"]},
                            {"$set": {"matchmaking": False, "human_attempts": 0, "active_chat": chatid}, "$unset": {"match_target": "", "match_lock_until": ""}}
                        )
                        await usersdb.update_one(
                            {"_id": matched_user["_id"]},
                            {"$set": {"active_chat": chatid}, "$unset": {"match_lock_until": ""}}
                        )
                        
                        # Create a new chat room
                        await chatsdb.insert_one({
                            "_id": chatid,
                            "messages": [],
                            "user1": data["username"],
                            "user2": matched_user["_id"],
                            "time": datetime.now(IST).timestamp(),
                            "active": True,
                                                    })
                        
                        return JSONResponse({"room": chatid})
                    # If no match found
                    await usersdb.update_one(
                        {"_id": data["username"], "match_lock_until": lock_until},
                        {"$unset": {"match_lock_until": ""}}
                    )
                    attempts = user.get("human_attempts", 0) + 1
                    if attempts >= 3:
                        # fallback to AI after repeated human misses
                        chatid = str(uuid4())
                        ai_first = random() < 0.5
                        await chatsdb.insert_one({
                            "_id": chatid,
                            "messages": [
                                {
                                    "role": "developer",
                                    "content": AI_PROMPT,
                                }
                            ],
                            "user1": data["username"],
                            "user2": "AI",
                            "time": datetime.now(IST).timestamp(),
                            "active": True,
                            "first": ("AI" if ai_first else data["username"]),
                                                        "turn_started": datetime.now(IST).timestamp()
                        })
                        await usersdb.update_one(
                            {"_id": data["username"]},
                            {"$set": {"matchmaking": False, "human_attempts": 0, "active_chat": chatid}, "$unset": {"match_target": "", "match_lock_until": ""}}
                        )
                        return JSONResponse({"room": chatid})
                    await usersdb.update_one(
                        {"_id": data["username"]},
                        {"$set": {"human_attempts": attempts, "match_target": "Human"}, "$unset": {"match_lock_until": ""}}
                    )
                    return JSONResponse({"error": "No match found."}, status_code=404)
    return JSONResponse({"error": "Unauthorized access."}, status_code=401)

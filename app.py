from fastapi import Request, FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from config import templates, verify_jwt, usersdb, chatsdb
from core.admin import adminrouter
from core.api import apirouter
from core.chat import chatrouter

app = FastAPI(
    docs_url=None,
    redoc_url=None,
    title="Reverse Turing",
)
app.include_router(adminrouter)
app.include_router(apirouter)
app.include_router(chatrouter)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "user":
                activeroom = await chatsdb.find_one({"active": True, "$or": [
                        {"user1": data["username"]},
                        {"user2": data["username"]}
                    ]
                })
                if activeroom:
                    user = await usersdb.find_one({"_id": data["username"]})
                    if user and activeroom["_id"] in user.get("judged", []):
                        return RedirectResponse(url="/dashboard")
                    return RedirectResponse(url="/chat/{}".format(activeroom["_id"]))
                return RedirectResponse(url="/dashboard")
            elif data["type"] == "admin":
                return RedirectResponse(url="/admin/dashboard")
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "user":
                activeroom = await chatsdb.find_one({"active": True, "$or": [
                        {"user1": data["username"]},
                        {"user2": data["username"]}
                    ]
                })
                if activeroom:
                    user = await usersdb.find_one({"_id": data["username"]})
                    if user and activeroom["_id"] in user.get("judged", []):
                        return RedirectResponse(url="/leaderboard")
                    return RedirectResponse(url="/chat/{}".format(activeroom["_id"]))
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/conclusion", response_class=HTMLResponse)
async def conclusion(request: Request, verdict: str, title:str):
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "title": title,
            "error_message": verdict,
            "navigate": "dashboard",
            "navigate_url": "/dashboard"
        }
    )  

@app.get("/leaderboard", response_class=HTMLResponse)
async def root_leaderboard(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "user":
                activeroom = await chatsdb.find_one({"active": True, "$or": [
                        {"user1": data["username"]},
                        {"user2": data["username"]}
                    ]
                })
                if activeroom:
                    user = await usersdb.find_one({"_id": data["username"]})
                    if not user or activeroom["_id"] not in user.get("judged", []):
                        return RedirectResponse(url="/chat/{}".format(activeroom["_id"]))
                
            leaderboardtemplate = """
<tr class="{bg} text-center text-neongreen text-lg md:text-xl">
    <td class="py-2">{position}</td>
    <td class="py-2">{username}</td>
    <td class="py-2">{score}</td>
</tr>
"""
            lb = await usersdb.find({"type": "user", "banned": False}).to_list(length=100)
            if not lb:
                return templates.TemplateResponse(
                    "leaderboard.html",
                    {
                        "request": request,
                        "leaderboard": ""
                    }
                )
            # sorting need to be done twice. First for score and then epoch within score.
            # Lower epoch with same score comes first.
            lb = sorted(lb, key=lambda x: x["score"], reverse=True)
            lbfinal = []
            temp = []
            alternativebg = {
                0: "bg-mattblack",
                1: "bg-black"
            }
            maxscore = lb[0]["score"]
            for x in lb:
                if x["score"] == maxscore:
                    temp.append(x)
                else:
                    temp = sorted(temp, key=lambda x: x["lastpoint"])
                    lbfinal.extend(temp)
                    temp = [x]
                    maxscore = x["score"]
            temp = sorted(temp, key=lambda x: x["lastpoint"])
            lbfinal.extend(temp)
            
            ret = ""
            for i, x in enumerate(lbfinal):
                ret += leaderboardtemplate.format(
                    position=i+1,
                    username=x["_id"],
                    score=x["score"],
                    bg=alternativebg[i%2]
                )
            return templates.TemplateResponse(
                "leaderboard.html",
                {
                    "request": request,
                    "leaderboard": ret
                }
            )
    return RedirectResponse(url="/")

@app.get("/rules", response_class=HTMLResponse)
async def rules(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data and data["type"] == "user":
            return templates.TemplateResponse(
                "rules.html",
                {
                    "request": request
                }
            )
    return RedirectResponse(url="/")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "user":
                activeroom = await chatsdb.find_one({"active": True, "$or": [
                        {"user1": data["username"]},
                        {"user2": data["username"]}
                    ]
                })
                if activeroom:
                    user = await usersdb.find_one({"_id": data["username"]})
                    if user and activeroom["_id"] in user.get("judged", []):
                        activeroom = None
                if activeroom:
                    return RedirectResponse(url="/chat/{0}".format(activeroom["_id"]))
                return templates.TemplateResponse(
                    "dashboard.html",
                    {
                        "request": request,
                        "username": data["username"],
                    }
                )
    return RedirectResponse(url="/")

@app.get("/match-making", response_class=HTMLResponse)
async def match_making(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "user":
                activeroom = await chatsdb.find_one({"active": True, "$or": [
                        {"user1": data["username"]},
                        {"user2": data["username"]}
                    ]
                })
                if activeroom:
                    user = await usersdb.find_one({"_id": data["username"]})
                    if user and activeroom["_id"] in user.get("judged", []):
                        activeroom = None
                if activeroom:
                    return RedirectResponse(url="/chat/{}".format(activeroom["_id"]))
                return templates.TemplateResponse(
                    "loading.html",
                    {
                        "request": request,
                        "username": data["username"],
                    }
                )
    return RedirectResponse(url="/")

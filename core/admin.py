"""
/admin/login
/admin/dashboard
/admin/reports
/admin/create-user
/admin/ban
/admin/chat-logs
/admin/chat/{chat_id}
/admin/admin-logs
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from config import usersdb, chatsdb, templates, verify_jwt, reportsdb, adminlogsdb, IST
from datetime import datetime

adminrouter = APIRouter(prefix="/admin", tags=["admin"])

@adminrouter.get("/")
async def admin_root(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "admin":
                return RedirectResponse(url="/admin/dashboard")
    return RedirectResponse(url="/admin/login")

@adminrouter.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@adminrouter.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "admin":
                return templates.TemplateResponse(
                    "admin_dashboard.html",
                    {
                        "request": request,
                        "username": data["username"]
                    }
                )
    return RedirectResponse(url="/admin/login")

@adminrouter.get("/reports", response_class=HTMLResponse)
async def reports(request: Request):
    token = request.cookies.get("token")
    reporttemplate = """
<tr class="border-2 text-white border-adminblue bg-mattblack">
    <td class="report-td">{reportid}</td>
    <td class="report-td">{reportedby}</td>
    <td class="report-td">{reported}</td>
    <td class="report-td">{message}</td>
    <td class="report-td">{time}</td>
</tr>
"""
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "admin":
                reports = await reportsdb.find({}).to_list(length=100)
                reports = sorted(reports, key=lambda x: x["time"], reverse=True)
                ret = ""
                for x in reports:
                    ret += reporttemplate.format(
                        reportid=x["_id"],
                        reportedby=x["reportedby"],
                        reported=x["reported"],
                        message=x["message"],
                        time= datetime.fromtimestamp(x["time"], IST).strftime("%d-%m-%Y %H:%M:%S")
                    )
                return templates.TemplateResponse(
                    "admin_reports.html",
                    {
                        "request": request,
                        "username": data["username"],
                        "reports": ret
                    }
                )
    return RedirectResponse(url="/admin/login")

@adminrouter.get("/create-user", response_class=HTMLResponse)
async def admin_createusers(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "admin":
                return templates.TemplateResponse("admin_create.html", {"request": request})
    return RedirectResponse(url="/admin/login")

@adminrouter.get("/ban", response_class=HTMLResponse)
async def admin_ban(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "admin":
                bantemplate = """
<tr class="border-2 text-white border-adminblue bg-mattblack">
    <td class="report-td">{username}</td>
    <td class="report-td">{score}</td>
    <td class="report-td">
        <button onclick="banUser('{username}');" class="bg-adminblue text-mattblack w-full px-2 py-1 text-xl">BAN</button>
    </td>
</tr>
"""
                bb = await usersdb.find({"type": "user", "banned":False}).to_list(length=1000)
                bb = sorted(bb, key=lambda x: x["score"], reverse=True)
                ret = ""
                for x in bb:
                    ret += bantemplate.format(
                        username=x["_id"],
                        score=x["score"]
                    )
                return templates.TemplateResponse(
                    "admin_manage.html",
                    {
                        "request": request,
                        "banusers": ret
                    }
                )
    return RedirectResponse(url="/admin/login")

@adminrouter.get("/unban", response_class=HTMLResponse)
async def admin_unban(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "admin":
                bantemplate = """
<tr class="border-2 text-white border-adminblue bg-mattblack">
    <td class="report-td">{username}</td>
    <td class="report-td">{score}</td>
    <td class="report-td">
        <button onclick="unbanUser('{username}');" class="bg-adminblue text-mattblack w-full px-2 py-1 text-xl">UNBAN</button>
    </td>
</tr>
"""
                bb = await usersdb.find({"type": "user", "banned":True}).to_list(length=1000)
                bb = sorted(bb, key=lambda x: x["score"], reverse=True)
                ret = ""
                for x in bb:
                    ret += bantemplate.format(
                        username=x["_id"],
                        score=x["score"]
                    )
                return templates.TemplateResponse(
                    "admin_unban.html",
                    {
                        "request": request,
                        "unbanusers": ret
                    }
                )
    return RedirectResponse(url="/admin/login")


@adminrouter.get("/admin-logs", response_class=HTMLResponse)
async def admin_logs(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "admin":
                logtemplate = """
<tr class="border-2 text-white border-adminblue bg-mattblack">
    <td class="report-td">{username}</td>
    <td class="report-td">{action}</td>
</tr>
"""
                logs = await adminlogsdb.find({}).to_list(length=1000)
                logs = sorted(logs, key=lambda x: x["time"], reverse=True)
                ret = ""
                for x in logs:
                    ret += logtemplate.format(
                        username=x["admin"],
                        action=x["action"]
                    )
                return templates.TemplateResponse(
                    "admin_logs.html",
                    {
                        "request": request,
                        "abuselogs": ret
                    }
                )

    return RedirectResponse(url="/admin/login")

@adminrouter.get("/chat-logs", response_class=HTMLResponse)
async def chat_logs(request: Request):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "admin":
                chattemplate = """
<tr class="border-2 text-white border-adminblue bg-mattblack">
    <td class="report-td">{user1}</td>
    <td class="report-td">{user2}</td>
    <td class="report-td">
        <button onclick="window.location.href='/admin/chat/{chat_id}';" class="bg-adminblue text-mattblack w-full px-2 py-1 text-xl">CHATS</button>
    </td>
</tr>
"""
                chats = await chatsdb.find({}).to_list(length=1000)
                ret = ""
                for x in chats:
                    ret += chattemplate.format(
                        user1=x["user1"],
                        user2=x["user2"],
                        chat_id=x["_id"]
                    )
                return templates.TemplateResponse(
                    "admin_chat_log.html",
                    {
                        "request": request,
                        "chats": ret
                    }
                )
    return RedirectResponse(url="/admin/login")

@adminrouter.get("/chat/{chat_id}", response_class=HTMLResponse)
async def chat_logs(request: Request, chat_id: str):
    token = request.cookies.get("token")
    if token:
        data = verify_jwt(token)
        if data:
            if data["type"] == "admin":
                othertemplate = """
<div class="other-div">
    <div class="other-text" style="text-align: right !important;">
        {content}
    </div>
</div>
"""
                usertemplate = """
<div class="user-div">
    <div class="user-text" style="text-align: left !important;">
        {content}
    </div>
</div>
"""
                allchats = await chatsdb.find_one({"_id": chat_id})
                if allchats:
                    ret = ""
                    first = None
                    for x in allchats["messages"]:
                        if x["role"] == "developer":
                            continue
                        if first == None:
                            first = x["role"]
                        if first == x["role"]:
                            ret += usertemplate.format(content=x["content"])
                        else:
                            ret += othertemplate.format(content=x["content"])
                    
                    return templates.TemplateResponse(
                        "admin_chatroom.html",
                        {
                            "request": request,
                            "chathistory": ret,
                            "user1": allchats["user1"],
                            "user2": allchats["user2"]
                        }
                    )
    return RedirectResponse(url="/admin/login")
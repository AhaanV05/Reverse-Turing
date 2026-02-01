import os
import jwt
from dotenv import dotenv_values
import motor.motor_asyncio
from fastapi.templating import Jinja2Templates
import pytz
from datetime import datetime

IST = pytz.timezone("Asia/Kolkata")

env_data = dotenv_values("./creds.env")

def _get_env(key: str) -> str:
    value = os.getenv(key) or env_data.get(key)
    if not value:
        raise KeyError(key)
    return value

mongo_url = _get_env("mongo_url")

client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
turingdb = client["reverse-turing"]
usersdb = turingdb["users"]
chatsdb = turingdb["chats"]
reportsdb = turingdb["reports"]
adminlogsdb = turingdb["adminlogs"]

jwt_secret = _get_env("jwt_secret")
APIKEY = _get_env("APIKEY")
APIKEY1 = _get_env("APIKEY1")

templates = Jinja2Templates(directory="templates")


def verify_jwt(token: str):
    try:
        return jwt.decode(token, jwt_secret, algorithms=["HS256"])
    except:
        return False


def generate_jwt(username: str, type: str) -> str:
    data = {
        "username": username,
        "type": type
    }
    return jwt.encode(data, jwt_secret, algorithm="HS256")


async def no_username_conflict(username: str) -> bool:
    user = await usersdb.find_one({"_id": username})
    if user == None:
        return True
    return False


async def create_admin(username: str, password: str):

    await usersdb.insert_one({
        "_id": username,
        "password": password,
        "token": generate_jwt(username, "admin"),
        "matchmaking": False,
        "score": 0,
        "type": "admin",
        "lastpoint": datetime.now(IST).timestamp(),
        "banned": False,
    })

if __name__ == "__main__":
    import asyncio
    print("""
-----------
config menu
-----------
1. Create Admin.
5. List Admins.

Enter your choice: """, end="")
    choice = int(input())
    if choice == 1:
        username = input("Enter username: ")
        password = input("Enter password: ")
        asyncio.run(create_admin(username, password))

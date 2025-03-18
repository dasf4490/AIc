import discord
import os
import threading
import requests
from flask import Flask
from discord.ext import commands, tasks
from pymongo import MongoClient
from datetime import datetime, timedelta
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()

# Intentsを有効化
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True

# ボットの初期化
bot = commands.Bot(command_prefix="!", intents=intents)

# MongoDB接続設定
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["discord_bot"]
collection = db["deleted_messages"]

# 環境変数からDiscordトークン、ログチャンネルID、Ping用URLを取得
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))
PING_URL = os.getenv("PING_URL")  # Ping用URLを環境変数から取得

# Flaskアプリのセットアップ
app = Flask(__name__)

@app.route("/")
def home():
    return "Ping successful! Bot is running!"

# Flaskサーバーを別スレッドで起動
def run_server():
    port = int(os.environ.get("PORT", 8080))  # RailwayのPORT環境変数を使用
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    server = threading.Thread(target=run_server)
    server.start()

# 自動Ping機能
@tasks.loop(minutes=5)  # 5分ごとにPingを送信
async def send_ping():
    try:
        if PING_URL:  # URLが設定されている場合にPingを送信
            response = requests.get(PING_URL)
            if response.status_code == 200:
                print("Ping sent successfully!")
            else:
                print(f"Ping failed with status code: {response.status_code}")
        else:
            print("PING_URL is not set in environment variables.")
    except Exception as e:
        print(f"Ping failed with error: {e}")

@bot.event
async def on_ready():
    print(f"Bot is now online as {bot.user.name}")
    send_ping.start()  # ボット起動時にPingタスクを開始

@bot.event
async def on_message_delete(message):
    if message.guild:  # サーバー内のメッセージか確認
        author_role_ids = [role.id for role in message.author.roles]

        # 削除メッセージを記録
        if message.content:
            deleted_message = {
                "content": message.content,
                "author": str(message.author),
                "channel_name": message.channel.name,
                "channel_id": message.channel.id,
                "timestamp": datetime.utcnow()
            }
            result = collection.insert_one(deleted_message)
            print(f"削除されたメッセージを記録 (ID: {result.inserted_id})")

            # 埋め込みメッセージでログチャンネルに記録を送信
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                embed = discord.Embed(
                    title="削除されたメッセージ記録",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="内容", value=message.content, inline=False)
                embed.add_field(name="送信者", value=str(message.author), inline=True)
                embed.add_field(name="元のチャンネル", value=message.channel.name, inline=True)
                embed.add_field(name="記録ID", value=str(result.inserted_id), inline=False)
                embed.set_footer(text="削除メッセージ記録")
                await log_channel.send(embed=embed)

@bot.command()
async def 復元(ctx, msg_id: str):
    from bson.objectid import ObjectId
    try:
        msg_data = collection.find_one({"_id": ObjectId(msg_id)})
        if msg_data:
            embed = discord.Embed(
                title="復元されたメッセージ",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="内容", value=msg_data['content'], inline=False)
            embed.add_field(name="送信者", value=msg_data['author'], inline=True)
            embed.add_field(name="元のチャンネル", value=msg_data['channel_name'], inline=True)
            embed.set_footer(text="復元完了")
            await ctx.send(embed=embed)
        else:
            await ctx.send("指定されたIDのメッセージが見つかりません。")
    except Exception as e:
        await ctx.send(f"エラーが発生しました: {str(e)}")

async def delete_old_messages():
    while True:
        threshold_time = datetime.utcnow() - timedelta(hours=24)
        result = collection.delete_many({"timestamp": {"$lt": threshold_time}})
        if result.deleted_count > 0:
            print(f"{result.deleted_count}件の古いメッセージを削除しました。")
        await asyncio.sleep(3600)

# サーバーを起動
keep_alive()

# ボットを起動
bot.run(DISCORD_TOKEN)

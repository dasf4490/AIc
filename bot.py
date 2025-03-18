import discord
import os
import asyncio
from discord.ext import commands
from pymongo import MongoClient, DESCENDING
from datetime import datetime, timedelta
from dotenv import load_dotenv

# .envファイルから環境変数を読み込み
load_dotenv()

bot = commands.Bot(command_prefix="!")

# MongoDB接続設定
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["discord_bot"]  # データベース名
collection = db["deleted_messages"]  # コレクション名

# 環境変数からDiscordトークンとログチャンネルIDを取得
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

@bot.event
async def on_ready():
    print(f"Botが起動しました - {bot.user.name}")
    # 古いデータを削除するタスクを起動
    bot.loop.create_task(delete_old_messages())

@bot.event
async def on_message_delete(message):
    if message.content:
        # 現在時刻をタイムスタンプとして記録
        deleted_message = {
            "content": message.content,
            "author": str(message.author),
            "channel_name": message.channel.name,
            "channel_id": message.channel.id,
            "timestamp": datetime.utcnow()  # UTCで保存
        }
        result = collection.insert_one(deleted_message)
        print(f"削除されたメッセージを記録 (ID: {result.inserted_id})")

        # ログ用チャンネルに削除メッセージの記録を送信
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(
                f"**削除されたメッセージが記録されました**\n"
                f"ID: {result.inserted_id}\n"
                f"内容: {message.content}\n"
                f"送信者: {message.author}\n"
                f"元のチャンネル: {message.channel.name}"
            )

@bot.command()
async def 復元(ctx, msg_id: str):
    from bson.objectid import ObjectId
    try:
        msg_data = collection.find_one({"_id": ObjectId(msg_id)})
        if msg_data:
            await ctx.send(
                f"**復元されたメッセージ**\n"
                f"内容: {msg_data['content']}\n"
                f"送信者: {msg_data['author']}\n"
                f"元のチャンネル: {msg_data['channel_name']}"
            )
        else:
            await ctx.send("指定されたIDのメッセージが見つかりません。")
    except Exception as e:
        await ctx.send(f"エラーが発生しました: {str(e)}")

async def delete_old_messages():
    while True:
        # 24時間前のタイムスタンプを計算
        threshold_time = datetime.utcnow() - timedelta(hours=24)
        # 古いメッセージを削除
        result = collection.delete_many({"timestamp": {"$lt": threshold_time}})
        if result.deleted_count > 0:
            print(f"{result.deleted_count}件の古いメッセージを削除しました。")
        # 1時間ごとにチェック
        await asyncio.sleep(3600)

bot.run(DISCORD_TOKEN)

import discord
import os
import asyncio
from discord.ext import commands
from pymongo import MongoClient
from datetime import datetime, timedelta
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()

# Intentsを有効化
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# MongoDB接続設定
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["discord_bot"]
collection = db["deleted_messages"]

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
            # 埋め込みメッセージで復元内容を送信
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
        # 24時間前のタイムスタンプを計算
        threshold_time = datetime.utcnow() - timedelta(hours=24)
        # 古いメッセージを削除
        result = collection.delete_many({"timestamp": {"$lt": threshold_time}})
        if result.deleted_count > 0:
            print(f"{result.deleted_count}件の古いメッセージを削除しました。")
        # 1時間ごとにチェック
        await asyncio.sleep(3600)

bot.run(DISCORD_TOKEN)

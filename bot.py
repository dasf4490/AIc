import discord
import os
import asyncio
import aiohttp
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
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# MongoDB接続設定
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["discord_bot"]
collection = db["deleted_messages"]

# 環境変数からDiscordトークン、ログチャンネルID、無視するロールIDを取得
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))
AUTOMOD_NOTIFICATION_CHANNEL_ID = int(os.getenv("AUTOMOD_NOTIFICATION_CHANNEL_ID"))

# Webhook URL（AutoMod通知を転送する先のWebhook URLを設定）
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

IGNORED_ROLE_IDS = list(map(int, os.getenv("IGNORED_ROLE_IDS", "").split(',')))

# --------------- 起動メッセージ ---------------
@bot.event
async def on_ready():
    print(f"Botが起動しました - {bot.user.name}")
    bot.loop.create_task(delete_old_messages())

# --------------- 削除メッセージをMongoDBに保存 ---------------
@bot.event
async def on_message_delete(message):
    if message.guild:
        author_role_ids = [role.id for role in message.author.roles]

        if any(role_id in IGNORED_ROLE_IDS for role_id in author_role_ids):
            print(f"無視対象のロールを持つユーザー ({message.author}) が削除したメッセージを記録しません。")
            return

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

# --------------- メッセージ復元コマンド ---------------
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

# --------------- 24時間後に古いメッセージを削除 ---------------
async def delete_old_messages():
    while True:
        threshold_time = datetime.utcnow() - timedelta(hours=24)
        result = collection.delete_many({"timestamp": {"$lt": threshold_time}})
        if result.deleted_count > 0:
            print(f"{result.deleted_count}件の古いメッセージを削除しました。")
        await asyncio.sleep(3600)

# --------------- Webhookに送信する関数 ---------------
async def send_to_webhook(username, avatar_url, content):
    async with aiohttp.ClientSession() as session:
        payload = {
            "username": username,
            "avatar_url": avatar_url,
            "content": content
        }
        async with session.post(WEBHOOK_URL, json=payload) as response:
            if response.status == 204:
                print("Webhook送信成功！")
            else:
                print(f"Webhook送信失敗: {response.status}")

# --------------- AutoMod通知のEmbedを監視 ---------------
@bot.event
async def on_message(message):
    # Botのメッセージは無視
    if message.author.bot:
        return

    # AutoMod通知チャンネルの監視
    if message.channel.id == AUTOMOD_NOTIFICATION_CHANNEL_ID:
        if message.embeds:
            embed = message.embeds[0]

            # 情報取得（送信者名・本文・キーワード等）
            author_name = embed.author.name if embed.author else "不明なユーザー"
            description = embed.description or "（本文なし）"

            fields_text = ""
            for field in embed.fields:
                fields_text += f"{field.name}: {field.value}\n"

            # Webhookで送る内容
            webhook_message = f"🔧 **AutoMod ブロック通知** 🔧\n\n" \
                              f"👤 **送信者**: {author_name}\n" \
                              f"💬 **メッセージ**: {description}\n" \
                              f"{fields_text}"

            # Webhook送信
            await send_to_webhook(username="AutoMod Logger", avatar_url=None, content=webhook_message)

    # コマンドも処理するために必要
    await bot.process_commands(message)

bot.run(DISCORD_TOKEN)

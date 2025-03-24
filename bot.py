import discord
import os
import asyncio
from discord.ext import commands
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from bson import ObjectId

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

# 無視するロールIDを環境変数から取得し、リスト形式に変換
IGNORED_ROLE_IDS = list(map(int, os.getenv("IGNORED_ROLE_IDS", "").split(',')))

# 削除されたメッセージを一時的に保持するリスト
deleted_messages_buffer = []
buffer_lock = asyncio.Lock()

@bot.event
async def on_ready():
    print(f"Botが起動しました - {bot.user.name}")
    # 定期的にログにまとめて送信
    bot.loop.create_task(send_buffered_messages())

@bot.event
async def on_message_delete(message):
    if message.guild:
        author_role_ids = [role.id for role in message.author.roles]

        if any(role_id in IGNORED_ROLE_IDS for role_id in author_role_ids):
            return

    # 削除メッセージを一時的に保持
    if message.content:
        deleted_message = {
            "content": message.content,
            "author": str(message.author),
            "channel_name": message.channel.name,
            "channel_id": message.channel.id,
            "timestamp": datetime.utcnow()
        }
        async with buffer_lock:
            deleted_messages_buffer.append(deleted_message)
        print(f"削除されたメッセージをバッファに追加 (ID: {len(deleted_messages_buffer)})")

@bot.command()
async def 復元(ctx, msg_id: str):
    try:
        # ObjectIdを使用して削除されたメッセージを取得
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

async def send_buffered_messages():
    while True:
        # 1分待機
        await asyncio.sleep(60)
        
        # メッセージをまとめて送信
        if deleted_messages_buffer:
            async with buffer_lock:
                # バッファの内容をコピーして送信
                messages_to_send = list(deleted_messages_buffer)
                deleted_messages_buffer.clear()

            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                # まとめて送信する埋め込みメッセージを作成
                embed = discord.Embed(
                    title="削除されたメッセージのまとめ",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )

                # メッセージ内容をリストとして表示
                for msg in messages_to_send:
                    embed.add_field(
                        name=f"復元用ID: {ObjectId()}",
                        value=f"**内容**: {msg['content']}\n**送信者**: {msg['author']}\n**チャンネル**: {msg['channel_name']}",
                        inline=False
                    )

                embed.set_footer(text="削除メッセージ記録")
                await log_channel.send(embed=embed)
                print(f"まとめて削除メッセージを送信しました。")

bot.run(DISCORD_TOKEN)

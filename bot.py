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
intents.guilds = True  # ロール情報にアクセス可能にする

bot = commands.Bot(command_prefix="!", intents=intents)

# MongoDB接続設定
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["discord_bot"]
collection = db["deleted_messages"]

# 環境変数からDiscordトークン、ログチャンネルID、無視するロールIDを取得
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))
AUTOMOD_LOG_CHANNEL_ID = int(os.getenv("AUTOMOD_LOG_CHANNEL_ID"))  # AutoMod通知専用チャンネルIDを取得

# 無視するロールIDを環境変数から取得し、リスト形式に変換
IGNORED_ROLE_IDS = list(map(int, os.getenv("IGNORED_ROLE_IDS", "").split(',')))

@bot.event
async def on_ready():
    print(f"Botが起動しました - {bot.user.name}")
    # 古いデータを削除するタスクを起動
    bot.loop.create_task(delete_old_messages())

@bot.event
async def on_message_delete(message):
    if message.guild:  # サーバー内のメッセージか確認
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

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # AutoMod通知専用チャンネルでのみ処理
    if message.channel.id == AUTOMOD_LOG_CHANNEL_ID:
        print(f"AutoModレポートを検出: {message.content}")

        target_channel_name = None
        if message.content:
            parts = message.content.split('でメッセージをブロックしました')
            if parts:
                target_channel_name = parts[0].strip()

        blocked_message_content = None
        user = None
        keyword = None
        rule = None

        if message.embeds:
            embed = message.embeds[0]
            embed_dict = embed.to_dict()  # 必要に応じてprintで確認してもOK！

            user = embed.author.name if embed.author else "不明"
            blocked_message_content = embed.description

            for field in embed.fields:
                if "キーワード" in field.name:
                    keyword = field.value
                elif "ルール" in field.name:
                    rule = field.value

        if blocked_message_content:
            blocked_record = {
                "content": blocked_message_content,
                "author": user or "不明",
                "channel_name": target_channel_name or "不明",
                "channel_id": message.channel.id,
                "keyword": keyword,
                "rule": rule,
                "timestamp": datetime.utcnow(),
                "automod": True
            }
            result = collection.insert_one(blocked_record)
            print(f"AutoModブロック記録 (ID: {result.inserted_id})")

            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                embed = discord.Embed(
                    title="AutoModブロックメッセージ記録",
                    color=discord.Color.orange(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="内容", value=blocked_message_content, inline=False)
                embed.add_field(name="送信者", value=user or "不明", inline=True)
                embed.add_field(name="元のチャンネル", value=target_channel_name or "不明", inline=True)
                if keyword:
                    embed.add_field(name="キーワード", value=keyword, inline=True)
                if rule:
                    embed.add_field(name="ルール", value=rule, inline=True)
                embed.add_field(name="記録ID", value=str(result.inserted_id), inline=False)
                embed.set_footer(text="AutoModブロックメッセージ記録")
                await log_channel.send(embed=embed)

    await bot.process_commands(message)

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

bot.run(DISCORD_TOKEN)

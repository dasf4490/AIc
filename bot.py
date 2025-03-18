import discord
import os
import asyncio
from discord.ext import commands
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from bson import ObjectId  # ObjectIdのインポート

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

# 無視するロールIDを環境変数から取得し、リスト形式に変換
IGNORED_ROLE_IDS = list(map(int, os.getenv("IGNORED_ROLE_IDS", "").split(',')))

# AutoMod通知を監視するためのチャンネルID（環境変数）
AUTOMOD_NOTIFICATION_CHANNEL_ID = int(os.getenv("AUTOMOD_NOTIFICATION_CHANNEL_ID"))

@bot.event
async def on_ready():
    print(f"Botが起動しました - {bot.user.name}")
    # 古いデータを削除するタスクを起動
    bot.loop.create_task(delete_old_messages())

@bot.event
async def on_message_delete(message):
    if message.guild:  # サーバー内のメッセージか確認
        # メッセージ送信者のロールIDを取得
        author_role_ids = [role.id for role in message.author.roles]

        # 無視するロールIDを持っている場合、記録しない
        if any(role_id in IGNORED_ROLE_IDS for role_id in author_role_ids):
            print(f"無視対象のロールを持つユーザー ({message.author}) が削除したメッセージを記録しません。")
            return

    # 削除メッセージを記録
    if message.content:
        deleted_message = {
            "content": message.content,
            "author": str(message.author),
            "channel_name": message.channel.name,
            "channel_id": message.channel.id,
            "timestamp": datetime.datetime.now(timezone.utc)  # UTCのタイムゾーンを使用
        }
        result = collection.insert_one(deleted_message)
        print(f"削除されたメッセージを記録 (ID: {result.inserted_id})")

        # 埋め込みメッセージでログチャンネルに記録を送信
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="削除されたメッセージ記録",
                color=discord.Color.red(),
                timestamp=datetime.datetime.now(timezone.utc)  # UTCのタイムゾーンを使用
            )
            embed.add_field(name="内容", value=message.content, inline=False)
            embed.add_field(name="送信者", value=str(message.author), inline=True)
            embed.add_field(name="元のチャンネル", value=message.channel.name, inline=True)
            embed.add_field(name="記録ID", value=str(result.inserted_id), inline=False)
            embed.set_footer(text="削除メッセージ記録")
            await log_channel.send(embed=embed)

@bot.command()
async def 復元(ctx, msg_id: str):
    try:
        # 通常のメッセージはObjectIdで検索
        msg_data = collection.find_one({"_id": ObjectId(msg_id)})
        if msg_data:
            embed = discord.Embed(
                title="復元されたメッセージ",
                color=discord.Color.green(),
                timestamp=datetime.datetime.now(timezone.utc)  # UTCのタイムゾーンを使用
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

@bot.command()
async def automod_復元(ctx, decision_id: str):
    try:
        # AutoModの通知もObjectIdとして保存された場合、ObjectIdで検索
        msg_data = collection.find_one({"decision_id": ObjectId(decision_id)})
        if msg_data:
            # AutoModの内容だけを復元
            embed = discord.Embed(
                title="AutoMod復元されたメッセージ",
                color=discord.Color.green(),
                timestamp=datetime.datetime.now(timezone.utc)  # UTCのタイムゾーンを使用
            )
            embed.add_field(name="メッセージ内容", value=msg_data['description'], inline=False)
            embed.set_footer(text="AutoMod復元完了")
            await ctx.send(embed=embed)
        else:
            await ctx.send("指定されたIDのAutoModメッセージが見つかりません。")
    except Exception as e:
        await ctx.send(f"エラーが発生しました: {str(e)}")

async def delete_old_messages():
    while True:
        threshold_time = datetime.datetime.now(timezone.utc) - timedelta(hours=24)
        result = collection.delete_many({"timestamp": {"$lt": threshold_time}})
        if result.deleted_count > 0:
            print(f"{result.deleted_count}件の古いメッセージを削除しました。")
        await asyncio.sleep(3600)

@bot.event
async def on_message(message):
    # Botのメッセージは無視
    if message.author.bot:
        return

    # AutoMod通知チャンネルの監視
    if message.channel.id == AUTOMOD_NOTIFICATION_CHANNEL_ID:
        if message.embeds:
            embed = message.embeds[0]

            # 送信者名（AutoModの場合は不明な場合もある）
            author_name = embed.author.name if embed.author else "不明なユーザー"
            description = embed.description or "（本文なし）"

            # Embedフィールドから必要な情報を取り出し
            fields_text = ""
            for field in embed.fields:
                fields_text += f"{field.name}: {field.value}\n"

            # Decision ID（AutoModによるアクションを識別するため）
            decision_id = embed.fields[0].value  # 必要に応じて正しい位置を取得

            # MongoDBに保存（AutoModの通知も保存）
            automod_notification = {
                "author_name": author_name,
                "description": description,
                "fields_text": fields_text,
                "decision_id": ObjectId(),  # ObjectIdとして保存
                "timestamp": datetime.datetime.now(timezone.utc)  # UTCのタイムゾーンを使用
            }
            result = collection.insert_one(automod_notification)
            print(f"AutoMod通知をログに記録 (ID: {result.inserted_id})")

            # AutoMod通知をログチャンネルに送信
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                embed_log = discord.Embed(
                    title="AutoModによるメッセージ削除",
                    color=discord.Color.orange(),
                    timestamp=datetime.datetime.now(timezone.utc)  # UTCのタイムゾーンを使用
                )
                embed_log.add_field(name="送信者", value=author_name, inline=True)
                embed_log.add_field(name="メッセージ内容", value=description, inline=False)
                embed_log.add_field(name="詳細", value=fields_text, inline=False)
                embed_log.add_field(name="Decision ID", value=decision_id, inline=False)
                embed_log.set_footer(text="AutoMod通知")
                await log_channel.send(embed=embed_log)

    # コマンドも処理するために必要
    await bot.process_commands(message)

bot.run(DISCORD_TOKEN)

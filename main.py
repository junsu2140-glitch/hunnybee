import threading
import asyncio
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv() # .env 파일 읽기
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

# ---------------------------------------------------------
# 1. 가짜 웹 서버 (Render 절전 모드 방지용)
# ---------------------------------------------------------
app = Flask('')

@app.route('/')
def home():
    return "🐝 꿀벌 봇이 정상적으로 깨어있습니다!"

def run_web_server():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run_web_server)
    t.daemon = True
    t.start()

# ---------------------------------------------------------
# 2. 디스코드 봇 설정
# ---------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("🐝 꿀벌 봇 슬래시 명령어 동기화 완료!")

bot = MyBot()

# ---------------------------------------------------------
# 💾 서버 설정 파일 관리 (JSON 영구 저장)
# ---------------------------------------------------------
CONFIG_FILE = "server_config.json"

def load_configs():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_configs(data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"설정 저장 중 에러 발생: {e}")

saved_configs = load_configs()

# ---------------------------------------------------------
# 🌐 런타임 서버별 상태 관리 딕셔너리
# ---------------------------------------------------------
server_runtime = {}

def get_server_runtime(guild_id_str):
    if guild_id_str not in server_runtime:
        server_runtime[guild_id_str] = {
            "mention_msg": None,
            "embed_msg": None,
            "task": None
        }
    return server_runtime[guild_id_str]

# ---------------------------------------------------------
# 🐝 특정 서버의 15분 뒤 알림을 보내는 핵심 함수
# ---------------------------------------------------------
async def schedule_next_harvest(guild_id: int):
    guild_id_str = str(guild_id)
    runtime = get_server_runtime(guild_id_str)

    # 15분 대기 (15분 = 900초)
    await asyncio.sleep(900)

    if guild_id_str not in saved_configs or saved_configs[guild_id_str].get("channel_id") is None:
        return

    channel_id = saved_configs[guild_id_str]["channel_id"]
    channel = bot.get_channel(channel_id)
    
    if channel:
        # 🛡️ [429 에러 방지 안전장치 1]
        # 무작위 채널 스캔이나 전체 삭제를 하지 않고,
        # 정확히 추적되고 있는 이전 멘션 메시지만 1번 안전하게 삭제하여 API 요청 폭발을 막습니다.
        if runtime["mention_msg"]:
            try: await runtime["mention_msg"].delete()
            except: pass
            runtime["mention_msg"] = None

        if runtime["embed_msg"]:
            try: await runtime["embed_msg"].delete()
            except: pass
            runtime["embed_msg"] = None

        role_id = saved_configs[guild_id_str].get("role_id")
        mention_text = f"<@&{role_id}>" if role_id else "@everyone"

        # [1] 🔔 멘션 전용 메시지 전송 (알림음용)
        runtime["mention_msg"] = await channel.send(content=f"🔔 {mention_text} 벌들이 꿀을 가득 모아왔어요!")

        # [2] 🐝 채집 완료 버튼이 포함된 임베드 메시지 전송
        embed = discord.Embed(
            title="🐝 위잉위잉! 벌들이 꿀을 듬뿍 찾아왔어요!",
            description=(
                "🍯 **15분 동안 열심히 모은 꿀통이 꽉 차서 꿀이 넘치고 있습니다!**\n\n"
                "어서 아래 **[🍯 채집 완료!]** 버튼을 눌러 꿀을 수확해 주세요.\n"
                "수확을 완료하면 벌들이 다시 꿀을 모으기 시작합니다! 🌸"
            ),
            color=0xFFD700
        )
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3413/3413307.png")
        embed.set_footer(text="🐝 수확을 기다리는 중...")

        runtime["embed_msg"] = await channel.send(embed=embed, view=HoneyHarvestView())

# ---------------------------------------------------------
# 채집 완료 버튼 UI (서버별 독립 제어)
# ---------------------------------------------------------
class HoneyHarvestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🍯 채집 완료!", style=discord.ButtonStyle.green, custom_id="honey_harvest_btn_clean")
    async def harvest_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        guild_id_str = str(guild_id)
        runtime = get_server_runtime(guild_id_str)

        # 🛡️ [429 에러 방지 안전장치 2]
        # 유저가 버튼을 연타하더라도 이미 삭제된 메시지라면 재요청하지 않고 안전하게 예외 처리합니다.
        if runtime["mention_msg"]:
            try:
                await runtime["mention_msg"].delete()
            except Exception:
                pass
            runtime["mention_msg"] = None

        # 버튼 누른 유저에게 조용히 팝업 피드백 전달 (채팅 API 대신 interaction 응답 활용으로 부하 감소)
        await interaction.response.defer()

        # 임베드 메시지는 지우지 않고 수정(edit)만 하여 API 호출 횟수를 최소화합니다.
        button.disabled = True
        button.label = "🐝 꿀 모으는 중..."

        now = datetime.now(ZoneInfo("Asia/Seoul"))
        finish_time = now + timedelta(minutes=15)
        time_str = finish_time.strftime('%H시 %M분')

        working_embed = discord.Embed(
            title="🐝 벌들이 꿀을 모으기 시작했습니다!",
            description=(
                f"**{interaction.user.display_name}** 님이 꿀 수확을 완료했습니다!\n\n"
                "🌸 **벌들이 다시 들판으로 나가 열심히 꿀을 모으고 있습니다...**\n"
                f"⏱️ 예상 수확 시각: 약 **{time_str}** 경 (KST)"
            ),
            color=0xFFD700
        )
        working_embed.set_footer(text="⏱️ 15분 타이머 작동 중...")

        try:
            await interaction.message.edit(embed=working_embed, view=self)
        except Exception:
            pass

        # 🛡️ [429 에러 방지 안전장치 3]
        # 기존에 돌고 있던 타이머 태스크가 중복으로 쌓이지 않도록,
        # 새로운 타이머를 만들기 전에 기존 태스크를 반드시 취소(cancel)하여 스팸 누적을 방지합니다.
        if runtime["task"] and not runtime["task"].done():
            runtime["task"].cancel()
        
        runtime["task"] = asyncio.create_task(schedule_next_harvest(guild_id))

# ---------------------------------------------------------
# 슬래시 명령어 (서버별 독립 설정 및 파일 저장)
# ---------------------------------------------------------

@bot.tree.command(name="채널설정", description="벌들이 꿀 알림을 보낼 채널을 지정합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def set_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    guild_id_str = str(interaction.guild.id)
    
    if guild_id_str not in saved_configs:
        saved_configs[guild_id_str] = {"channel_id": None, "role_id": None}
    
    saved_configs[guild_id_str]["channel_id"] = channel.id
    save_configs(saved_configs) # JSON 파일에 즉시 저장
    
    await interaction.response.send_message(f"🍯 꿀 알림 채널이 {channel.mention}(으)로 설정되었습니다. (설정 저장됨)", ephemeral=True)

@bot.tree.command(name="역할설정", description="알림 시 멘션할 역할(양봉업자)을 지정합니다. (비워두면 @everyone)")
@app_commands.checks.has_permissions(administrator=True)
async def set_role(interaction: discord.Interaction, role: discord.Role = None):
    guild_id_str = str(interaction.guild.id)
    
    if guild_id_str not in saved_configs:
        saved_configs[guild_id_str] = {"channel_id": None, "role_id": None}

    if role is None:
        saved_configs[guild_id_str]["role_id"] = None
        save_configs(saved_configs)
        await interaction.response.send_message("🍯 멘션 대상이 **@everyone**으로 설정되었습니다. (설정 저장됨)", ephemeral=True)
    else:
        saved_configs[guild_id_str]["role_id"] = role.id
        save_configs(saved_configs)
        await interaction.response.send_message(f"🍯 멘션 대상이 {role.mention}(으)로 설정되었습니다. (설정 저장됨)", ephemeral=True)

@bot.tree.command(name="타이머시작", description="벌들을 들판으로 보내 15분 꿀 모으기 타이머를 시작합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def start_timer(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    guild_id_str = str(guild_id)
    runtime = get_server_runtime(guild_id_str)

    if guild_id_str not in saved_configs or saved_configs[guild_id_str].get("channel_id") is None:
        await interaction.response.send_message("⚠️ 먼저 `/채널설정` 명령어로 꿀 알림을 받을 채널을 선택해 주세요.", ephemeral=True)
        return

    now = datetime.now(ZoneInfo("Asia/Seoul"))
    finish_time = now + timedelta(minutes=15)
    time_str = finish_time.strftime('%H시 %M분')

    status_embed = discord.Embed(
        title="🐝 벌들이 꿀을 모으기 시작했습니다!",
        description=f"🌸 **벌들이 들판으로 나가 열심히 꿀을 모으고 있습니다...**\n⏱️ 예상 수확 시각: 약 **{time_str}** 경 (KST)",
        color=0xFFD700
    )
    status_embed.set_footer(text="⏱️ 15분 타이머 작동 중...")

    if runtime["mention_msg"]:
        try: await runtime["mention_msg"].delete()
        except: pass
        runtime["mention_msg"] = None

    # 🛡️ [429 에러 방지 안전장치 3 (명령어 버전)]
    # 수동으로 `/타이머시작`을 다시 누를 때도 기존 태스크가 겹치지 않게 취소합니다.
    if runtime["task"] and not runtime["task"].done():
        runtime["task"].cancel()
    
    runtime["task"] = asyncio.create_task(schedule_next_harvest(guild_id))
    
    await interaction.response.send_message(embed=status_embed, ephemeral=True)

@bot.tree.command(name="타이머중지", description="벌들의 꿀 모으기를 중지하고 쉬게 합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def stop_timer(interaction: discord.Interaction):
    guild_id_str = str(interaction.guild.id)
    runtime = get_server_runtime(guild_id_str)
    
    if runtime["task"] and not runtime["task"].done():
        runtime["task"].cancel()
        await interaction.response.send_message("🛑 이 서버의 벌들이 꿀 모으기를 멈추고 벌집으로 돌아왔습니다.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ 현재 이 서버에서 실행 중인 타이머가 없습니다.", ephemeral=True)

# ---------------------------------------------------------
# 프로그램 실행 진입점
# ---------------------------------------------------------
if __name__ == '__main__':
    keep_alive()
    bot.run(TOKEN)

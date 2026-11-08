import threading
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv
import asyncio
from datetime import datetime, timedelta
from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands

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

# 설정 및 상태 관리 변수
target_channel_id = None
target_role_id = None          # None이면 @everyone
current_mention_message = None # 🔔 멘션 알림 메시지 객체
current_embed_message = None   # 🐝 임베드 메시지 객체
timer_task = None              # 현재 진행 중인 대기 작업(Task)

# ---------------------------------------------------------
# 🐝 15분 뒤 알림을 보내는 핵심 함수 (시간 라이브러리 활용)
# ---------------------------------------------------------
async def schedule_next_harvest():
    global current_mention_message, current_embed_message, timer_task

    # 15분 대기 (15분 = 900초)
    # 테스트하고 싶으실 때는 900 대신 10초(10) 등으로 줄여서 테스트해 보실 수 있습니다!
    await asyncio.sleep(900)

    if target_channel_id is None:
        return

    channel = bot.get_channel(target_channel_id)
    if channel:
        # 혹시 남아있는 이전 메시지들 청소
        if current_mention_message:
            try: await current_mention_message.delete()
            except: pass
            current_mention_message = None

        if current_embed_message:
            try: await current_embed_message.delete()
            except: pass
            current_embed_message = None

        mention_text = f"<@&{target_role_id}>" if target_role_id else "@everyone"

        # [1] 🔔 멘션 전용 메시지 전송 (알림음용)
        current_mention_message = await channel.send(content=f"🔔 {mention_text} 벌들이 꿀을 가득 모아왔어요!")

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

        current_embed_message = await channel.send(embed=embed, view=HoneyHarvestView())

# ---------------------------------------------------------
# 채집 완료 버튼 UI (View 클래스 내부에서 시간 제어)
# ---------------------------------------------------------
class HoneyHarvestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🍯 채집 완료!", style=discord.ButtonStyle.green, custom_id="honey_harvest_btn")
    async def harvest_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        global current_mention_message, timer_task

        # 1. 🔔 멘션 알림 메시지만 쏙 골라서 삭제
        if current_mention_message:
            try:
                await current_mention_message.delete()
            except Exception:
                pass
            current_mention_message = None

        # 2. 버튼 누른 유저에게 조용히 팝업 피드백 전달
        await interaction.response.send_message(
            f"🐝 {interaction.user.display_name}님이 꿀을 수확했습니다! 벌들이 다시 꿀을 모으러 출동합니다.",
            ephemeral=True
        )

        # 3. 임베드 메시지는 지우지 않고 "꿀 모으는 중..." 상태로 수정 & 버튼 비활성화
        button.disabled = True
        button.label = "🐝 꿀 모으는 중..."

        # datetime 라이브러리로 현재 수확 완료된 시각 기록
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        finish_time = now + timedelta(minutes=15)
        time_str = finish_time.strftime('%H시 %M분')

        working_embed = discord.Embed(
            title="🐝 벌들이 꿀을 모으기 시작했습니다!",
            description=(
                f"**{interaction.user.display_name}** 님이 꿀 수확을 완료했습니다!\n\n"
                "🌸 **벌들이 다시 들판으로 나가 열심히 꿀을 모으고 있습니다...**\n"
                f"⏱️ 예상 수확 시각: 약 **{time_str}** 경"
            ),
            color=0xFFD700  # 노란색
        )
        working_embed.set_footer(text="⏱️ 15분 타이머 작동 중...")

        try:
            await interaction.message.edit(embed=working_embed, view=self)
        except Exception:
            pass

        # 4. 기존에 돌고 있던 타이머가 있다면 취소하고 새로 15분 대기 시작!
        if timer_task and not timer_task.done():
            timer_task.cancel()
        
        timer_task = asyncio.create_task(schedule_next_harvest())

# ---------------------------------------------------------
# 슬래시 명령어
# ---------------------------------------------------------

@bot.tree.command(name="채널설정", description="벌들이 꿀 알림을 보낼 채널을 지정합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def set_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    global target_channel_id
    target_channel_id = channel.id
    await interaction.response.send_message(f"🍯 꿀 알림 채널이 {channel.mention}(으)로 설정되었습니다.", ephemeral=True)

@bot.tree.command(name="역할설정", description="알림 시 멘션할 역할(양봉업자)을 지정합니다. (비워두면 @everyone)")
@app_commands.checks.has_permissions(administrator=True)
async def set_role(interaction: discord.Interaction, role: discord.Role = None):
    global target_role_id
    if role is None:
        target_role_id = None
        await interaction.response.send_message("🍯 멘션 대상이 **@everyone**으로 설정되었습니다.", ephemeral=True)
    else:
        target_role_id = role.id
        await interaction.response.send_message(f"🍯 멘션 대상이 {role.mention}(으)로 설정되었습니다.", ephemeral=True)

@bot.tree.command(name="타이머시작", description="벌들을 들판으로 보내 15분 꿀 모으기 타이머를 시작합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def start_timer(interaction: discord.Interaction):
    global current_mention_message, timer_task
    if target_channel_id is None:
        await interaction.response.send_message("⚠️ 먼저 `/채널설정` 명령어로 꿀 알림을 받을 채널을 선택해 주세요.", ephemeral=True)
        return

    now = datetime.now(ZoneInfo("Asia/Seoul"))
    finish_time = now + timedelta(minutes=15)
    time_str = finish_time.strftime('%H시 %M분')

    status_embed = discord.Embed(
        title="🐝 벌들이 꿀을 모으기 시작했습니다!",
        description=f"🌸 **벌들이 들판으로 나가 열심히 꿀을 모으고 있습니다...**\n⏱️ 예상 수확 시각: 약 **{time_str}** 경",
        color=0xFFD700
    )
    status_embed.set_footer(text="⏱️ 15분 타이머 작동 중...")

    if current_mention_message:
        try: await current_mention_message.delete()
        except: pass
        current_mention_message = None

    # 기존 타이머 취소 후 새로 시작
    if timer_task and not timer_task.done():
        timer_task.cancel()
    
    timer_task = asyncio.create_task(schedule_next_harvest())
    
    await interaction.response.send_message(embed=status_embed, ephemeral=True)

@bot.tree.command(name="타이머중지", description="벌들의 꿀 모으기를 중지하고 쉬게 합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def stop_timer(interaction: discord.Interaction):
    global timer_task
    if timer_task and not timer_task.done():
        timer_task.cancel()
        await interaction.response.send_message("🛑 벌들이 꿀 모으기를 멈추고 벌집으로 돌아왔습니다.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ 현재 실행 중인 타이머가 없습니다.", ephemeral=True)

# ---------------------------------------------------------
# 프로그램 실행 진입점
# ---------------------------------------------------------
if __name__ == '__main__':
    keep_alive()
    TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
    bot.run(TOKEN)

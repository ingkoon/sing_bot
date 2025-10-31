# ingribo.py
import os
import discord
import asyncio
from discord.ext import commands
from dico_token import Token
import yt_dlp
import re
import ctypes
from typing import List, Optional, Dict
import time
import random
import shutil

# =========================
# Opus 강제 로드 (필요시 경로 수정)
# =========================
OPUS_LIB_PATH = "/opt/homebrew/lib/libopus.dylib"  # mac에서 테스트용. 리눅스에선 무시됨
try:
    discord.opus.load_opus(OPUS_LIB_PATH)
    print(f"[OPUS] Loaded opus from {OPUS_LIB_PATH}")
except OSError as e:
    print(f"[OPUS] Failed to load opus from {OPUS_LIB_PATH}: {e}")
    # 실패해도, 서버(리눅스) 환경에서 기본 opus가 잡히면 정상 동작함

# =========================
# 상수 / 정규식 / 이모지
# =========================
YOUTUBE_URL_REGEX = re.compile(
    r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+',
    re.IGNORECASE,
)
EMOJI_CHOICES = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

# 간단 캐시: 같은 키워드 반복 요청 시 바로 응답
track_cache: Dict[str, dict] = {}

# =========================
# Intents
# =========================
intents = discord.Intents.default()
intents.message_content = True      # prefix 명령 처리
intents.reactions = True            # reaction 선택
intents.voice_states = True         # 음성 참여 상태

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!"),
    description="디스코드 음성/음악 테스트 봇 (반응성 개선 버전)",
    intents=intents,
)

# =========================
# yt-dlp 공통 옵션 (쿠키 포함)  ← 추가/수정
# =========================
def _ydl_opts_base(default_search: Optional[str] = None) -> dict:
    """
    환경변수 YTDLP_COOKIES를 사용해 cookiefile을 yt-dlp에 전달한다.
    하드코딩은 하지 않으며, 경로가 없으면 경고만 남기고 쿠키 없이 진행한다.
    """
    opts: Dict[str, object] = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "skip_download": True,
        # 필요 시 player_client 강제를 넣고 싶다면 아래 extractor_args 사용
        # "extractor_args": {"youtube": {"player_client": ["web"]}},
        "retries": 3,
        "file_access_retries": 2,
        "fragment_retries": 3,
        "geo_bypass": True,
    }
    if default_search:
        opts["default_search"] = default_search

    cookiefile = os.getenv("YTDLP_COOKIES")
    if cookiefile and os.path.exists(cookiefile):
        opts["cookiefile"] = cookiefile
        print(f"[YTDLP] Using cookiefile from env: {cookiefile}")
    else:
        print(f"[YTDLP] No cookies loaded. YTDLP_COOKIES={cookiefile} exists={os.path.exists(cookiefile) if cookiefile else None}")
    return opts

# =========================
# yt-dlp Helper (동기 함수)
# =========================

def _ytdlp_search_one_sync(query: str) -> dict:
    """검색어로 유튜브 검색해서 첫번째 결과 추출 (동기)."""
    ydl_opts = _ydl_opts_base(default_search="ytsearch")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]

    return {
        "webpage_url": info.get("webpage_url"),
        "url": info.get("url"),
        "title": info.get("title", "Unknown Title"),
        "duration": info.get("duration"),
    }

def _ytdlp_from_url_sync(url: str) -> dict:
    """유튜브 URL 직접 분석 (동기)."""
    ydl_opts = _ydl_opts_base()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return {
        "webpage_url": info.get("webpage_url"),
        "url": info.get("url"),
        "title": info.get("title", "Unknown Title"),
        "duration": info.get("duration"),
    }

def _ytdlp_search_top5_sync(query: str) -> List[dict]:
    """검색어로 유튜브 상위 5개 결과 추출 (동기)."""
    ydl_opts = _ydl_opts_base(default_search="ytsearch5")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        entries = info.get("entries", [])

    results = []
    for e in entries[:5]:
        results.append({
            "webpage_url": e.get("webpage_url"),
            "url": e.get("url"),
            "title": e.get("title", "Unknown Title"),
            "duration": e.get("duration"),
        })
    return results

# =========================
# yt-dlp Async Wrapper
# =========================

async def get_track_info(query: str) -> dict:
    """검색어 또는 URL -> track dict. 캐시 사용. 비동기 래핑."""
    if query in track_cache:
        return track_cache[query]

    if YOUTUBE_URL_REGEX.match(query):
        info = await asyncio.to_thread(_ytdlp_from_url_sync, query)
    else:
        info = await asyncio.to_thread(_ytdlp_search_one_sync, query)

    track_cache[query] = info
    return info

async def search_top5(query: str) -> List[dict]:
    """검색어 -> 상위 5 트랙 dict list (비동기 래핑)."""
    results = await asyncio.to_thread(_ytdlp_search_top5_sync, query)
    return results

# =========================
# Guild 음악 상태 관리
# =========================

class GuildMusicPlayer:
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.queue: List[dict] = []       # 대기열
        self.playing: bool = False        # 현재 재생 중인지
        self.search_results: Dict[int, List[dict]] = {}  # message_id -> 후보 리스트

    def add_to_queue(self, track: dict):
        self.queue.append(track)

    def remove_from_queue_index(self, idx: int) -> Optional[dict]:
        if 0 <= idx < len(self.queue):
            return self.queue.pop(idx)
        return None

    def has_next_track(self) -> bool:
        return len(self.queue) > 0

    def pop_next_track(self) -> Optional[dict]:
        if self.queue:
            return self.queue.pop(0)
        return None

players: Dict[int, GuildMusicPlayer] = {}

def get_player(guild_id: int) -> GuildMusicPlayer:
    if guild_id not in players:
        players[guild_id] = GuildMusicPlayer(guild_id)
    return players[guild_id]

# =========================
# Voice Join / Playback
# =========================

async def ensure_voice(ctx) -> discord.VoiceClient:
    """ctx.author의 음성채널에 봇이 없으면 붙는다. 이미 있으면 이동 안 함."""
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(
            name=":exclamation:",
            value="먼저 음성 채널에 들어가 주세요."
        )
        await ctx.send(embed=embed)
        raise commands.CommandError("Caller not in voice channel")

    vc = ctx.guild.voice_client
    if vc is not None and vc.is_connected():
        return vc

    vc = await ctx.author.voice.channel.connect()
    return vc

def start_playback(vc: discord.VoiceClient, track: dict, guild_player: GuildMusicPlayer, loop: asyncio.AbstractEventLoop):
    """ffmpeg 실행해서 실제로 음성 재생 시작."""
    ffmpeg_opts = {
        'before_options': (
            '-reconnect 1 '
            '-reconnect_streamed 1 '
            '-reconnect_delay_max 5 '
            '-timeout 10000000 '
            '-rw_timeout 10000000 '
        ),
        'options': '-vn'
    }
    audio_source = discord.FFmpegPCMAudio(track["url"], **ffmpeg_opts)

    # 재생 시작 시각 기록
    track["start_time"] = time.time()

    def after_play(error):
        if error:
            print(f"[재생 에러] {error}")
        loop.call_soon_threadsafe(asyncio.create_task, handle_after_track(vc, guild_player, track))

    vc.play(audio_source, after=after_play)

async def handle_after_track(vc: discord.VoiceClient, guild_player: GuildMusicPlayer, track: dict):
    """곡 종료 이후 호출: 다음 곡 재생 or 퇴장."""
    await asyncio.sleep(0.5)

    duration = track.get("duration", None)
    start_time = track.get("start_time", None)
    play_time = (time.time() - start_time) if start_time else None

    # 1) 방이 비어 있으면 즉시 퇴장
    if voice_channel_is_empty(vc):
        print("[INFO] 음성 채널에 유저가 없어 즉시 퇴장합니다.")
        guild_player.playing = False
        if vc.is_connected():
            await vc.disconnect()
        return

    # 2) 다음 곡 있으면 재생
    if guild_player.has_next_track():
        next_track = guild_player.pop_next_track()
        loop = asyncio.get_event_loop()
        start_playback(vc, next_track, guild_player, loop)
        return

    # 3) 다음 곡 없음 → 정상/비정상 종료 판단
    guild_player.playing = False

    duration_ok = duration and play_time
    normal_end = duration_ok and (play_time >= duration * 0.8)

    if normal_end:
        print("[INFO] 정상 종료 감지 → 퇴장 시도")
        if vc.is_connected():
            await vc.disconnect()
    else:
        print("[WARN] 비정상 조기 종료 → 채널 유지 (사용자 재요청 대기)")

async def maybe_start_playing(ctx, guild_player: GuildMusicPlayer):
    """재생 중이 아니면 바로 재생 시작. 이미 재생 중이면 아무것도 안 함."""
    if guild_player.playing:
        return
    if not guild_player.has_next_track():
        return

    vc = ctx.guild.voice_client
    if vc is None or not vc.is_connected():
        vc = await ensure_voice(ctx)

    first_track = guild_player.pop_next_track()
    guild_player.playing = True

    loop = asyncio.get_event_loop()
    start_playback(vc, first_track, guild_player, loop)

    embed = discord.Embed(
        title="지금 재생 중 🎵",
        description=first_track["title"],
        color=0x00ff56
    )
    await ctx.send(embed=embed)

# =========================
# Commands
# =========================

def voice_channel_is_empty(vc: discord.VoiceClient) -> bool:
    """현재 voice client 채널에 봇 이외 유저가 없으면 True"""
    if not vc or not vc.channel:
        return True
    channel = vc.channel
    for member in channel.members:
        if not member.bot:
            return False
    return True

@bot.command(aliases=['입장'])
async def join(ctx):
    """현재 유저 음성 채널에 봇 접속 (또는 이미 있으면 OK)."""
    try:
        vc = await ensure_voice(ctx)
    except commands.CommandError:
        return

    embed = discord.Embed(
        title=":white_check_mark: 연결됨",
        description=f"{vc.channel.name} 에 접속했습니다.",
        color=0x00ff56
    )
    await ctx.send(embed=embed)

@bot.command(aliases=['나가기'])
async def out(ctx):
    """봇 나가기 + 큐 초기화."""
    player = get_player(ctx.guild.id)
    vc = ctx.guild.voice_client

    if vc and vc.is_connected():
        ch_name = vc.channel.name
        await vc.disconnect()
        player.queue.clear()
        player.playing = False

        embed = discord.Embed(color=0x00ff56)
        embed.add_field(
            name=":regional_indicator_b::regional_indicator_y::regional_indicator_e:",
            value=f"{ch_name} 에서 나갔습니다.",
            inline=False
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(
            name=":grey_question:",
            value="현재 음성 채널에 봇이 없습니다."
        )
        await ctx.send(embed=embed)

@bot.command(name="p")
async def play(ctx, *, query: str = None):
    """
    !p <검색어 또는 유튜브URL>
    - 즉각 '검색중...' 메시지 먼저 보내고
    - yt-dlp는 다른 스레드에서 돌려서 렉 줄임
    - 큐에 넣고, 필요하면 재생 시작
    """
    if query is None or query.strip() == "":
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(
            name=":question:",
            value="사용법: `!p <유튜브 검색어>` 또는 `!p <유튜브 링크>`"
        )
        return await ctx.send(embed=embed)

    wait_embed = discord.Embed(
        color=0x999999,
        description=f"🔍 `{query}` 검색중..."
    )
    status_msg = await ctx.send(embed=wait_embed)

    try:
        track_info = await get_track_info(query)
    except Exception as e:
        err = str(e)
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(
            name="⚠️ 재생 실패",
            value=(
                "유튜브에서 ‘봇 확인’이 걸렸거나 차단된 영상일 수 있어요.\n"
                "조금 다른 검색어/영상으로도 시도해 보세요."
            )
        )
        await status_msg.edit(embed=embed)
        print(f"[yt-dlp error] {err}")
        return

    track_info["requester"] = ctx.author.display_name

    player = get_player(ctx.guild.id)
    player.add_to_queue(track_info)

    position = len(player.queue)

    done_embed = discord.Embed(color=0x00ff56)
    done_embed.add_field(
        name=":notes: 리스트에 추가",
        value=f"{position}. {track_info['title']} (요청: {track_info['requester']})"
    )
    await status_msg.edit(embed=done_embed)

    await maybe_start_playing(ctx, player)

@bot.command(name="remove")
async def remove_track(ctx, index: int = None):
    """!remove <번호> : 리스트에서 해당 번호 제거."""
    player = get_player(ctx.guild.id)

    if index is None:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(
            name=":question:",
            value="사용법: `!remove <번호>`"
        )
        return await ctx.send(embed=embed)

    removed = player.remove_from_queue_index(index - 1)
    if removed is None:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(
            name=":x:",
            value=f"{index} 번 항목은 큐에 없습니다."
        )
        return await ctx.send(embed=embed)

    embed = discord.Embed(color=0x00ff56)
    embed.add_field(
        name=":wastebasket: 제거됨",
        value=f"{index}. {removed['title']}"
    )
    await ctx.send(embed=embed)

@bot.command(name="search")
async def search_tracks(ctx, *, query: str = None):
    """
    !search <키워드>
    - '검색중...' 메세지
    - 상위 5개 결과 목록/이모지 달기
    - 리액션으로 선택하면 큐에 추가 & 필요시 재생
    """
    if query is None or query.strip() == "":
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(
            name=":question:",
            value="사용법: `!search <키워드>`"
        )
        return await ctx.send(embed=embed)

    wait_embed = discord.Embed(
        color=0x999999,
        description=f"🔍 `{query}` 검색중..."
    )
    loading_msg = await ctx.send(embed=wait_embed)

    try:
        results = await search_top5(query)
    except Exception as e:
        err = str(e)
        nores_embed = discord.Embed(color=0xf66c24)
        nores_embed.add_field(
            name=":mag:",
            value="검색 중 오류가 발생했습니다. 다른 검색어로 시도해 주세요."
        )
        await loading_msg.edit(embed=nores_embed)
        print(f"[yt-dlp error] {err}")
        return

    if len(results) == 0:
        nores_embed = discord.Embed(color=0xf66c24)
        nores_embed.add_field(
            name=":mag:",
            value="검색 결과가 없습니다."
        )
        return await loading_msg.edit(embed=nores_embed)

    desc_lines = []
    for i, r in enumerate(results, start=1):
        desc_lines.append(f"{i}. {r['title']}")
    desc_text = "\n".join(desc_lines)

    res_embed = discord.Embed(
        title=f"검색 결과: {query}",
        description=desc_text,
        color=0x00ff56
    )
    res_embed.set_footer(text="원하는 번호(1️⃣~5️⃣)에 반응하면 큐에 추가됩니다.")
    await loading_msg.edit(embed=res_embed)

    player = get_player(ctx.guild.id)
    player.search_results[loading_msg.id] = results

    for i in range(min(len(results), 5)):
        await loading_msg.add_reaction(EMOJI_CHOICES[i])

# =========================
# Reaction Handler
# =========================

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """!search 결과 메시지에 1️⃣~5️⃣ 반응하면 큐에 추가하고 필요시 재생."""
    if payload.user_id == bot.user.id:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    player = get_player(guild.id)

    if payload.message_id not in player.search_results:
        return

    emoji = str(payload.emoji)
    if emoji not in EMOJI_CHOICES:
        return

    choice_index = EMOJI_CHOICES.index(emoji)
    candidates = player.search_results[payload.message_id]
    if choice_index >= len(candidates):
        return

    chosen = candidates[choice_index]

    member = guild.get_member(payload.user_id)
    requester_name = member.display_name if member else "unknown"

    track_info = {
        "webpage_url": chosen["webpage_url"],
        "url": chosen["url"],
        "title": chosen["title"],
        "duration": chosen["duration"],
        "requester": requester_name,
    }
    player.add_to_queue(track_info)

    channel = guild.get_channel(payload.channel_id)
    if channel is not None:
        pos = len(player.queue)
        added_embed = discord.Embed(color=0x00ff56)
        added_embed.add_field(
            name=":notes: 큐에 추가",
            value=f"{pos}. {track_info['title']} (요청: {track_info['requester']})"
        )
        await channel.send(embed=added_embed)

        if not player.playing:
            vc = guild.voice_client
            if vc is None or not vc.is_connected():
                if member and member.voice and member.voice.channel:
                    vc = await member.voice.channel.connect()
            if vc and (vc.is_connected()):
                first_track = player.pop_next_track()
                player.playing = True
                loop = asyncio.get_event_loop()
                start_playback(vc, first_track, player, loop)

                play_embed = discord.Embed(
                    title="지금 재생 중 🎵",
                    description=first_track["title"],
                    color=0x00ff56
                )
                await channel.send(embed=play_embed)

@bot.command(name="skip")
async def skip_track(ctx):
    """현재 곡을 건너뛰고 다음 곡 재생 (없으면 퇴장)"""
    vc = ctx.guild.voice_client
    if not vc or not vc.is_connected():
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":grey_question:", value="현재 음성 채널에 봇이 없습니다.")
        return await ctx.send(embed=embed)

    player = get_player(ctx.guild.id)

    if vc.is_playing():
        vc.stop()
        await asyncio.sleep(0.5)
    else:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":zzz:", value="현재 재생 중인 곡이 없습니다.")
        return await ctx.send(embed=embed)

    if player.has_next_track():
        next_track = player.pop_next_track()
        player.playing = True
        loop = asyncio.get_event_loop()
        start_playback(vc, next_track, player, loop)

        embed = discord.Embed(
            title="⏭ 다음 곡 재생",
            description=next_track["title"],
            color=0x00ff56
        )
        await ctx.send(embed=embed)
    else:
        player.playing = False
        await vc.disconnect()
        embed = discord.Embed(
            color=0xf66c24,
            description="⏹️ 재생할 다음 곡이 없어 퇴장합니다."
        )
        await ctx.send(embed=embed)

# =========================
# !list (기존 !queue 대체)
# =========================
@bot.command(name="list", aliases=["queue", "q"])
async def show_list(ctx):
    """현재 재생 중 + 대기열 표시"""
    player = get_player(ctx.guild.id)
    vc = ctx.guild.voice_client

    current = None
    if vc and vc.is_playing() and player.playing:
        current = "🎶 **현재 재생 중:** (다음 곡 ↓)\n\n"

    if len(player.queue) == 0 and not current:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":zzz:", value="재생 중이거나 대기 중인 곡이 없습니다.")
        return await ctx.send(embed=embed)

    desc_lines = [
        f"{idx}. {t['title']} (요청: {t.get('requester', '알 수 없음')})"
        for idx, t in enumerate(player.queue, start=1)
    ]

    desc_text = (current or "") + "\n".join(desc_lines) if desc_lines else "대기열이 비었습니다."

    embed = discord.Embed(
        title="📜 현재 재생 리스트",
        description=desc_text,
        color=0x00ff56
    )
    await ctx.send(embed=embed)

# =========================
# !shuffle
# =========================
@bot.command(name="shuffle")
async def shuffle_list(ctx):
    """현재 대기열을 섞기"""
    player = get_player(ctx.guild.id)

    if len(player.queue) < 2:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":grey_question:", value="섞을 대기열이 없습니다.")
        return await ctx.send(embed=embed)

    random.shuffle(player.queue)

    embed = discord.Embed(color=0x00ff56)
    embed.add_field(name="🔀 셔플 완료", value="대기열의 순서를 무작위로 변경했습니다.")
    await ctx.send(embed=embed)

# =========================
# on_ready
# =========================
@bot.event
async def on_ready():
    print(f'{bot.user} 봇을 실행합니다.')
    print(f"[HEALTH] ffmpeg in PATH? {shutil.which('ffmpeg')}")
    cookiefile = os.getenv("YTDLP_COOKIES")
    print(f"[HEALTH] YTDLP_COOKIES={cookiefile} exists={os.path.exists(cookiefile) if cookiefile else None}")

# =========================
# run
# =========================
bot.run(Token)
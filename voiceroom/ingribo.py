#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import re
import time
import random
import asyncio
import ctypes.util
import platform
import shutil
from typing import List, Optional, Dict

import discord
from discord.ext import commands
import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from dico_token import Token  # 봇 토큰은 별도 파일/환경변수로 관리 권장

# =========================
# Opus Portable Loader
# =========================
def load_opus_portably() -> bool:
    """
    EC2/리눅스/맥/윈도우에서 Opus를 자동 탐색/로드.
    우선순위: 환경변수(OPUS_LIB) -> ctypes.util.find_library -> OS별 흔한 경로
    """
    if discord.opus.is_loaded():
        return True

    # 1) 환경변수 우선
    env_path = os.getenv("OPUS_LIB")
    if env_path:
        try:
            discord.opus.load_opus(env_path)
            print(f"[OPUS] Loaded via OPUS_LIB={env_path}")
            return True
        except OSError as e:
            print(f"[OPUS] Failed via OPUS_LIB: {e}")

    # 2) 시스템 검색
    for name in ("opus", "libopus", "libopus-0"):
        libpath = ctypes.util.find_library(name)
        if libpath:
            try:
                discord.opus.load_opus(libpath)
                print(f"[OPUS] Loaded via find_library: {libpath}")
                return True
            except OSError as e:
                print(f"[OPUS] Failed via find_library({libpath}): {e}")

    # 3) OS별 후보 경로
    candidates = []
    if sys.platform.startswith("linux"):
        candidates += [
            "/usr/lib/x86_64-linux-gnu/libopus.so.0",
            "/usr/lib/x86_64-linux-gnu/libopus.so",
            "/usr/lib64/libopus.so.0",
            "/usr/lib64/libopus.so",
            "/usr/local/lib/libopus.so.0",
            "/usr/local/lib/libopus.so",
        ]
    elif sys.platform == "darwin":
        candidates += [
            "/opt/homebrew/lib/libopus.dylib",  # Apple Silicon
            "/usr/local/lib/libopus.dylib",     # Intel mac
        ]
    elif sys.platform.startswith("win"):
        candidates += ["opus.dll"]

    for path in candidates:
        if os.path.exists(path):
            try:
                discord.opus.load_opus(path)
                print(f"[OPUS] Loaded from {path}")
                return True
            except OSError as e:
                print(f"[OPUS] Failed to load {path}: {e}")

    print("[OPUS] Could not load Opus. Voice features will fail.")
    return False

# 실제 로드 시도
load_opus_portably()

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
# ⚠️ 개발자 포털에서 "Message Content Intent"를 반드시 켜주세요!
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!"),
    description="디스코드 음성/음악 테스트 봇 (반응성 개선 버전)",
    intents=intents,
)

# =========================
# yt-dlp 공용 옵션 빌더 (쿠키/우회/재시도)
# =========================
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

def build_ydl_opts(default_search: Optional[str] = None) -> dict:
    """
    yt-dlp 공통 옵션:
      - 쿠키 파일 자동 인식 (env: YTDLP_COOKIES)
      - 안드로이드 플레이어 클라이언트 우회
      - 한국어 우선 헤더
      - 재시도/프래그먼트 재시도/지오바이패스
    """
    opts: Dict[str, object] = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "skip_download": True,
        "http_headers": {
            "User-Agent": UA,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.youtube.com/",
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
                # 필요시 DASH 스킵 등 추가 가능
                # "skip": ["dash"],
            }
        },
        "retries": 3,
        "file_access_retries": 2,
        "fragment_retries": 3,
        "geo_bypass": True,
    }
    if default_search:
        opts["default_search"] = default_search

    cookies = os.getenv("YTDLP_COOKIES")
    if cookies and os.path.exists(cookies):
        opts["cookiefile"] = cookies

    return opts

# =========================
# yt-dlp Helper (동기 함수)
# =========================
def _ytdlp_search_one_sync(query: str) -> dict:
    ydl_opts = build_ydl_opts(default_search="ytsearch")
    try:
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
    except (DownloadError, ExtractorError) as e:
        raise RuntimeError(f"yt-dlp search failed: {e}") from e

def _ytdlp_from_url_sync(url: str) -> dict:
    ydl_opts = build_ydl_opts()
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return {
            "webpage_url": info.get("webpage_url"),
            "url": info.get("url"),
            "title": info.get("title", "Unknown Title"),
            "duration": info.get("duration"),
        }
    except (DownloadError, ExtractorError) as e:
        raise RuntimeError(f"yt-dlp url failed: {e}") from e

def _ytdlp_search_top5_sync(query: str) -> List[dict]:
    ydl_opts = build_ydl_opts(default_search="ytsearch5")
    try:
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
    except (DownloadError, ExtractorError) as e:
        raise RuntimeError(f"yt-dlp top5 failed: {e}") from e

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
    return await asyncio.to_thread(_ytdlp_search_top5_sync, query)

# =========================
# Guild 음악 상태 관리
# =========================
class GuildMusicPlayer:
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.queue: List[dict] = []
        self.playing: bool = False
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
        embed.add_field(name=":exclamation:", value="먼저 음성 채널에 들어가 주세요.")
        await ctx.send(embed=embed)
        raise commands.CommandError("Caller not in voice channel")

    vc = ctx.guild.voice_client
    if vc is not None and vc.is_connected():
        return vc
    return await ctx.author.voice.channel.connect()

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

    # 1) 방이 비었으면 즉시 퇴장
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

    # 3) 다음 곡 없음
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
    """재생 중이 아니면 바로 재생 시작."""
    if guild_player.playing or not guild_player.has_next_track():
        return

    vc = ctx.guild.voice_client
    if vc is None or not vc.is_connected():
        vc = await ensure_voice(ctx)

    first_track = guild_player.pop_next_track()
    guild_player.playing = True

    loop = asyncio.get_event_loop()
    start_playback(vc, first_track, guild_player, loop)

    embed = discord.Embed(title="지금 재생 중 🎵", description=first_track["title"], color=0x00ff56)
    await ctx.send(embed=embed)

# =========================
# Commands & Helpers
# =========================
def voice_channel_is_empty(vc: discord.VoiceClient) -> bool:
    """현재 voice client 채널에 '봇 이외 유저'가 없으면 True"""
    if not vc or not vc.channel:
        return True
    for member in vc.channel.members:
        if not member.bot:
            return False
    return True

@bot.command(aliases=['입장'])
async def join(ctx):
    try:
        vc = await ensure_voice(ctx)
    except commands.CommandError:
        return
    embed = discord.Embed(title=":white_check_mark: 연결됨", description=f"{vc.channel.name} 에 접속했습니다.", color=0x00ff56)
    await ctx.send(embed=embed)

@bot.command(aliases=['나가기'])
async def out(ctx):
    player = get_player(ctx.guild.id)
    vc = ctx.guild.voice_client

    if vc and vc.is_connected():
        ch_name = vc.channel.name
        await vc.disconnect()
        player.queue.clear()
        player.playing = False
        embed = discord.Embed(color=0x00ff56)
        embed.add_field(name=":regional_indicator_b::regional_indicator_y::regional_indicator_e:",
                        value=f"{ch_name} 에서 나갔습니다.", inline=False)
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":grey_question:", value="현재 음성 채널에 봇이 없습니다.")
        await ctx.send(embed=embed)

@bot.command(name="p")
async def play(ctx, *, query: str = None):
    if not query or query.strip() == "":
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":question:", value="사용법: `!p <유튜브 검색어>` 또는 `!p <유튜브 링크>`")
        return await ctx.send(embed=embed)

    wait_embed = discord.Embed(color=0x999999, description=f"🔍 `{query}` 검색중...")
    status_msg = await ctx.send(embed=wait_embed)

    try:
        track_info = await get_track_info(query)
    except RuntimeError as e:
        guide = (
            "유튜브에서 ‘봇 확인’에 걸렸습니다.\n"
            "서버에 유튜브 쿠키를 설정해야 해요.\n"
            "1) 로컬 브라우저에서 youtube.com 로그인 상태로 cookies.txt 추출\n"
            "2) EC2에 업로드 후 환경변수 설정\n"
            "```bash\n"
            "mkdir -p ~/cookies && chmod 700 ~/cookies\n"
            "scp youtube.txt ec2-user@<EC2_IP>:~/cookies/youtube.txt\n"
            "chmod 600 ~/cookies/youtube.txt\n"
            "export YTDLP_COOKIES=/home/ec2-user/cookies/youtube.txt\n"
            "```\n"
            "설정 후 다시 시도해 주세요."
        )
        err_embed = discord.Embed(title="⚠️ 재생 실패", description=guide, color=0xf66c24)
        err_embed.set_footer(text=str(e))
        return await status_msg.edit(embed=err_embed)

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
    player = get_player(ctx.guild.id)
    if index is None:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":question:", value="사용법: `!remove <번호>`")
        return await ctx.send(embed=embed)
    removed = player.remove_from_queue_index(index - 1)
    if removed is None:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":x:", value=f"{index} 번 항목은 큐에 없습니다.")
        return await ctx.send(embed=embed)
    embed = discord.Embed(color=0x00ff56)
    embed.add_field(name=":wastebasket: 제거됨", value=f"{index}. {removed['title']}")
    await ctx.send(embed=embed)

@bot.command(name="search")
async def search_tracks(ctx, *, query: str = None):
    if not query or query.strip() == "":
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":question:", value="사용법: `!search <키워드>`")
        return await ctx.send(embed=embed)

    wait_embed = discord.Embed(color=0x999999, description=f"🔍 `{query}` 검색중...")
    loading_msg = await ctx.send(embed=wait_embed)

    try:
        results = await search_top5(query)
    except RuntimeError as e:
        err = discord.Embed(title="⚠️ 검색 실패", description="yt-dlp 검색에 실패했습니다. (쿠키 설정 필요할 수 있음)", color=0xf66c24)
        err.set_footer(text=str(e))
        return await loading_msg.edit(embed=err)

    if not results:
        nores_embed = discord.Embed(color=0xf66c24)
        nores_embed.add_field(name=":mag:", value="검색 결과가 없습니다.")
        return await loading_msg.edit(embed=nores_embed)

    desc_lines = [f"{i}. {r['title']}" for i, r in enumerate(results, start=1)]
    res_embed = discord.Embed(title=f"검색 결과: {query}", description="\n".join(desc_lines), color=0x00ff56)
    res_embed.set_footer(text="원하는 번호(1️⃣~5️⃣)에 반응하면 큐에 추가됩니다.")
    await loading_msg.edit(embed=res_embed)

    player = get_player(ctx.guild.id)
    player.search_results[loading_msg.id] = results

    for i in range(min(len(results), 5)):
        await loading_msg.add_reaction(EMOJI_CHOICES[i])

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
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
        added_embed.add_field(name=":notes: 큐에 추가",
                              value=f"{pos}. {track_info['title']} (요청: {track_info['requester']})")
        await channel.send(embed=added_embed)

        if not player.playing:
            vc = guild.voice_client
            if vc is None or not vc.is_connected():
                if member and member.voice and member.voice.channel:
                    vc = await member.voice.channel.connect()
            if vc and vc.is_connected():
                first_track = player.pop_next_track()
                player.playing = True
                loop = asyncio.get_event_loop()
                start_playback(vc, first_track, player, loop)
                play_embed = discord.Embed(title="지금 재생 중 🎵",
                                           description=first_track["title"], color=0x00ff56)
                await channel.send(embed=play_embed)

@bot.command(name="skip")
async def skip_track(ctx):
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
        embed = discord.Embed(title="⏭ 다음 곡 재생", description=next_track["title"], color=0x00ff56)
        await ctx.send(embed=embed)
    else:
        player.playing = False
        await vc.disconnect()
        embed = discord.Embed(color=0xf66c24, description="⏹️ 재생할 다음 곡이 없어 퇴장합니다.")
        await ctx.send(embed=embed)

@bot.command(name="list", aliases=["queue", "q"])
async def show_list(ctx):
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
    desc_text = (current or "") + ("\n".join(desc_lines) if desc_lines else "대기열이 비었습니다.")

    embed = discord.Embed(title="📜 현재 재생 리스트", description=desc_text, color=0x00ff56)
    await ctx.send(embed=embed)

# =========================
# on_ready (헬스체크 로그 강화)
# =========================
@bot.event
async def on_ready():
    print(f'{bot.user} 봇을 실행합니다.')
    print(f"[HEALTH] Opus loaded? {discord.opus.is_loaded()}")
    print(f"[HEALTH] ffmpeg in PATH? {shutil.which('ffmpeg')}")
    print(f"[HEALTH] Python={platform.python_version()} | Platform={platform.platform()}")

# =========================
# run
# =========================
if __name__ == "__main__":
    # systemd로 돌릴 때는 [Service]에 다음 추가 권장:
    # Environment=YTDLP_COOKIES=/home/ec2-user/cookies/youtube.txt
    # Environment=PATH=/home/ec2-user/.venv/bin:/usr/local/bin:/usr/bin
    bot.run(Token)
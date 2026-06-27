# ingribo.py
import os
import re
import time
import random
import shutil
import tempfile
import asyncio
from typing import List, Optional, Dict

import discord
from discord.ext import commands
from dico_token import Token
import yt_dlp

# =========================
# (선택) Opus 강제 로드 - mac 테스트용, 리눅스에선 무시돼도 OK
# =========================
OPUS_LIB_PATH = "/opt/homebrew/lib/libopus.dylib"
try:
    discord.opus.load_opus(OPUS_LIB_PATH)
    print(f"[OPUS] Loaded opus from {OPUS_LIB_PATH}")
except OSError as e:
    print(f"[OPUS] Failed to load opus from {OPUS_LIB_PATH}: {e}")

# =========================
# 상수 / 정규식 / 이모지
# =========================
YOUTUBE_URL_REGEX = re.compile(r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+', re.IGNORECASE)
EMOJI_CHOICES = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

# 간단 캐시: 같은 키워드 반복 요청 시 바로 응답
track_cache: Dict[str, dict] = {}

# =========================
# Intents & Bot
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!"),
    description="디스코드 음악 봇 (쿠키/클라이언트 폴백/검색 폴백 내장)",
    intents=intents,
)

# =========================
# yt-dlp 공통 옵션 (쿠키는 환경변수 YTDLP_COOKIES에서만)
# =========================
def _ydl_opts_base(default_search: Optional[str] = None) -> Dict[str, object]:
    opts: Dict[str, object] = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "skip_download": True,
        "retries": 3,
        "file_access_retries": 2,
        "fragment_retries": 3,
        "geo_bypass": True,
        # 필요 시 HTTP 헤더 등 추가 가능
        # "http_headers": {...}
    }
    if default_search:
        opts["default_search"] = default_search

    # PO Token 공급자(bgutil HTTP 서버)를 가리키도록 설정.
    # 데이터센터 IP(EC2)에서 'Sign in to confirm you're not a bot' 우회에 필요.
    # compose 사이드카 서비스명 기준 기본값(http://bgutil-provider:4416).
    pot_base = os.getenv("BGUTIL_POT_BASE_URL")
    if pot_base:
        opts["extractor_args"] = {
            "youtubepot-bgutilhttp": {"base_url": [pot_base]},
        }
        print(f"[YTDLP] Using bgutil POT provider: {pot_base}")

    cookiefile = os.getenv("YTDLP_COOKIES")
    if cookiefile and os.path.exists(cookiefile):
        opts["cookiefile"] = cookiefile
        print(f"[YTDLP] Using cookiefile from env: {cookiefile}")
    else:
        print(f"[YTDLP] No cookies loaded. YTDLP_COOKIES={cookiefile} exists={os.path.exists(cookiefile) if cookiefile else None}")
    return opts

# 여러 클라이언트로 재시도 (일부 영상이 특정 클라에서만 막히는 대응)
# 주의: ios/android 클라이언트는 쿠키를 무시(android는 'does not support cookies')하므로 제외.
# 2026년 기준 web/mweb는 SABR로 막혀 'Only images are available'(포맷 없음)이 잦음.
# tv(TV HTML5) 클라이언트가 쿠키+POT와 함께 실제 포맷을 안정적으로 반환 → 최우선.
PLAYER_CLIENTS = (["tv"], ["web_safari"], ["mweb"])

def _extract_with_clients(extract_fn, *args, default_search: Optional[str] = None):
    """
    extract_fn(ydl, *args)을 player_client 후보들을 바꿔가며 시도.
    하나라도 성공하면 반환, 모두 실패 시 마지막 예외를 올림.
    """
    last_err = None
    for client in PLAYER_CLIENTS:
        ydl_opts = _ydl_opts_base(default_search=default_search)
        ea = dict(ydl_opts.get("extractor_args") or {})
        ytargs = dict(ea.get("youtube") or {})
        ytargs["player_client"] = client
        ea["youtube"] = ytargs
        ydl_opts["extractor_args"] = ea

        # yt-dlp는 추출 종료 시 cookiefile에 쿠키를 다시 저장한다.
        # 마운트된 원본이 읽기전용(:ro)이면 OSError로 성공한 추출까지 버려지고,
        # 동시 추출이 같은 파일에 쓰면 손상될 수 있다. 매 시도마다 쓰기 가능한
        # 임시 파일로 복사해 사용하고 끝나면 삭제한다(원본은 건드리지 않음).
        tmp_cookie = None
        src_cookie = ydl_opts.get("cookiefile")
        if src_cookie:
            fd, tmp_cookie = tempfile.mkstemp(prefix="ytcookies_", suffix=".txt")
            os.close(fd)
            shutil.copyfile(src_cookie, tmp_cookie)
            ydl_opts["cookiefile"] = tmp_cookie

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                print(f"[YTDLP] Try player_client={client}")
                return extract_fn(ydl, *args)
        except Exception as e:
            last_err = e
            print(f"[YTDLP] player_client={client} failed: {e}")
            continue
        finally:
            if tmp_cookie and os.path.exists(tmp_cookie):
                os.remove(tmp_cookie)
    raise last_err

# =========================
# yt-dlp Helper (동기 함수)
# =========================
def _ytdlp_search_one_sync(query: str) -> dict:
    def _do(ydl, q):
        info = ydl.extract_info(q, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return {
            "webpage_url": info.get("webpage_url"),
            "url": info.get("url"),
            "title": info.get("title", "Unknown Title"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
        }
    return _extract_with_clients(_do, query, default_search="ytsearch")

def _ytdlp_from_url_sync(url: str) -> dict:
    def _do(ydl, u):
        info = ydl.extract_info(u, download=False)
        return {
            "webpage_url": info.get("webpage_url"),
            "url": info.get("url"),
            "title": info.get("title", "Unknown Title"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
        }
    return _extract_with_clients(_do, url)

def _ytdlp_search_top5_sync(query: str) -> List[dict]:
    def _do(ydl, q):
        info = ydl.extract_info(q, download=False)
        entries = info.get("entries", [])
        return [{
            "webpage_url": e.get("webpage_url"),
            "url": e.get("url"),
            "title": e.get("title", "Unknown Title"),
            "duration": e.get("duration"),
            "thumbnail": e.get("thumbnail"),
        } for e in entries[:5]]
    return _extract_with_clients(_do, query, default_search="ytsearch5")

# =========================
# yt-dlp Async Wrapper
# =========================
async def get_track_info(query: str) -> dict:
    """검색어/URL -> track dict. 캐시 사용. 비동기 래핑."""
    if query in track_cache:
        return track_cache[query]
    if YOUTUBE_URL_REGEX.match(query):
        info = await asyncio.to_thread(_ytdlp_from_url_sync, query)
    else:
        info = await asyncio.to_thread(_ytdlp_search_one_sync, query)
    track_cache[query] = info
    return info

async def search_top5(query: str) -> List[dict]:
    return await asyncio.to_thread(_ytdlp_search_top5_sync, query)

# =========================
# 반복(loop) 모드
# =========================
LOOP_OFF = "off"          # 반복 없음 (기본)
LOOP_ONE = "one"          # 현재 곡 반복
LOOP_ALL = "all"          # 전체 반복 (큐를 순서대로 순환)
LOOP_SHUFFLE = "shuffle"  # 랜덤 반복 (큐를 무작위 순서로 순환)

LOOP_LABELS = {
    LOOP_OFF: "반복 없음",
    LOOP_ONE: "🔂 한 곡 반복",
    LOOP_ALL: "🔁 전체 반복",
    LOOP_SHUFFLE: "🔀 랜덤 반복",
}

# 사용자가 입력할 수 있는 별칭 → 내부 모드
LOOP_ALIASES = {
    "off": LOOP_OFF, "끄기": LOOP_OFF, "해제": LOOP_OFF, "none": LOOP_OFF, "0": LOOP_OFF,
    "one": LOOP_ONE, "한곡": LOOP_ONE, "곡": LOOP_ONE, "현재": LOOP_ONE, "song": LOOP_ONE, "this": LOOP_ONE,
    "all": LOOP_ALL, "전체": LOOP_ALL, "queue": LOOP_ALL, "큐": LOOP_ALL,
    "shuffle": LOOP_SHUFFLE, "랜덤": LOOP_SHUFFLE, "random": LOOP_SHUFFLE, "셔플": LOOP_SHUFFLE,
}

def _format_time(sec: Optional[float]) -> str:
    if sec is None:
        return "?"
    sec = max(int(sec), 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def _progress_bar(elapsed: Optional[float], duration: Optional[float], length: int = 18) -> str:
    if not duration or duration <= 0 or elapsed is None:
        return ""
    ratio = min(max(elapsed / duration, 0.0), 1.0)
    pos = min(int(ratio * length), length - 1)
    return "▬" * pos + "🔘" + "▬" * (length - pos - 1)

def track_thumbnail(track: dict) -> Optional[str]:
    """트랙의 썸네일 URL. 없으면 영상 ID로 유튜브 기본 썸네일을 유추."""
    thumb = track.get("thumbnail")
    if thumb:
        return thumb
    url = track.get("webpage_url") or ""
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([0-9A-Za-z_-]{11})", url)
    if m:
        return f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg"
    return None

def build_now_playing_embed(track: dict, player: "GuildMusicPlayer") -> discord.Embed:
    """현재 재생 곡 정보 임베드(제목/썸네일/진행바/요청자/반복 모드/대기열)."""
    title = track.get("title", "Unknown Title")
    requester = track.get("requester", "알 수 없음")
    duration = track.get("duration")
    start_time = track.get("start_time")
    elapsed = (time.time() - start_time) if start_time else None

    embed = discord.Embed(title="🎶 지금 재생 중", description=f"**{title}**", color=0x00ff56)
    url = track.get("webpage_url")
    if url:
        embed.url = url
    thumb = track_thumbnail(track)
    if thumb:
        embed.set_thumbnail(url=thumb)
    if duration:
        bar = _progress_bar(elapsed, duration)
        embed.add_field(name="진행", value=f"{bar}\n`{_format_time(elapsed)} / {_format_time(duration)}`", inline=False)
    embed.add_field(name="요청자", value=requester, inline=True)
    embed.add_field(name="반복", value=LOOP_LABELS.get(player.loop_mode, "?"), inline=True)
    embed.add_field(name="대기열", value=f"{len(player.queue)}곡 대기", inline=True)
    return embed

def build_added_embed(track: dict, position: int) -> discord.Embed:
    """큐 추가 안내 임베드(제목/썸네일/길이/요청자/대기 순번)."""
    title = track.get("title", "Unknown Title")
    requester = track.get("requester", "알 수 없음")
    duration = track.get("duration")
    embed = discord.Embed(
        title="🎵 리스트에 추가",
        description=f"**{title}**",
        color=0x00ff56,
    )
    url = track.get("webpage_url")
    if url:
        embed.url = url
    thumb = track_thumbnail(track)
    if thumb:
        embed.set_thumbnail(url=thumb)
    if duration:
        embed.add_field(name="길이", value=_format_time(duration), inline=True)
    embed.add_field(name="요청자", value=requester, inline=True)
    embed.add_field(name="대기 순번", value=f"{position}번째", inline=True)
    return embed

# =========================
# Guild 음악 상태 관리
# =========================
class GuildMusicPlayer:
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.queue: List[dict] = []
        self.playing: bool = False
        self.search_results: Dict[int, List[dict]] = {}
        self.loop_mode: str = LOOP_OFF       # 반복 모드 (off/one/all/shuffle)
        self.current: Optional[dict] = None  # 현재 재생 중인 트랙
        self.skip_requested: bool = False    # 스킵 시 한 곡 반복을 무시하기 위한 플래그
        self.text_channel = None             # 자동 다음곡 안내를 보낼 텍스트 채널

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

    def pop_random_track(self) -> Optional[dict]:
        if self.queue:
            return self.queue.pop(random.randrange(len(self.queue)))
        return None

    def pick_next(self, finished: Optional[dict], force_advance: bool = False) -> Optional[dict]:
        """반복 모드에 따라 다음 재생할 트랙을 결정.
        - one: 끝난 곡을 다시 재생(스킵 시 force_advance로 다음 곡 전진)
        - all/shuffle: 끝난 곡을 큐 뒤로 되돌려 순환(전체/무작위)
        - off: 큐의 다음 곡, 없으면 None
        """
        mode = self.loop_mode
        if mode == LOOP_ONE and not force_advance:
            return finished
        if mode in (LOOP_ALL, LOOP_SHUFFLE) and finished is not None:
            self.queue.append(finished)
        if mode == LOOP_SHUFFLE:
            return self.pop_random_track()
        return self.pop_next_track()

players: Dict[int, GuildMusicPlayer] = {}
def get_player(guild_id: int) -> GuildMusicPlayer:
    if guild_id not in players:
        players[guild_id] = GuildMusicPlayer(guild_id)
    return players[guild_id]

# =========================
# Voice Join / Playback
# =========================
def voice_channel_is_empty(vc: discord.VoiceClient) -> bool:
    if not vc or not vc.channel:
        return True
    for member in vc.channel.members:
        if not member.bot:
            return False
    return True

async def ensure_voice(ctx) -> discord.VoiceClient:
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

    # 원본 오디오 스트림
    audio_source = discord.FFmpegPCMAudio(track["url"], **ffmpeg_opts)

    # ✅ 기본 볼륨 30%로 낮춤 (원하면 0.1~0.5 사이로 조정)
    audio_source = discord.PCMVolumeTransformer(audio_source, volume=0.3)

    track["start_time"] = time.time()
    # 모든 재생은 이 함수를 통과하므로 여기서 현재 곡/재생 상태를 일원화한다.
    guild_player.current = track
    guild_player.playing = True

    def after_play(error):
        if error:
            print(f"[재생 에러] {error}")
        loop.call_soon_threadsafe(asyncio.create_task, handle_after_track(vc, guild_player, track))

    vc.play(audio_source, after=after_play)

async def handle_after_track(vc: discord.VoiceClient, guild_player: GuildMusicPlayer, track: dict):
    await asyncio.sleep(0.5)
    duration = track.get("duration", None)
    start_time = track.get("start_time", None)
    play_time = (time.time() - start_time) if start_time else None

    if voice_channel_is_empty(vc):
        print("[INFO] 음성 채널에 유저가 없어 즉시 퇴장합니다.")
        guild_player.playing = False
        guild_player.current = None
        if vc.is_connected():
            await vc.disconnect()
        return

    # 스킵 요청은 한 곡 반복을 무시하고 다음 곡으로 전진
    force_advance = guild_player.skip_requested
    guild_player.skip_requested = False

    # 비정상 조기 종료(스트림 에러 등)로 추정되면 같은 곡 무한 반복을 막기 위해
    # 반복 모드를 무시하고 큐의 다음 곡으로 전진한다(스킵일 땐 이 판정 생략).
    too_short = (play_time is not None) and (play_time < 2.0) and not force_advance
    if too_short:
        print("[WARN] 비정상 조기 종료 추정 → 반복 무시하고 큐 전진")
        next_track = guild_player.pop_next_track()
    else:
        next_track = guild_player.pick_next(track, force_advance=force_advance)

    if next_track is not None:
        loop = asyncio.get_event_loop()
        start_playback(vc, next_track, guild_player, loop)
        # 곡이 실제로 바뀐 경우에만 안내(한 곡 반복으로 같은 곡 재생 시엔 생략)
        if guild_player.text_channel is not None and next_track is not track:
            try:
                await guild_player.text_channel.send(embed=build_now_playing_embed(next_track, guild_player))
            except Exception as e:
                print(f"[WARN] 다음곡 안내 전송 실패: {e}")
        return

    guild_player.playing = False
    guild_player.current = None
    duration_ok = duration and play_time
    normal_end = duration_ok and (play_time >= duration * 0.8)
    # 정상 종료했거나, 사용자가 스킵했는데 다음 곡이 없으면 퇴장
    if normal_end or force_advance:
        print("[INFO] 다음 곡 없음 → 퇴장")
        if vc.is_connected():
            await vc.disconnect()
        if force_advance and guild_player.text_channel is not None:
            try:
                await guild_player.text_channel.send(embed=discord.Embed(color=0xf66c24, description="⏹️ 재생할 다음 곡이 없어 퇴장합니다."))
            except Exception:
                pass
    else:
        print("[WARN] 비정상 조기 종료 → 채널 유지")

async def maybe_start_playing(ctx, guild_player: GuildMusicPlayer):
    if guild_player.playing:
        return
    if not guild_player.has_next_track():
        return
    vc = ctx.guild.voice_client
    if vc is None or not vc.is_connected():
        vc = await ensure_voice(ctx)
    first_track = guild_player.pop_next_track()
    guild_player.playing = True
    guild_player.text_channel = ctx.channel
    loop = asyncio.get_event_loop()
    start_playback(vc, first_track, guild_player, loop)
    await ctx.send(embed=build_now_playing_embed(first_track, guild_player))

# =========================
# Commands
# =========================
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
        player.current = None
        player.loop_mode = LOOP_OFF
        player.skip_requested = False
        player.text_channel = None
        embed = discord.Embed(color=0x00ff56)
        embed.add_field(name=":regional_indicator_b::regional_indicator_y::regional_indicator_e:", value=f"{ch_name} 에서 나갔습니다.", inline=False)
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":grey_question:", value="현재 음성 채널에 봇이 없습니다.")
        await ctx.send(embed=embed)

@bot.command(name="p")
async def play(ctx, *, query: str = None):
    """
    !p <검색어 또는 유튜브URL>
    - 실패 시: 클라이언트 폴백 → 그래도 실패하면 제목/검색 폴백 → 그래도 안되면 안내
    """
    if not query or query.strip() == "":
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":question:", value="사용법: `!p <유튜브 검색어>` 또는 `!p <유튜브 링크>`")
        return await ctx.send(embed=embed)

    wait_embed = discord.Embed(color=0x999999, description=f"🔍 `{query}` 검색중...")
    status_msg = await ctx.send(embed=wait_embed)

    # 1차 시도
    try:
        track_info = await get_track_info(query)
    except Exception as e:
        print(f"[yt-dlp error-1st] {e}")
        # URL이었다면 → 제목/검색 폴백 시도
        if YOUTUBE_URL_REGEX.match(query):
            title = ""
            try:
                meta = await asyncio.to_thread(_ytdlp_from_url_sync, query)  # 메타만 뽑기(실패 무시)
                title = (meta.get("title") or "").strip()
            except Exception as e2:
                print(f"[yt-dlp meta fail] {e2}")

            fallback_q = title or query  # 제목이 비어도 원문 query로 검색
            try:
                candidates = await search_top5(fallback_q)
                chosen = None
                for c in candidates:
                    try:
                        # 각 후보를 실제 URL 추출로 검증(클라이언트 폴백 내장)
                        _ = await asyncio.to_thread(_ytdlp_from_url_sync, c["webpage_url"])
                        chosen = c
                        break
                    except Exception as e3:
                        print(f"[yt-dlp candidate fail] {c.get('title')} | {e3}")
                        continue
                if chosen:
                    chosen["requester"] = ctx.author.display_name
                    player = get_player(ctx.guild.id)
                    player.add_to_queue(chosen)
                    sub_embed = build_added_embed(chosen, len(player.queue))
                    sub_embed.title = "🎵 대체 트랙 추가"
                    sub_embed.description = f"원본이 차단되어 대체 트랙으로 추가했어요.\n**{chosen['title']}**"
                    await status_msg.edit(embed=sub_embed)
                    return await maybe_start_playing(ctx, player)
            except Exception as e4:
                print(f"[yt-dlp search fallback fail] {e4}")

        # 최종 실패 메시지
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(
            name="⚠️ 재생 실패",
            value=(
                "해당 영상은 유튜브의 ‘봇 확인/로그인’이 강하게 걸린 것 같아요.\n"
                "같은 곡의 다른 업로드(lyrics/official audio 등)나 검색어로 시도해 주세요."
            )
        )
        return await status_msg.edit(embed=embed)

    # 정상 케이스
    track_info["requester"] = ctx.author.display_name
    player = get_player(ctx.guild.id)
    player.add_to_queue(track_info)
    position = len(player.queue)

    await status_msg.edit(embed=build_added_embed(track_info, position))
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
    except Exception as e:
        print(f"[yt-dlp error-search] {e}")
        nores_embed = discord.Embed(color=0xf66c24)
        nores_embed.add_field(name=":mag:", value="검색 중 오류가 발생했습니다. 다른 검색어로 시도해 주세요.")
        return await loading_msg.edit(embed=nores_embed)

    if not results:
        nores_embed = discord.Embed(color=0xf66c24)
        nores_embed.add_field(name=":mag:", value="검색 결과가 없습니다.")
        return await loading_msg.edit(embed=nores_embed)

    desc = "\n".join(f"{i}. {r['title']}" for i, r in enumerate(results, start=1))
    res_embed = discord.Embed(title=f"검색 결과: {query}", description=desc, color=0x00ff56)
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

    idx = EMOJI_CHOICES.index(emoji)
    candidates = player.search_results[payload.message_id]
    if idx >= len(candidates):
        return

    chosen = candidates[idx]
    member = guild.get_member(payload.user_id)
    requester_name = member.display_name if member else "unknown"

    # 후보 URL 실재성 검증(클라 폴백 포함) 후 큐 추가
    try:
        _ = await asyncio.to_thread(_ytdlp_from_url_sync, chosen["webpage_url"])
    except Exception as e:
        print(f"[yt-dlp candidate failed @reaction] {chosen.get('title')} | {e}")
        channel = guild.get_channel(payload.channel_id)
        if channel:
            await channel.send(embed=discord.Embed(color=0xf66c24, description="선택한 영상은 차단되어 재생할 수 없어요. 다른 항목을 선택해 주세요."))
        return

    track_info = {
        "webpage_url": chosen["webpage_url"],
        "url": chosen["url"],
        "title": chosen["title"],
        "duration": chosen["duration"],
        "thumbnail": chosen.get("thumbnail"),
        "requester": requester_name,
    }
    player.add_to_queue(track_info)

    channel = guild.get_channel(payload.channel_id)
    if channel:
        pos = len(player.queue)
        await channel.send(embed=build_added_embed(track_info, pos))

        if not player.playing:
            vc = guild.voice_client
            if vc is None or not vc.is_connected():
                if member and member.voice and member.voice.channel:
                    vc = await member.voice.channel.connect()
            if vc and vc.is_connected():
                first_track = player.pop_next_track()
                player.playing = True
                player.text_channel = channel
                loop = asyncio.get_event_loop()
                start_playback(vc, first_track, player, loop)
                await channel.send(embed=build_now_playing_embed(first_track, player))

@bot.command(name="skip")
async def skip_track(ctx):
    vc = ctx.guild.voice_client
    if not vc or not vc.is_connected():
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":grey_question:", value="현재 음성 채널에 봇이 없습니다.")
        return await ctx.send(embed=embed)

    player = get_player(ctx.guild.id)
    if not vc.is_playing():
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":zzz:", value="현재 재생 중인 곡이 없습니다.")
        return await ctx.send(embed=embed)

    # 스킵은 한 곡 반복이어도 다음 곡으로 전진해야 한다.
    # 다음 곡 선택/재생/퇴장은 vc.stop() → after_play → handle_after_track 에서 일원화.
    player.skip_requested = True
    player.text_channel = ctx.channel
    skipped = player.current
    vc.stop()
    title = skipped.get("title") if skipped else "현재 곡"
    embed = discord.Embed(color=0x00ff56, description=f"⏭ **{title}** 스킵")
    await ctx.send(embed=embed)

@bot.command(name="list", aliases=["queue", "q"])
async def show_list(ctx):
    player = get_player(ctx.guild.id)
    vc = ctx.guild.voice_client

    header = ""
    if player.current and vc and vc.is_connected() and (vc.is_playing() or vc.is_paused()):
        header = (
            f"🎶 **현재 재생 중:** {player.current.get('title', '?')}\n"
            f"반복: {LOOP_LABELS.get(player.loop_mode, '?')}\n\n"
        )

    if len(player.queue) == 0 and not header:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":zzz:", value="재생 중이거나 대기 중인 곡이 없습니다.")
        return await ctx.send(embed=embed)

    if player.queue:
        desc_lines = [f"{idx}. {t['title']} (요청: {t.get('requester', '알 수 없음')})" for idx, t in enumerate(player.queue, start=1)]
        body = "\n".join(desc_lines)
    else:
        body = "대기열이 비었습니다."
    embed = discord.Embed(title="📜 현재 재생 리스트", description=header + body, color=0x00ff56)
    await ctx.send(embed=embed)

@bot.command(name="shuffle")
async def shuffle_list(ctx):
    player = get_player(ctx.guild.id)
    if len(player.queue) < 2:
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":grey_question:", value="섞을 대기열이 없습니다.")
        return await ctx.send(embed=embed)
    random.shuffle(player.queue)
    embed = discord.Embed(color=0x00ff56)
    embed.add_field(name="🔀 셔플 완료", value="대기열의 순서를 무작위로 변경했습니다.")
    await ctx.send(embed=embed)

@bot.command(name="loop", aliases=["repeat", "반복"])
async def loop_cmd(ctx, mode: str = None):
    """
    !loop <one|all|shuffle|off>
    - one: 현재 곡 반복 / all: 전체 반복 / shuffle: 랜덤 반복 / off: 끄기
    - 같은 모드를 다시 입력하면 해제됩니다.
    """
    player = get_player(ctx.guild.id)

    if mode is None:
        embed = discord.Embed(
            title="🔁 반복 설정",
            description=(
                f"현재 모드: **{LOOP_LABELS.get(player.loop_mode, '?')}**\n\n"
                "`!loop one` 🔂 현재 곡 반복\n"
                "`!loop all` 🔁 전체 반복\n"
                "`!loop shuffle` 🔀 랜덤 반복\n"
                "`!loop off` 반복 끄기"
            ),
            color=0x00ff56,
        )
        return await ctx.send(embed=embed)

    new_mode = LOOP_ALIASES.get(mode.strip().lower())
    if new_mode is None:
        embed = discord.Embed(color=0xf66c24, description="모드는 `one`(현재 곡) / `all`(전체) / `shuffle`(랜덤) / `off` 중 하나예요.")
        return await ctx.send(embed=embed)

    # 같은 모드를 다시 누르면 토글로 해제
    if new_mode != LOOP_OFF and new_mode == player.loop_mode:
        player.loop_mode = LOOP_OFF
        return await ctx.send(embed=discord.Embed(color=0x00ff56, description=f"{LOOP_LABELS[new_mode]} 을(를) 해제했습니다."))

    player.loop_mode = new_mode
    await ctx.send(embed=discord.Embed(color=0x00ff56, description=f"반복 모드: **{LOOP_LABELS[new_mode]}**"))

@bot.command(name="np", aliases=["nowplaying", "now", "현재곡", "재생중"])
async def now_playing(ctx):
    """현재 재생 중인 곡 정보 표시."""
    player = get_player(ctx.guild.id)
    vc = ctx.guild.voice_client
    if not player.current or not (vc and vc.is_connected() and (vc.is_playing() or vc.is_paused())):
        embed = discord.Embed(color=0xf66c24)
        embed.add_field(name=":zzz:", value="현재 재생 중인 곡이 없습니다.")
        return await ctx.send(embed=embed)
    await ctx.send(embed=build_now_playing_embed(player.current, player))

# =========================
# on_ready
# =========================
@bot.event
async def on_ready():
    print(f'{bot.user} 봇을 실행합니다.')
    print(f"[HEALTH] ffmpeg in PATH? {shutil.which('ffmpeg')}")
    cookiefile = os.getenv("YTDLP_COOKIES")
    print(f"[HEALTH] YTDLP_COOKIES={cookiefile} exists={os.path.exists(cookiefile) if cookiefile else None}")
    print(f"[HEALTH] BGUTIL_POT_BASE_URL={os.getenv('BGUTIL_POT_BASE_URL')}")
    print(f"[HEALTH] Opus loaded? {discord.opus.is_loaded()}")

# =========================
# run
# =========================
bot.run(Token)
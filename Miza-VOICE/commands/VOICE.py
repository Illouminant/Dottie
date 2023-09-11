try:
    from common import *
except ModuleNotFoundError:
    import os
    os.chdir("..")
    from common import *

print = PRINT

import youtube_dlc
from bs4 import BeautifulSoup
youtube_dl = youtube_dlc

# Audio sample rate for both converting and playing
SAMPLE_RATE = 48000

try:
    subprocess.check_output("ffmpeg")
except subprocess.CalledProcessError:
    pass
except FileNotFoundError:
    print("WARNING: FFmpeg not found. Unable to convert and play audio.")

try:
    genius_key = AUTH["genius_key"]
    if not genius_key:
        raise
except:
    genius_key = None
    print("WARNING: genius_key not found. Unable to use API to search song lyrics.")
try:
    google_api_key = AUTH["google_api_key"]
    if not google_api_key:
        raise
except:
    google_api_key = None
    print("WARNING: google_api_key not found. Unable to use API to search youtube playlists.")


async def create_player(auds, p_type=0, verbose=False):
    auds.stats.quiet |= 2 * p_type
    # Set callback message for updating audio player
    text = (
        "```" + "\n" * verbose + "callback-voice-player-" + str(int(bool(p_type)))
        + "\nInitializing virtual audio player...```"
    )
    await auds.channel.send(text)
    await auds.update_player()


# Gets estimated duration from duration stored in queue entry
e_dur = lambda d: float(d) if type(d) is str else (d if d is not None else 300)


# Runs ffprobe on a file or url, returning the duration if possible.
def get_duration(filename):
    command = ["ffprobe", "-hide_banner", filename]
    resp = None
    for _ in loop(3):
        try:
            proc = psutil.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            fut = create_future_ex(proc.communicate, timeout=8)
            res = fut.result(timeout=8)
            resp = b"\n".join(res)
            break
        except:
            with suppress():
                proc.kill()
            print_exc()
    if not resp:
        return None
    s = as_str(resp)
    with tracebacksuppressor(ValueError):
        i = s.index("Duration: ")
        d = s[i + 10:]
        i = 2147483647
        for c in ", \n\r":
            with suppress(ValueError):
                x = d.index(c)
                if x < i:
                    i = x
        dur = time_parse(d[:i])
        return dur


# Gets the best icon/thumbnail for a queue entry.
def get_best_icon(entry):
    with suppress(KeyError):
        return entry["icon"]
    with suppress(KeyError):
        return entry["thumbnail"]
    try:
        thumbnails = entry["thumbnails"]
    except KeyError:
        try:
            url = entry["webpage_url"]
        except KeyError:
            url = entry["url"]
        if is_discord_url(url):
            if not is_image(url):
                return "https://cdn.discordapp.com/embed/avatars/0.png"
        return url
    return sorted(thumbnails, key=lambda x: float(x.get("width", x.get("preference", 0) * 4096)), reverse=True)[0]["url"]


# Gets the best audio file download link for a queue entry.
def get_best_audio(entry):
    with suppress(KeyError):
        return entry["stream"]
    best = -inf
    try:
        fmts = entry["formats"]
    except KeyError:
        fmts = ()
    try:
        url = entry["webpage_url"]
    except KeyError:
        url = entry.get("url")
    replace = True
    for fmt in fmts:
        q = fmt.get("abr", 0)
        if type(q) is not int:
            q = 0
        vcodec = fmt.get("vcodec", "none")
        if vcodec not in (None, "none"):
            q -= 1
        u = as_str(fmt["url"])
        if not u.startswith("https://manifest.googlevideo.com/api/manifest/dash/"):
            replace = False
        if q > best or replace:
            best = q
            url = fmt["url"]
    if "dropbox.com" in url:
        if "?dl=0" in url:
            url = url.replace("?dl=0", "?dl=1")
    if url.startswith("https://manifest.googlevideo.com/api/manifest/dash/"):
        resp = Request(url)
        fmts = alist()
        with suppress(ValueError, KeyError):
            while True:
                search = b'<Representation id="'
                resp = resp[resp.index(search) + len(search):]
                f_id = as_str(resp[:resp.index(b'"')])
                search = b"><BaseURL>"
                resp = resp[resp.index(search) + len(search):]
                stream = as_str(resp[:resp.index(b'</BaseURL>')])
                fmt = cdict(youtube_dl.extractor.youtube.YoutubeIE._formats[f_id])
                fmt.url = stream
                fmts.append(fmt)
        entry["formats"] = fmts
        return get_best_audio(entry)
    if not url:
        raise KeyError("URL not found.")
    return url


# Gets the best video file download link for a queue entry.
def get_best_video(entry):
    with suppress(KeyError):
        return entry["stream"]
    best = -inf
    try:
        fmts = entry["formats"]
    except KeyError:
        fmts = ()
    try:
        url = entry["webpage_url"]
    except KeyError:
        url = entry.get("url")
    replace = True
    for fmt in fmts:
        q = fmt.get("height", 0)
        if type(q) is not int:
            q = 0
        vcodec = fmt.get("vcodec", "none")
        if vcodec in (None, "none"):
            q -= 1
        u = as_str(fmt["url"])
        if not u.startswith("https://manifest.googlevideo.com/api/manifest/dash/"):
            replace = False
        if q > best or replace:
            best = q
            url = fmt["url"]
    if "dropbox.com" in url:
        if "?dl=0" in url:
            url = url.replace("?dl=0", "?dl=1")
    if url.startswith("https://manifest.googlevideo.com/api/manifest/dash/"):
        resp = Request(url)
        fmts = alist()
        with suppress(ValueError, KeyError):
            while True:
                search = b'<Representation id="'
                resp = resp[resp.index(search) + len(search):]
                f_id = as_str(resp[:resp.index(b'"')])
                search = b"><BaseURL>"
                resp = resp[resp.index(search) + len(search):]
                stream = as_str(resp[:resp.index(b'</BaseURL>')])
                fmt = cdict(youtube_dl.extractor.youtube.YoutubeIE._formats[f_id])
                fmt.url = stream
                fmts.append(fmt)
        entry["formats"] = fmts
        return get_best_video(entry)
    if not url:
        raise KeyError("URL not found.")
    return url


# Joins a voice channel and returns the associated audio player.
async def auto_join(guild, channel, user, bot, preparing=False, vc=None):
    if type(channel) in (str, int):
        channel = await bot.fetch_channel(channel)
    if guild.id not in bot.data.audio.players:
        for func in bot.commands.connect:
            try:
                await func(user=user, channel=channel, vc=vc)
            except (discord.ClientException, AttributeError):
                pass
    try:
        auds = bot.data.audio.players[guild.id]
    except KeyError:
        raise LookupError("Unable to find voice channel.")
    auds.channel = channel
    auds.preparing = preparing
    return auds


# Helper function to save all items in a queue
copy_entry = lambda item: {"name": item.name, "url": item.url, "duration": item.duration}


async def disconnect_members(bot, guild, members, channel=None):
    if bot.id in (member.id for member in members):
        with suppress(KeyError):
            auds = bot.data.audio.players[guild.id]
            if channel is not None:
                auds.channel = channel
            auds.dead = True
            bot.data.audio.connecting.pop(guild.id, None)
            await bot.data.audio(guild=guild)
    futs = [create_task(member.move_to(None)) for member in members]
    for fut in futs:
        await fut


# Checks if the user is alone in voice chat (excluding bots).
def is_alone(auds, user):
    for m in auds.vc.channel.members:
        if m.id != user.id and not m.bot:
            return False
    return True


# Replaces youtube search queries in youtube-dl with actual youtube search links.
def ensure_url(url):
    if url.startswith("ytsearch:"):
        url = f"https://www.youtube.com/results?search_query={verify_url(url[9:])}"
    return url


# This messy regex helps identify and remove certain words in song titles
lyric_trans = re.compile(
    (
        "[([]+"
        "(((official|full|demo|original|extended) *)?"
        "((version|ver.?) *)?"
        "((w\\/)?"
        "(lyrics?|vocals?|music|ost|instrumental|acoustic|studio|hd|hq) *)?"
        "((album|video|audio|cover|remix) *)?"
        "(upload|reupload|version|ver.?)?"
        "|(feat|ft)"
        ".+)"
        "[)\\]]+"
    ),
    flags=re.I,
)


# Audio player that wraps discord audio sources, contains a queue, and also manages audio settings.
class CustomAudio(discord.AudioSource, collections.abc.Hashable):

    # Empty opus packet data
    emptyopus = b"\xfc\xff\xfe"
    # Default player settings
    defaults = {
        "volume": 1,
        "reverb": 0,
        "pitch": 0,
        "speed": 1,
        "pan": 1,
        "bassboost": 0,
        "compressor": 0,
        "chorus": 0,
        "resample": 0,
        "bitrate": mpf("1966.08"),
        "loop": False,
        "repeat": False,
        "shuffle": False,
        "quiet": False,
        "stay": False,
        "position": 0,
    }

    def __init__(self, bot, vc=None, channel=None):
        with tracebacksuppressor:
            # Class instance variables
            self.paused = False
            self.stats = cdict(self.defaults)
            self.source = None
            self.channel = channel
            self.vc = vc
            self.reverse = False
            self.reading = 0
            self.has_read = False
            self.searching = False
            self.preparing = True
            self.player = None
            self.timeout = utc()
            self.ts = None
            self.lastsent = 0
            self.last_end = 0
            self.pausec = False
            self.curr_timeout = 0
            self.bot = bot
            self.args = []
            self.new(update=False)
            self.queue = AudioQueue()
            self.queue._init_(auds=self)
            self.semaphore = Semaphore(1, 4, rate_limit=1 / 8)
            self.announcer = Semaphore(1, 1, rate_limit=1 / 3)
            if not bot.is_trusted(getattr(channel, "guild", None)):
                self.queue.maxitems = 8192
            bot.data.audio.players[vc.guild.id] = self
            self.stats.update(bot.data.audiosettings.get(self.guild.id, {}))

    def __str__(self):
        classname = str(self.__class__).replace("'>", "")
        classname = classname[classname.index("'") + 1:]
        return f"<{classname} object at {hex(id(self)).upper().replace('X', 'x')}>: " + "{" + f'"vc": {self.vc}, "queue": {len(self.queue)}, "stats": {self.stats}, "source": {self.source}' + "}"

    __hash__ = lambda self: self.channel.id ^ self.guild.id

    def __getattr__(self, key):
        with suppress(AttributeError):
            return self.__getattribute__(key)
        with suppress(AttributeError, KeyError):
            return getattr(self.__getattribute__("source"), key)
        with suppress(AttributeError, KeyError):
            return getattr(self.__getattribute__("vc"), key)
        with suppress(AttributeError, LookupError):
            return getattr(self.__getattribute__("queue"), key)
        return getattr(self.__getattribute__("channel"), key)

    def __dir__(self):
        data = set(object.__dir__(self))
        data.update(dir(self.source))
        data.update(dir(self.vc))
        data.update(dir(self.queue))
        data.update(dir(self.channel))
        return data

    def has_options(self):
        stats = self.stats
        return stats.volume != 1 or stats.reverb != 0 or stats.pitch != 0 or stats.speed != 1 or stats.pan != 1 or stats.bassboost != 0 or stats.compressor != 0 or stats.chorus != 0 or stats.resample != 0

    def get_dump(self, position, js=False):
        with self.semaphore:
            lim = 1024
            q = [copy_entry(item) for item in self.queue.verify()]
            s = {k: (v if not issubclass(type(v), mpf) else int(v) if abs(int(v)) >= (1 << 32) else float(v)) for k, v in self.stats.items()}
            d = {
                "stats": s,
                "queue": q,
            }
            if not position:
                d["stats"].pop("position")
            if js:
                if len(q) > lim:
                    s = pickle.dumps(d)
                    if len(s) > 262144:
                        return encrypt(bytes2zip(s)), "dump.bin"
                    return encrypt(s), "dump.bin"
                return json.dumps(d).encode("utf-8"), "dump.json"
            return d, None

    # A call to voice_client.play ignoring discord.py bot exceptions.
    def ensure_play(self):
        with tracebacksuppressor(RuntimeError, discord.ClientException):
            self.play(self, after=self.update)

    # Stops currently playing source, closing it if possible.
    def stop(self):
        if getattr(self, "source", None) is None:
            return
        if not self.source.closed:
            create_future_ex(self.source.close, timeout=60)
        self.source = None

    # Loads and plays a new audio source, with current settings and optional song init position.
    def new(self, source=None, pos=0, update=True):
        self.speed = abs(self.stats.speed)
        self.is_playing = source is not None
        if source is not None:
            new_source = None
            try:
                self.stats.position = 0
                # This call may take a while depending on the time taken by FFmpeg to start outputting
                t = utc()
                while source.stream is None and utc() - t < 10:
                    time.sleep(0.1)
                new_source = source.create_reader(pos, auds=self)
            except OverflowError:
                source = None
            else:
                self.preparing = False
                self.is_playing = True
                self.has_read = False
            # Only stop and replace audio source when the next one is buffered successfully and readable
            self.stop()
            self.source = new_source
            self.file = source
        else:
            self.stop()
            self.file = None
        self.stats.position = pos
        if pos == 0:
            if self.reverse and len(self.queue):
                self.stats.position = e_dur(self.queue[0].duration)
        if self.source is not None and self.player:
            self.player.time = 1 + utc()
        if self.speed < 0.005:
            self.speed = 1
            self.paused |= 2
        else:
            self.paused &= -3
        if update:
            self.update()
            self.queue.update_play()

    # Seeks current song position.
    def seek(self, pos):
        duration = e_dur(self.queue[0].duration)
        pos = max(0, pos)
        # Skip current song if position is out of range
        if (pos >= duration and not self.reverse) or (pos <= 0 and self.reverse):
            create_future_ex(self.new, update=True, timeout=60)
            return duration
        create_future_ex(self.new, self.file, pos, update=False, timeout=60)
        self.stats.position = pos
        return self.stats.position

    # Sends a deletable message to the audio player's channel.
    def announce(self, *args, sync=True, **kwargs):
        if sync:
            with self.announcer:
                return await_fut(send_with_react(self.channel, *args, reacts="❎", **kwargs))
        return create_task(send_with_react(self.channel, *args, reacts="❎", **kwargs))

    # Kills this audio player, stopping audio playback. Will cause bot to leave voice upon next update event.
    def kill(self, reason=None):
        self.dead = None
        g = self.guild.id
        self.bot.data.audio.players.pop(g, None)
        self.bot.data.audio.connecting.pop(g, None)
        with suppress(LookupError):
            if reason is None:
                reason = ini_md(f"Successfully disconnected from {sqr_md(self.guild)}... Sad that it is time to go... 😔")
            if reason:
                self.announce(reason)
        self.stop()
        with tracebacksuppressor:
            self.vc.stop()

    # Update event, ensures audio is playing correctly and moves, leaves, or rejoins voice when necessary.
    def update(self, *void1, **void2):
        vc = self.vc
        guild = self.guild
        if hasattr(self, "dead"):
            await_fut(vc.disconnect())
            if self.dead is not None:
                self.kill()
            return
        if not hasattr(vc, "channel"):
            self.dead = True
            return
        m = guild.me
        if m is None:
            self.dead = True
            return
        q = self.queue
        if not vc.is_playing():
            try:
                if q and not self.pausec and self.source is not None:
                    vc.play(self, after=self.update)
                self.att = 0
            except (RuntimeError, discord.ClientException):
                pass
            except:
                if getattr(self, "att", 0) <= 0:
                    print_exc()
                    await_fut(vc.disconnect())
                    self.att = utc()
                elif utc() - self.att > 10:
                    self.dead = True
                    return
                await_fut(self.reconnect())
        if self.stats.stay:
            cnt = inf
        else:
            cnt = sum(1 for m in vc.channel.members if not m.bot)
        if not cnt:
            # Timeout for leaving is 20 seconds
            if self.timeout < utc() - 20:
                self.dead = True
                return
            # If idle for more than 10 seconds, attempt to find members in other voice channels
            elif self.timeout < utc() - 10:
                if guild.afk_channel is not None:
                    if guild.afk_channel.id != vc.channel.id:
                        await_fut(self.move_unmute(vc, guild.afk_channel))
                    else:
                        cnt = 0
                        ch = None
                        for channel in guild.voice_channels:
                            if channel.id != guild.afk_channel.id:
                                c = sum(1 for m in channel.members if not m.bot)
                                if c > cnt:
                                    cnt = c
                                    ch = channel
                        if ch:
                            with tracebacksuppressor(SemaphoreOverflowError):
                                await_fut(vc.move_to(ch))
                                self.announce(ini_md(f"🎵 Detected {sqr_md(cnt)} user{'s' if cnt != 1 else ''} in {sqr_md(ch)}, automatically joined! 🎵"), sync=True)
        else:
            self.timeout = utc()
        if m.voice is not None:
            if m.voice.deaf or m.voice.mute or m.voice.afk:
                await_fut(m.edit(mute=False, deafen=False))
        # Attempt to reconnect if not connected, otherwise update queue
        if not (vc.is_connected() or self.bot.data.audio.is_connecting(vc.guild.id)):
            await_fut(self.reconnect())
        else:
            self.att = 0
        self.queue.update_load()

    # Moves to the target channel, unmuting self afterwards.
    async def move_unmute(self, vc, channel):
        await vc.move_to(channel)
        await channel.guild.me.edit(mute=False, deafen=False)

    async def smart_connect(self, channel=None):
        if hasattr(self, "dead"):
            self.bot.data.audio.connecting.pop(channel.guild.id, None)
            return
        if not self.vc.is_connected():
            guild = channel.guild
            member = guild.me
            if member is None:
                self.dead = True
                raise RuntimeError("Audio player not associated with guild.")
            if guild.voice_client is not None:
                self.vc = guild.voice_client
                if channel is not None:
                    await self.vc.move_to(channel)
                if not self.vc.is_connected():
                    await self.vc.connect(reconnect=True, timeout=7)
                return self.vc
            if member.voice is not None:
                if channel is None:
                    channel = member.voice.channel
                await member.move_to(None)
        if channel is None:
            return self.vc
        try:
            for i in range(5):
                if hasattr(self, "dead"):
                    break
                with suppress(asyncio.TimeoutError, discord.ConnectionClosed):
                    return await channel.connect(timeout=6, reconnect=False)
                await asyncio.sleep(2)
            raise TimeoutError
        except:
            self.dead = True
            raise

    async def set_voice_client(self, channel):
        voice_client = await self.smart_connect(channel)
        self.vc = voice_client
        self.bot.data.audio.connecting.pop(voice_client.guild.id, None)
        if not self.queue and self.vc.is_playing():
            self.vc.pause()
        return voice_client

    # Attempts to reconnect to a voice channel that was removed. Gives up if unable to rejoin within 60 seconds.
    async def reconnect(self):
        try:
            if hasattr(self, "dead") or self.vc.is_connected():
                return
            self.bot.data.audio.connecting[self.vc.guild.id] = utc()
            if getattr(self, "att", 0) <= 0:
                self.att = utc()
            self.vc = await self.smart_connect(self.vc.channel)
            user = self.vc.guild.me
            if getattr(user, "voice", None) is not None:
                if user.voice.deaf or user.voice.mute or user.voice.afk:
                    create_task(user.edit(mute=False, deafen=False))
            self.att = 0
        except discord.Forbidden:
            print_exc()
            self.dead = True
        except discord.ClientException:
            self.att = utc()
        except:
            print_exc()
            if getattr(self, "att", 0) > 0 and utc() - self.att > 60:
                self.dead = True
        self.bot.data.audio.connecting.pop(self.vc.guild.id, None)

    # Updates audio player messages.
    async def update_player(self):
        curr = self.player
        self.stats.quiet &= -3
        if curr is not None:
            if curr.type:
                self.stats.quiet |= 2
            try:
                if not curr.message.content and not curr.message.embeds:
                    raise EOFError
            except:
                self.player = None
                print_exc()
            if utc() > curr.time:
                curr.time = inf
                try:
                    await self.bot.react_callback(curr.message, "❎", self.bot.user)
                except discord.NotFound:
                    self.player = None
                    print_exc()
        q = self.stats.quiet
        if q == bool(q):
            self.stats.quiet = bool(q)

    # Constructs array of FFmpeg options using the audio settings.
    def construct_options(self, full=True):
        stats = self.stats
        # Pitch setting is in semitones, so frequency is on an exponential scale
        pitchscale = 2 ** ((stats.pitch + stats.resample) / 12)
        chorus = min(16, abs(stats.chorus))
        reverb = stats.reverb
        volume = stats.volume
        # FIR sample for reverb
        if reverb:
            args = ["-i", "misc/SNB3,0all.wav"]
        else:
            args = []
        options = deque()
        # This must be first, else the filter will not initialize properly
        if not is_finite(stats.compressor):
            options.extend(("anoisesrc=a=.001953125:c=brown", "amerge"))
        # Reverses song, this may be very resource consuming
        if self.reverse:
            options.append("areverse")
        # Adjusts song tempo relative to speed, pitch, and nightcore settings
        if pitchscale != 1 or stats.speed != 1:
            speed = abs(stats.speed) / pitchscale
            speed *= 2 ** (stats.resample / 12)
            if round(speed, 9) != 1:
                speed = max(0.005, speed)
                if speed >= 64:
                    raise OverflowError
                opts = ""
                while speed > 3:
                    opts += "atempo=3,"
                    speed /= 3
                while speed < 0.5:
                    opts += "atempo=0.5,"
                    speed /= 0.5
                opts += "atempo=" + str(speed)
                options.append(opts)
        # Adjusts resample to match song pitch
        if pitchscale != 1:
            if abs(pitchscale) >= 64:
                raise OverflowError
            if full:
                options.append("aresample=" + str(SAMPLE_RATE))
            options.append("asetrate=" + str(SAMPLE_RATE * pitchscale))
        # Chorus setting, this is a bit of a mess
        if chorus:
            A = B = C = D = ""
            for i in range(ceil(chorus)):
                neg = ((i & 1) << 1) - 1
                i = 1 + i >> 1
                i *= stats.chorus / ceil(chorus)
                if i:
                    A += "|"
                    B += "|"
                    C += "|"
                    D += "|"
                delay = (25 + i * tau * neg) % 39 + 18
                A += str(round(delay, 3))
                decay = (0.125 + i * 0.03 * neg) % 0.25 + 0.25
                B += str(round(decay, 3))
                speed = (2 + i * 0.61 * neg) % 4.5 + 0.5
                C += str(round(speed, 3))
                depth = (i * 0.43 * neg) % max(4, stats.chorus) + 0.5
                D += str(round(depth, 3))
            b = 0.5 / sqrt(ceil(chorus + 1))
            options.append(
                "chorus=0.5:" + str(round(b, 3)) + ":"
                + A + ":"
                + B + ":"
                + C + ":"
                + D
            )
            volume *= 2
        # Compressor setting, this needs a bit of tweaking perhaps
        if stats.compressor:
            comp = min(8000, abs(stats.compressor * 10 + sgn(stats.compressor)))
            while abs(comp) > 1:
                c = min(20, comp)
                try:
                    comp /= c
                except ZeroDivisionError:
                    comp = 1
                mult = str(round((c * math.sqrt(2)) ** 0.5, 4))
                options.append(
                    "acompressor=mode=" + ("upward" if stats.compressor < 0 else "downward")
                    + ":ratio=" + str(c) + ":level_in=" + mult + ":threshold=0.0625:makeup=" + mult
                )
        # Bassboost setting, the ratio is currently very unintuitive and definitely needs tweaking
        if stats.bassboost:
            opt = "anequalizer="
            width = 4096
            x = round(sqrt(1 + abs(stats.bassboost)), 5)
            coeff = width * max(0.03125, (0.25 / x))
            ch = " f=" + str(coeff if stats.bassboost > 0 else width - coeff) + " w=" + str(coeff / 2) + " g=" + str(max(0.5, min(48, 4 * math.log2(x * 5))))
            opt += "c0" + ch + "|c1" + ch
            options.append(opt)
        # Reverb setting, using afir and aecho FFmpeg filters.
        if reverb:
            coeff = abs(reverb)
            wet = min(3, coeff) / 3
            # Split audio into 2 inputs if wet setting is between 0 and 1, one input passes through FIR filter
            if wet != 1:
                options.append("asplit[2]")
            volume *= 1.2
            options.append("afir=dry=10:wet=10")
            # Must include amix if asplit is used
            if wet != 1:
                dry = 1 - wet
                options.append("[2]amix=weights=" + str(round(dry, 6)) + " " + str(round(wet, 6)))
            if coeff > 1:
                decay = str(round(1 - 4 / (3 + coeff), 4))
                options.append("aecho=1:1:479|613:" + decay + "|" + decay)
                if not is_finite(coeff):
                    options.append("aecho=1:1:757|937:1|1")
        # Pan setting, uses extrastereo and volume filters to balance
        if stats.pan != 1:
            pan = min(10000, max(-10000, stats.pan))
            while abs(abs(pan) - 1) > 0.001:
                p = max(-10, min(10, pan))
                try:
                    pan /= p
                except ZeroDivisionError:
                    pan = 1
                options.append("extrastereo=m=" + str(p) + ":c=0")
                volume *= 1 / max(1, round(math.sqrt(abs(p)), 4))
        if volume != 1:
            options.append("volume=" + str(round(volume, 7)))
        # Soft clip audio using atan, reverb filter requires -filter_complex rather than -af option
        if options:
            if stats.compressor:
                options.append("alimiter")
            elif volume > 1:
                options.append("asoftclip=atan")
            args.append(("-af", "-filter_complex")[bool(reverb)])
            args.append(",".join(options))
        # print(args)
        return args

    # Reads from source, selecting appropriate course of action upon hitting EOF
    def read(self):
        try:
            found = empty = False
            if self.queue.loading or self.paused:
                self.is_playing = True
                raise EOFError
            try:
                source = self.source
                if source is None:
                    raise StopIteration
                temp = source.read()
                if not temp:
                    raise StopIteration
                found = True
            except (StopIteration, ValueError):
                empty = True
                raise EOFError
            except:
                empty = True
                print_exc()
                raise EOFError
            if not empty:
                self.stats.position = round(
                    self.stats.position + self.speed / 50 * (self.reverse * -2 + 1),
                    4,
                )
                self.has_read = True
                self.curr_timeout = 0
            self.is_playing = True
        except EOFError:
            if self.source is not None and self.source.closed:
                self.source = None
            if (empty or not self.paused) and not self.queue.loading:
                queueable = (self.queue or self.bot.data.playlists.get(self.vc.guild.id, None))
                # Advance queue if nothing is playing but there are songs to load
                if self.queue and not self.queue[0].get("played", False):
                    if not found and not self.queue.loading:
                        if self.source is not None:
                            self.source.advanced = True
                        create_future_ex(self.queue.advance, timeout=120)
                # If there is a source to read from, update the queue
                elif empty and queueable and self.source is not None:
                    if utc() - self.last_end > 0.5:
                        if self.reverse:
                            ended = self.stats.position <= 0.5
                        else:
                            ended = ceil(self.stats.position) >= e_dur(self.queue[0].duration) - 0.5
                        if self.curr_timeout and utc() - self.curr_timeout > 0.5 or ended:
                            if not found:
                                self.last_end = utc()
                                if not self.has_read or not self.queue:
                                    if self.queue:
                                        self.queue[0].url = ""
                                    self.source.advanced = True
                                    create_future_ex(self.queue.update_play, timeout=120)
                                    self.preparing = False
                                else:
                                    self.source.advanced = True
                                    create_future_ex(self.queue.update_play, timeout=120)
                                    self.preparing = False
                        elif self.curr_timeout == 0:
                            self.curr_timeout = utc()
                # If there is nothing to play, stop the audio player
                elif (empty and not queueable) or self.pausec:
                    self.curr_timeout = 0
                    self.vc.stop()
            temp = self.emptyopus
            self.pausec = self.paused & 1
        else:
            self.pausec = False
        return temp

    # For compatibility with discord.AudioSource
    is_opus = lambda self: True
    cleanup = lambda self: None


# Manages the audio queue. Has optimized insertion/removal on both ends, and linear time lookup. One instance of this class is created per audio player.
class AudioQueue(alist):

    maxitems = 262144
        
    def _init_(self, auds):
        self.auds = auds
        self.bot = auds.bot
        self.vc = auds.vc
        self.lastsent = 0
        self.loading = False
        self.playlist = None

    # Update queue, loading all file streams that would be played soon
    def update_load(self):
        q = self
        if q:
            dels = deque()
            for i, e in enumerate(q):
                if i >= len(q) or i > 8191:
                    break
                if i < 2:
                    if not e.get("stream", None):
                        if not i:
                            callback = self.update_play
                        else:
                            callback = None
                        create_future_ex(ytdl.get_stream, e, callback=callback, timeout=90)
                        break
                if "file" in e:
                    e["file"].ensure_time()
                if not e.url:
                    if not self.auds.stats.quiet:
                        self.auds.announce(ini_md(f"A problem occured while loading {sqr_md(e.name)}, and it has been automatically removed from the queue."))
                    dels.append(i)
                    continue
            q.pops(dels)
            self.advance(process=False)
        create_task(self.auds.update_player())

    # Advances queue when applicable, taking into account loop/repeat/shuffle settings.
    def advance(self, looped=True, repeated=True, shuffled=True, process=True):
        q = self
        s = self.auds.stats
        if q and process:
            if q[0].get("played"):
                # Remove played status from queue entry
                q[0].pop("played")
                if not (s.repeat and repeated):
                    if s.loop:
                        temp = q[0]
                    q.popleft()
                    if s.shuffle and shuffled:
                        if len(q) > 1:
                            temp = q.popleft()
                            shuffle(q)
                            q.appendleft(temp)
                    if s.loop and looped:
                        q.append(temp)
                if self.auds.player:
                    self.auds.player.time = 1 + utc()
        # If no queue entries found but there is a default playlist assigned, load a random entry from that
        if not (q or self.auds.preparing):
            if not self.playlist:
                t = self.bot.data.playlists.get(self.vc.guild.id, ())
                if t:
                    self.playlist = shuffle(t)
            if self.playlist:
                p = self.playlist.pop()
                e = cdict(p)
                e.u_id = self.bot.id
                e.skips = ()
                e.stream = ytdl.get_stream(e)
                q.appendleft(e)
        self.update_play()

    # Updates next queue entry and starts loading/playing it if possible
    def update_play(self):
        auds = self.auds
        q = self
        if q:
            entry = q[0]
            # Only start loading a new source if there is one to be found and none is already loading/playing
            if (auds.source is None or auds.source.closed or auds.source.advanced) and not entry.get("played", False):
                if entry.get("file", None) or entry.get("stream", None) not in (None, "none"):
                    entry.played = True
                    if not auds.stats.quiet:
                        if utc() - self.lastsent > 1:
                            try:
                                u = self.bot.cache.users[entry.u_id]
                                name = u.display_name
                            except KeyError:
                                name = "Deleted User"
                            self.lastsent = utc()
                            auds.announce(italics(ini_md(f"🎵 Now playing {sqr_md(q[0].name)}, added by {sqr_md(name)}! 🎵")), sync=False)
                    self.loading = True
                    try:
                        # Gets audio file stream and loads into audio source object
                        source = ytdl.get_stream(entry, force=True)
                        auds.new(source)
                        self.loading = False
                        auds.ensure_play()
                    except:
                        print(entry)
                        print(source)
                        self.loading = False
                        print_exc()
                        raise
                    auds.preparing = False
            # Advance queue if there is nothing playing and the current song has already been played
            elif auds.source is None and not self.loading and not auds.preparing:
                self.advance()
            elif auds.source is not None and auds.source.advanced:
                auds.source.advanced = False
                auds.source.closed = True
                self.advance()
        else:
            # Stop audio player if there is nothing to play
            if auds.source is None or auds.source.closed or auds.source.advanced:
                auds.vc.stop()
                auds.source = None

    def verify(self):
        if len(self) > self.maxitems + 2048:
            self.__init__(self[1 - self.maxitems:].appendleft(self[0]), fromarray=True)
        elif len(self) > self.maxitems:
            self.rotate(-1)
            while len(self) > self.maxitems:
                self.pop()
            self.rotate(1)
        return self

    # Enqueue items at target position, starting audio playback if queue was previously empty.
    def enqueue(self, items, position):
        with self.auds.semaphore:
            if len(items) > self.maxitems:
                items = items[:self.maxitems]
            if not self:
                self.__init__(items)
                self.auds.source = None
                create_future_ex(self.update_load, timeout=120)
                return self
            if position == -1:
                self.extend(items)
            else:
                self.rotate(-position)
                self.extend(items)
                self.rotate(len(items) + position)
            return self.verify()


# runs org2xm on a file, with an optional custom sample bank.
def org2xm(org, dat=None):
    if os.name != "nt":
        raise OSError("org2xm is only available on Windows.")
    if not org or type(org) is not bytes:
        if not is_url(org):
            raise TypeError("Invalid input URL.")
        org = verify_url(org)
        data = Request(org)
        if not data:
            raise FileNotFoundError("Error downloading file content.")
    else:
        if not org.startswith(b"Org-"):
            raise ValueError("Invalid file header.")
        data = org
    # Set compatibility option if file is not of org2 format.
    compat = not data.startswith(b"Org-02")
    ts = ts_us()
    # Write org data to file.
    r_org = "cache/" + str(ts) + ".org"
    with open(r_org, "wb") as f:
        f.write(data)
    r_dat = "cache/" + str(ts) + ".dat"
    orig = False
    # Load custom sample bank if specified
    if dat is not None and is_url(dat):
        dat = verify_url(dat)
        with open(r_dat, "wb") as f:
            dat = Request(dat)
            f.write(dat)
    else:
        if type(dat) is bytes and dat:
            with open(r_dat, "wb") as f:
                f.write(dat)
        else:
            r_dat = "misc/ORG210EN.DAT"
            orig = True
    args = ["misc/org2xm.exe", r_org, r_dat]
    if compat:
        args.append("c")
    subprocess.check_output(args)
    r_xm = f"cache/{ts}.xm"
    if not os.path.exists("cache/" + str(ts) + ".xm"):
        raise FileNotFoundError("Unable to locate converted file.")
    if not os.path.getsize(r_xm):
        raise RuntimeError("Converted file is empty.")
    for f in (r_org, r_dat)[:2 - orig]:
        with suppress():
            os.remove(f)
    return r_xm


def mid2mp3(mid):
    url = Request(
        "https://hostfast.onlineconverter.com/file/send",
        files={
            "class": (None, "audio"),
            "from": (None, "midi"),
            "to": (None, "mp3"),
            "source": (None, "file"),
            "file": mid,
            "audio_quality": (None, "192"),
        },
        method="post",
        decode=True,
    )
    print(url)
    fn = url.rsplit("/", 1)[-1].strip("\x00")
    for i in range(360):
        with delay(1):
            test = Request(f"https://hostfast.onlineconverter.com/file/{fn}")
            if test == b"d":
                break
    ts = ts_us()
    r_mp3 = f"cache/{ts}.mp3"
    with open(r_mp3, "wb") as f:
        f.write(Request(f"https://hostfast.onlineconverter.com/file/{fn}/download"))
    return r_mp3


CONVERTERS = {
    b"MThd": mid2mp3,
    b"Org-": org2xm,
}

def select_and_convert(stream):
    with requests.get(stream, timeout=8, stream=True) as resp:
        it = resp.iter_content(4096)
        b = bytes()
        while len(b) < 4:
            b += next(it)
        try:
            convert = CONVERTERS[b[:4]]
        except KeyError:
            raise ValueError("Invalid file header.")
        b += resp.content
    return convert(b)


# Represents a cached audio file in opus format. Executes and references FFmpeg processes loading the file.
class AudioFile:

    live = False
    
    def __init__(self, fn, stream=None):
        self.file = fn
        self.proc = None
        self.stream = stream
        self.wasfile = False
        self.loading = False
        self.expired = False
        self.buffered = False
        self.loaded = False
        self.readers = cdict()
        self.assign = deque()
        self.semaphore = Semaphore(1, 1, delay=5)
        self.ensure_time()
        self.webpage_url = None

    def __str__(self):
        classname = str(self.__class__).replace("'>", "")
        classname = classname[classname.index("'") + 1:]
        return f"<{classname} object at {hex(id(self)).upper().replace('X', 'x')}>"
    
    def load(self, stream=None, check_fmt=False, force=False, webpage_url=None, live=False):
        if live:
            self.loading = self.buffered = self.loaded = True
            self.live = self.stream = stream
            self.proc = None
            return self
        if self.loading and not force:
            return self
        if stream is not None:
            self.stream = stream
        stream = self.stream
        if webpage_url is not None:
            self.webpage_url = webpage_url
        self.loading = True
        # Collects data from source, converts to 48khz 192kbps opus format, outputting to target file
        cmd = ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-vn", "-i", stream, "-map_metadata", "-1", "-f", "opus", "-c:a", "libopus", "-ar", str(SAMPLE_RATE), "-ac", "2", "-b:a", "196608", "cache/" + self.file]
        if "https://cf-hls-media.sndcdn.com/" not in stream:
            with suppress():
                fmt = as_str(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "default=nokey=1:noprint_wrappers=1", stream])).strip()
                if fmt == "opus":
                    cmd = ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-vn", "-i", stream, "-map_metadata", "-1", "-c:a", "copy", "cache/" + self.file]
        self.proc = None
        try:
            try:
                self.proc = psutil.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            except:
                print(cmd)
                raise
            fl = 0
            # Attempt to monitor status of output file
            while fl < 4096:
                with delay(0.1):
                    if not self.proc.is_running():
                        err = as_str(self.proc.stderr.read())
                        if self.webpage_url and ("Server returned 5XX Server Error reply" in err or "Server returned 404 Not Found" in err or "Server returned 403 Forbidden" in err):
                            with tracebacksuppressor:
                                if "https://cf-hls-media.sndcdn.com/" in stream:
                                    entry = ytdl.extract_from(self.webpage_url)
                                else:
                                    entry = ytdl.extract_backup(self.webpage_url)
                                print(err)
                                return self.load(get_best_audio(entry), check_fmt=False, force=True)
                        if check_fmt:
                            new = None
                            with suppress(ValueError):
                                new = select_and_convert(stream)
                            if new is not None:
                                return self.load(new, check_fmt=False, force=True)
                        print(self.proc.args)
                        if err:
                            ex = RuntimeError(err)
                        else:
                            ex = RuntimeError("FFmpeg did not start correctly, or file was too small.")
                        raise ex
                try:
                    fl = os.path.getsize("cache/" + self.file)
                except FileNotFoundError:
                    fl = 0
            self.buffered = True
            self.ensure_time()
            # print(self.file, "buffered", fl)
        except:
            # File errored, remove from cache and kill corresponding FFmpeg process if possible
            ytdl.cache.pop(self.file, None)
            if self.proc is not None:
                with suppress():
                    self.proc.kill()
            with suppress():
                os.remove("cache/" + self.file)
            raise
        return self

    # Touch the file to update its cache time.
    ensure_time = lambda self: setattr(self, "time", utc())

    # Update event run on all cached files
    def update(self):
        if not self.live:
            # Newly loaded files have their duration estimates copied to all queue entries containing them
            if self.loaded:
                if not self.wasfile:
                    dur = self.duration()
                    if dur is not None:
                        for e in self.assign:
                            e["duration"] = dur
                        self.assign.clear()
            # Check when file has been fully loaded
            elif self.buffered and not self.proc.is_running():
                if not self.loaded:
                    self.loaded = True
                    if not is_url(self.stream):
                        retry(os.remove, self.stream, attempts=3, delay=0.5)
                    try:
                        fl = os.path.getsize("cache/" + self.file)
                    except FileNotFoundError:
                        fl = 0
                    # print(self.file, "loaded", fl)
            # Touch file if file is currently in use
        if self.readers:
            self.ensure_time()
            return
        # Remove any unused file that has been left for a long time
        if utc() - self.time > 24000:
            try:
                fl = os.path.getsize("cache/" + self.file)
            except FileNotFoundError:
                fl = 0
                if self.buffered:
                    self.time = -inf
            ft = 24000 / (math.log2(fl / 16777216 + 1) + 1)
            if ft > 86400:
                ft = 86400
            if utc() - self.time > ft:
                self.destroy()

    # Creates a reader object that either reads bytes or opus packets from the file.
    def open(self):
        self.ensure_time()
        if self.proc is None:
            raise ProcessLookupError
        f = open("cache/" + self.file, "rb")
        it = discord.oggparse.OggStream(f).iter_packets()

        # For compatibility with other audio readers
        reader = cdict(file=f, read=lambda: next(it), _read = f.read, closed=False, advanced=False, is_opus=lambda: True)

        def close():
            reader.closed = True
            reader.file.close()

        reader.close = reader.cleanup = close
        return reader

    # Destroys the file object, killing associated FFmpeg process and removing from cache.
    def destroy(self):
        self.expired = True
        if self.proc and self.proc.is_running():
            with suppress():
                self.proc.kill()
        with suppress():
            with self.semaphore:
                if not self.live:
                    retry(os.remove, "cache/" + self.file, attempts=8, delay=5, exc=(FileNotFoundError,))
                # File is removed from cache data
                ytdl.cache.pop(self.file, None)
                # print(self.file, "deleted.")

    # Creates a reader, selecting from direct opus file, single piped FFmpeg, or double piped FFmpeg.
    def create_reader(self, pos=0, auds=None):
        if self.live:
            source = self.live
        else:
            source = "cache/" + self.file
            if not os.path.exists(source):
                t = utc()
                while utc() - t < 10 and not self.stream:
                    time.sleep(0.1)
                self.load(force=True)
        stats = auds.stats
        auds.reverse = stats.speed < 0
        if auds.speed < 0.005:
            auds.speed = 1
            auds.paused |= 2
        else:
            auds.paused &= -3
        stats.position = pos
        if not is_finite(stats.pitch * stats.speed):
            raise OverflowError("Speed setting out of range.")
        # Construct FFmpeg options
        options = auds.construct_options(full=self.live)
        if options or auds.reverse or pos or auds.stats.bitrate != 1966.08 or self.live:
            args = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
            if pos and not self.live:
                arg = "-to" if auds.reverse else "-ss"
                args += [arg, str(pos)]
            args.append("-i")
            if self.loaded:
                buff = False
                args.insert(1, "-nostdin")
                args.append(source)
            else:
                buff = True
                args.append("pipe:0")
            if options or auds.stats.bitrate != 1966.08:
                br = 100 * auds.stats.bitrate
                sr = SAMPLE_RATE
                while br < 4096:
                    br *= 2
                    sr >>= 1
                if sr < 8000:
                    sr = 8000
                options.extend(("-f", "opus", "-c:a", "libopus", "-ar", str(sr), "-ac", "2", "-b:a", str(round_min(br)), "-bufsize", "8192"))
                if options:
                    args.extend(options)
            else:
                args.extend(("-f", "opus"))
                if not self.live:
                    args.extend(("-c:a", "copy"))
            args.append("pipe:1")
            key = auds.vc.guild.id
            self.readers[key] = True
            callback = lambda: self.readers.pop(key, None)
            if buff:
                while not self.buffered and not self.expired:
                    time.sleep(0.1)
                # Select buffered reader for files not yet fully loaded, convert while downloading
                player = BufferedAudioReader(self, args, callback=callback)
            else:
                # Select loaded reader for loaded files
                player = LoadedAudioReader(self, args, callback=callback)
            auds.args = args
            return player.start()
        # Select raw file stream for direct audio playback
        auds.args.clear()
        return self.open()

    # Audio duration estimation: Get values from file if possible, otherwise URL
    duration = lambda self: inf if self.live else self.dur if getattr(self, "dur", None) is not None else set_dict(self.__dict__, "dur", get_duration("cache/" + self.file) if self.loaded else get_duration(self.stream), ignore=True)


# Audio reader for fully loaded files. FFmpeg with single pipe for output.
class LoadedAudioReader(discord.AudioSource):

    def __init__(self, file, args, callback=None):
        self.closed = False
        self.advanced = False
        self.args = args
        self.proc = psutil.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        self.packet_iter = discord.oggparse.OggStream(self.proc.stdout).iter_packets()
        self.file = file
        self.buffer = None
        self.callback = callback
    
    def read(self):
        if self.buffer:
            b, self.buffer = self.buffer, None
            return b
        for att in range(16):
            try:
                return next(self.packet_iter)
            except OSError:
                self.proc = psutil.Popen(self.args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
                self.packet_iter = discord.oggparse.OggStream(self.proc.stdout).iter_packets()
    
    def start(self):
        self.buffer = None
        with tracebacksuppressor():
            self.buffer = self.read()
        return self

    def close(self, *void1, **void2):
        self.closed = True
        with suppress():
            self.proc.kill()
        if callable(self.callback):
            self.callback()

    is_opus = lambda self: True
    cleanup = close


# Audio player for audio files still being written to. Continuously reads and sends data to FFmpeg process, only terminating when file download is confirmed to be finished.
class BufferedAudioReader(discord.AudioSource):

    def __init__(self, file, args, callback=None):
        self.closed = False
        self.advanced = False
        self.proc = psutil.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.packet_iter = discord.oggparse.OggStream(self.proc.stdout).iter_packets()
        self.file = file
        self.stream = file.open()
        self.buffer = None
        self.callback = callback
        self.full = False

    def read(self):
        if self.buffer:
            b, self.buffer = self.buffer, None
            return b
        return next(self.packet_iter)

    # Required loop running in background to feed data to FFmpeg
    def run(self):
        while not self.file.buffered and not self.closed:
            time.sleep(0.1)
        while True:
            b = bytes()
            try:
                b = self.stream._read(65536)
                if not b:
                    raise EOFError
                self.proc.stdin.write(b)
                self.proc.stdin.flush()
            except (ValueError, EOFError):
                # Only stop when file is confirmed to be finished
                if self.file.loaded or self.closed:
                    break
                time.sleep(0.1)
        self.full = True
        self.proc.stdin.close()
    
    def start(self):
        # Run loading loop in parallel thread obviously
        create_future_ex(self.run, timeout=86400)
        self.buffer = None
        with tracebacksuppressor():
            self.buffer = self.read()
        return self

    def close(self):
        self.closed = True
        with suppress():
            self.stream.close()
        with suppress():
            self.proc.kill()
        if callable(self.callback):
            self.callback()

    is_opus = lambda self: True
    cleanup = close


# Manages all audio searching and downloading.
class AudioDownloader:
    
    _globals = globals()
    ydl_opts = {
        # "verbose": 1,
        "quiet": 1,
        "format": "bestaudio/best",
        "nocheckcertificate": 1,
        "no_call_home": 1,
        "nooverwrites": 1,
        "noplaylist": 1,
        "logtostderr": 0,
        "ignoreerrors": 0,
        "default_search": "auto",
        "source_address": "0.0.0.0",
    }
    youtube_x = 0
    youtube_dl_x = 0
    spotify_x = 0
    other_x = 0

    def __init__(self):
        self.bot = None
        self.lastclear = 0
        self.downloading = cdict()
        self.cache = cdict()
        self.searched = cdict()
        self.semaphore = Semaphore(4, 128, delay=0.25)
        self.update_dl()
        self.setup_pages()

    # Fetches youtube playlist page codes, split into pages of 50 items
    def setup_pages(self):
        with open("misc/page_tokens.txt", "r", encoding="utf-8") as f:
            s = f.read()
        page10 = s.splitlines()
        self.yt_pages = {i * 10: page10[i] for i in range(len(page10))}
        # self.yt_pages = [page10[i] for i in range(0, len(page10), 5)]

    # Initializes youtube_dl object as well as spotify tokens, every 720 seconds.
    def update_dl(self):
        if utc() - self.lastclear > 720:
            self.lastclear = utc()
            with tracebacksuppressor:
                self.youtube_dl_x += 1
                self.downloader = youtube_dl.YoutubeDL(self.ydl_opts)
                self.spotify_x += 1
                token = await_fut(aretry(Request, "https://open.spotify.com/get_access_token", aio=True, attempts=8, delay=0.5))
                self.spotify_header = {"authorization": f"Bearer {json.loads(token[:512])['accessToken']}"}
                self.other_x += 1
                resp = Request("https://keepv.id/", timeout=16)
                search = b"<script>apikey='"
                resp = resp[resp.rindex(search) + len(search):]
                search = b";sid='"
                resp = resp[resp.index(search) + len(search):]
                self.keepvid_token = as_str(resp[:resp.index(b"';</script>")])

    # Gets data from yt-download.org, keepv.id, or y2mate.guru, adjusts the format to ensure compatibility with results from youtube-dl. Used as backup.
    def extract_backup(self, url, video=False):
        url = verify_url(url)
        if is_url(url) and not is_youtube_url(url):
            raise TypeError("Not a youtube link.")
        excs = alist()
        if ":" in url:
            url = url.rsplit("/", 1)[-1].split("v=", 1)[-1].split("&", 1)[0]
        webpage_url = f"https://www.youtube.com/watch?v={url}"
        resp = None
        try:
            yt_url = f"https://www.yt-download.org/file/mp3/{url}"
            if video:
                v_url = f"https://www.yt-download.org/file/mp4/{url}"
                self.other_x += 1
                fut = create_future_ex(Request, v_url, timeout=16)
            self.other_x += 1
            resp = Request(yt_url, timeout=16)
            search = b'<img class="h-20 w-20 md:h-48 md:w-48 mt-0 md:mt-12 lg:mt-0 rounded-full mx-auto md:mx-0 md:mr-6" src="'
            resp = resp[resp.index(search) + len(search):]
            thumbnail = as_str(resp[:resp.index(b'"')])
            search = b'<h2 class="text-lg text-teal-600 font-bold m-2 text-center">'
            resp = resp[resp.index(search) + len(search):]
            title = html_decode(as_str(resp[:resp.index(b"</h2>")]))
            resp = resp[resp.index(f'<a href="https://www.yt-download.org/download/{url}/mp3/192'.encode("utf-8")) + 9:]
            stream = as_str(resp[:resp.index(b'"')])
            resp = resp[:resp.index(b"</a>")]
            search = b'<div class="text-shadow-1">'
            fs = parse_fs(resp[resp.rindex(search) + len(search):resp.rindex(b"</div>")])
            dur = fs / 192000 * 8
            entry = {
                "formats": [
                    {
                        "abr": 192,
                        "url": stream,
                    },
                ],
                "duration": dur,
                "thumbnail": thumbnail,
                "title": title,
                "webpage_url": webpage_url,
            }
            if video:
                with tracebacksuppressor:
                    resp = fut.result()
                    while True:
                        try:
                            resp = resp[resp.index(f'<a href="https://www.yt-download.org/download/{url}/mp4/'.encode("utf-8")) + 9:]
                            stream = as_str(resp[:resp.index(b'"')])
                            search = b'<div class="text-shadow-1">'
                            height = int(resp[resp.rindex(search) + len(search):resp.rindex(b"</div>")].strip().rstrip("p"))
                        except ValueError:
                            break
                        else:
                            entry["formats"].append(dict(
                                abr=1,
                                url=stream,
                                height=height,
                            ))
            print("Successfully resolved with yt-download.")
            return entry
        except Exception as ex:
            if resp:
                excs.append(resp)
            excs.append(ex)
        try:
            self.other_x += 1
            resp = Request(
                "https://keepv.id/",
                headers={"Accept": "*/*", "Cookie": "PHPSESSID=" + self.keepvid_token, "X-Requested-With": "XMLHttpRequest"},
                data=(("url", webpage_url), ("sid", self.keepvid_token)),
                method="POST",
                timeout=16,
            )
            search = b'<h2 class="mb-3">'
            resp = resp[resp.index(search) + len(search):]
            title = html_decode(as_str(resp[:resp.index(b"</h3>")]))
            search = b'<img src="'
            resp = resp[resp.index(search) + len(search):]
            thumbnail = as_str(resp[:resp.index(b'"')])
            entry = {
                "formats": [],
                "thumbnail": thumbnail,
                "title": title,
                "webpage_url": webpage_url,
            }
            with suppress(ValueError):
                search = b"Download Video</a><br>"
                resp = resp[resp.index(search) + len(search):]
                search = b"Duration: "
                resp = resp[resp.index(search) + len(search):]
                entry["duration"] = dur = time_parse(as_str(resp[:resp.index(b"<br><br>")]))
            resp = resp[resp.index(b"<body>") + 6:]
            while resp:
                try:
                    search = b"<tr><td>"
                    resp = resp[resp.index(search) + len(search):]
                except ValueError:
                    break
                fmt = as_str(resp[:resp.index(b"</td>")])
                if not fmt:
                    form = {}
                elif "x" in fmt:
                    form = dict(zip(("width", "height"), (int(i) for i in fmt.split("x", 1))))
                else:
                    form = dict(abr=int(fmt.casefold().rstrip("kmgbps")))
                search = b' shadow vdlbtn" href="'
                resp = resp[resp.index(search) + len(search):]
                stream = resp[:resp.index(b'"')]
                form["url"] = stream
                entry["formats"].append(form)
            if not entry["formats"]:
                raise FileNotFoundError
            print("Successfully resolved with keepv.id.")
            return entry
        except Exception as ex:
            if resp:
                excs.append(resp)
            excs.append(ex)
        try:
            self.other_x += 1
            data = Request("https://y2mate.guru/api/convert", data={"url": webpage_url}, method="POST", json=True, timeout=16)
            meta = data["meta"]
            entry = {
                "formats": [
                    {
                        "height": stream.get("height", 0),
                        "abr": stream.get("quality", 0),
                        "url": stream["url"],
                    } for stream in data["url"] if "url" in stream and stream.get("audio")
                ],
                "thumbnail": data.get("thumb"),
                "title": meta["title"],
                "webpage_url": meta["source"],
            }
            if meta.get("duration"):
                entry["duration"] = time_parse(meta["duration"])
            if not entry["formats"]:
                raise FileNotFoundError
            print("Successfully resolved with y2mate.")
            return entry
        except Exception as ex:
            if resp:
                excs.append(resp)
            excs.append(ex)
            print(excs)
            raise

    # Returns part of a spotify playlist.
    def get_spotify_part(self, url):
        out = deque()
        self.spotify_x += 1
        d = Request(url, headers=self.spotify_header, json=True)
        with suppress(KeyError):
            d = d["tracks"]
        try:
            items = d["items"]
            total = d.get("total", 0)
        except KeyError:
            if "type" in d:
                items = (d,)
                total = 1
            else:
                items = []
        for item in items:
            try:
                track = item["track"]
            except KeyError:
                try:
                    track = item["episode"]
                except KeyError:
                    if "id" in item:
                        track = item
                    else:
                        continue
            name = track.get("name", track["id"])
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            dur = track.get("duration_ms")
            if dur:
                dur /= 1000
            temp = cdict(
                name=name,
                url="ytsearch:" + f"{name} ~ {artists}".replace(":", "-"),
                id=track["id"],
                duration=dur,
                research=True,
            )
            out.append(temp)
        return out, total

    # Returns part of a youtube playlist.
    def get_youtube_part(self, url):
        out = deque()
        self.youtube_x += 1
        d = Request(url, json=True)
        items = d["items"]
        total = d.get("pageInfo", {}).get("totalResults", 0)
        for item in items:
            try:
                snip = item["snippet"]
                v_id = snip["resourceId"]["videoId"]
            except KeyError:
                continue
            name = snip.get("title", v_id)
            url = f"https://www.youtube.com/watch?v={v_id}"
            temp = cdict(
                name=name,
                url=url,
                duration=None,
                research=True,
            )
            out.append(temp)
        return out, total

    # Returns a full youtube playlist.
    def get_youtube_playlist(self, p_id):
        out = deque()
        self.youtube_x += 1
        resp = Request(f"https://www.youtube.com/playlist?list={p_id}")
        try:
            search = b'window["ytInitialData"] = '
            try:
                resp = resp[resp.index(search) + len(search):]
            except ValueError:
                search = b"var ytInitialData = "
                resp = resp[resp.index(search) + len(search):]
            try:
                resp = resp[:resp.index(b'window["ytInitialPlayerResponse"] = null;')]
                resp = resp[:resp.rindex(b";")]
            except ValueError:
                try:
                    resp = resp[:resp.index(b";</script><title>")]
                except:
                    resp = resp[:resp.index(b';</script><link rel="')]
            data = eval_json(resp)
        except:
            print(resp)
            raise
        count = int(data["sidebar"]["playlistSidebarRenderer"]["items"][0]["playlistSidebarPrimaryInfoRenderer"]["stats"][0]["runs"][0]["text"].replace(",", ""))
        for part in data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]["content"]["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"][0]["playlistVideoListRenderer"]["contents"]:
            try:
                video = part["playlistVideoRenderer"]
            except KeyError:
                if "continuationItemRenderer" not in part:
                    print(part)
                continue
            v_id = video['videoId']
            try:
                dur = round_min(float(video["lengthSeconds"]))
            except (KeyError, ValueError):
                try:
                    dur = time_parse(video["lengthText"]["simpleText"])
                except KeyError:
                    dur = None
            temp = cdict(
                name=video["title"]["runs"][0]["text"],
                url=f"https://www.youtube.com/watch?v={v_id}",
                duration=dur,
                thumbnail=f"https://i.ytimg.com/vi/{v_id}/maxresdefault.jpg",
            )
            out.append(temp)
        if count > 100:
            url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50&key={google_api_key}&playlistId={p_id}"
            page = 50
            futs = deque()
            for curr in range(100, page * ceil(count / page), page):
                search = f"{url}&pageToken={self.yt_pages[curr]}"
                futs.append(create_future_ex(self.get_youtube_part, search))
            for fut in futs:
                out.extend(fut.result()[0])
        return out
    
    def ydl_errors(self, s):
        return not ("video unavailable" in s or "this video is not available" in s or "this video contains content from" in s or "this video has been removed" in s)

    # Repeatedly makes calls to youtube-dl until there is no more data to be collected.
    def extract_true(self, url):
        while not is_url(url):
            with suppress(NotImplementedError):
                return self.search_yt(regexp("ytsearch[0-9]*:").sub("", url, 1))[0]
            resp = self.extract_from(url)
            if "entries" in resp:
                resp = next(iter(resp["entries"]))
            if "duration" in resp and "formats" in resp:
                return resp
            try:
                url = resp["webpage_url"]
            except KeyError:
                try:
                    url = resp["url"]
                except KeyError:
                    url = resp["id"]
        if is_discord_url(url):
            title = url.split("?", 1)[0].rsplit("/", 1)[-1]
            if "." in title:
                title = title[:title.rindex(".")]
            return dict(url=url, name=title, direct=True)
        try:
            self.youtube_dl_x += 1
            entries = self.downloader.extract_info(url, download=False, process=True)
        except Exception as ex:
            s = str(ex).casefold()
            if type(ex) is not youtube_dl.DownloadError or self.ydl_errors(s):
                try:
                    entries = self.extract_backup(url)
                except (TypeError, youtube_dl.DownloadError):
                    raise FileNotFoundError("Unable to fetch audio data.")
            else:
                raise
        if "entries" in entries:
            entries = entries["entries"]
        else:
            entries = [entries]
        out = deque()
        for entry in entries:
            temp = cdict(
                name=entry["title"],
                url=entry["webpage_url"],
                duration=entry.get("duration"),
                stream=get_best_audio(entry),
                icon=get_best_icon(entry),
            )
            if not temp.duration:
                temp.research = True
            out.append(temp)
        return out

    # Extracts audio information from a single URL.
    def extract_from(self, url):
        if is_discord_url(url):
            title = url.split("?", 1)[0].rsplit("/", 1)[-1]
            if "." in title:
                title = title[:title.rindex(".")]
            return dict(url=url, webpage_url=url, title=title, direct=True)
        try:
            self.youtube_dl_x += 1
            return self.downloader.extract_info(url, download=False, process=False)
        except Exception as ex:
            s = str(ex).casefold()
            if type(ex) is not youtube_dl.DownloadError or self.ydl_errors(s):
                if is_url(url):
                    try:
                        return self.extract_backup(url)
                    except (TypeError, youtube_dl.DownloadError):
                        raise FileNotFoundError("Unable to fetch audio data.")
            raise

    # Extracts info from a URL or search, adjusting accordingly.
    def extract_info(self, item, count=1, search=False, mode=None):
        if (mode or search) and not item.startswith("ytsearch:") and not is_url(item):
            if count == 1:
                c = ""
            else:
                c = count
            item = item.replace(":", "-")
            if mode:
                self.youtube_dl_x += 1
                return self.downloader.extract_info(f"{mode}search{c}:{item}", download=False, process=False)
            exc = ""
            try:
                self.youtube_dl_x += 1
                return self.downloader.extract_info(f"ytsearch{c}:{item}", download=False, process=False)
            except Exception as ex:
                exc = repr(ex)
            try:
                self.youtube_dl_x += 1
                return self.downloader.extract_info(f"scsearch{c}:{item}", download=False, process=False)
            except Exception as ex:
                raise ConnectionError(exc + repr(ex))
        if is_url(item) or not search:
            return self.extract_from(item)
        self.youtube_dl_x += 1
        return self.downloader.extract_info(item, download=False, process=False)

    # Main extract function, able to extract from youtube playlists much faster than youtube-dl using youtube API, as well as ability to follow spotify links.
    def extract(self, item, force=False, count=1, mode=None, search=True):
        try:
            page = None
            output = deque()
            if google_api_key and ("youtube.com" in item or "youtu.be/" in item):
                p_id = None
                for x in ("?list=", "&list="):
                    if x in item:
                        p_id = item[item.index(x) + len(x):]
                        p_id = p_id.split("&", 1)[0]
                        break
                if p_id:
                    with tracebacksuppressor:
                        output.extend(self.get_youtube_playlist(p_id))
                        # Scroll to highlighted entry if possible
                        v_id = None
                        for x in ("?v=", "&v="):
                            if x in item:
                                v_id = item[item.index(x) + len(x):]
                                v_id = v_id.split("&", 1)[0]
                                break
                        if v_id:
                            for i, e in enumerate(output):
                                if v_id in e.url:
                                    output.rotate(-i)
                                    break
                        return output
            elif regexp("(play|open|api)\\.spotify\\.com").search(item):
                # Spotify playlist searches contain up to 100 items each
                if "playlist" in item:
                    url = item[item.index("playlist"):]
                    url = url[url.index("/") + 1:]
                    key = url.split("/", 1)[0]
                    url = f"https://api.spotify.com/v1/playlists/{key}/tracks?type=track,episode"
                    page = 100
                # Spotify album searches contain up to 50 items each
                elif "album" in item:
                    url = item[item.index("album"):]
                    url = url[url.index("/") + 1:]
                    key = url.split("/", 1)[0]
                    url = f"https://api.spotify.com/v1/albums/{key}/tracks?type=track,episode"
                    page = 50
                # Single track links also supported
                elif "track" in item:
                    url = item[item.index("track"):]
                    url = url[url.index("/") + 1:]
                    key = url.split("/", 1)[0]
                    url = f"https://api.spotify.com/v1/tracks/{key}"
                    page = 1
                else:
                    raise TypeError("Unsupported Spotify URL.")
                if page == 1:
                    output.extend(self.get_spotify_part(url)[0])
                else:
                    futs = deque()
                    maxitems = 10000
                    # Optimized searching with lookaheads
                    for i, curr in enumerate(range(0, maxitems, page)):
                        with delay(0.03125):
                            if curr >= maxitems:
                                break
                            search = f"{url}&offset={curr}&limit={page}"
                            fut = create_future_ex(self.get_spotify_part, search, timeout=90)
                            print("Sent 1 spotify search.")
                            futs.append(fut)
                            if not (i < 1 or math.log2(i + 1) % 1) or not i & 7:
                                while futs:
                                    fut = futs.popleft()
                                    res = fut.result()
                                    if not i:
                                        maxitems = res[1] + page
                                    if not res[0]:
                                        maxitems = 0
                                        futs.clear()
                                        break
                                    output += res[0]
                    while futs:
                        output.extend(futs.popleft().result()[0])
                    # Scroll to highlighted entry if possible
                    v_id = None
                    for x in ("?highlight=spotify:track:", "&highlight=spotify:track:"):
                        if x in item:
                            v_id = item[item.index(x) + len(x):]
                            v_id = v_id.split("&", 1)[0]
                            break
                    if v_id:
                        for i, e in enumerate(output):
                            if v_id == e.get("id"):
                                output.rotate(-i)
                                break
            # Only proceed if no items have already been found (from playlists in this case)
            if not len(output):
                # Allow loading of files output by ~dump
                if is_url(item):
                    url = verify_url(item)
                    if url[-5:] == ".json" or url[-4:] in (".txt", ".bin", ".zip"):
                        s = await_fut(self.bot.get_request(url))
                        d = select_and_loads(s, size=268435456)
                        q = d["queue"][:262144]
                        return [cdict(name=e["name"], url=e["url"], duration=e.get("duration")) for e in q]
                elif mode in (None, "yt"):
                    with suppress(NotImplementedError):
                        return self.search_yt(item)[:count]
                # Otherwise call automatic extract_info function
                resp = self.extract_info(item, count, search=search, mode=mode)
                if resp.get("_type", None) == "url":
                    resp = self.extract_from(resp["url"])
                if resp is None or not len(resp):
                    raise LookupError(f"No results for {item}")
                # Check if result is a playlist
                if resp.get("_type", None) == "playlist":
                    entries = list(resp["entries"])
                    if force or len(entries) <= 1:
                        for entry in entries:
                            # Extract full data if playlist only contains 1 item
                            try:
                                data = self.extract_from(entry["url"])
                            except KeyError:
                                temp = cdict({
                                    "name": resp["title"],
                                    "url": resp["webpage_url"],
                                    "duration": inf,
                                    "stream": get_best_audio(entry),
                                    "icon": get_best_icon(entry),
                                    "video": get_best_video(entry),
                                })
                            else:
                                temp = cdict({
                                    "name": data["title"],
                                    "url": data["webpage_url"],
                                    "duration": float(data["duration"]),
                                    "stream": get_best_audio(resp),
                                    "icon": get_best_icon(resp),
                                    "video": get_best_video(resp),
                                })
                            output.append(temp)
                    else:
                        for i, entry in enumerate(entries):
                            if not i:
                                # Extract full data from first item only
                                temp = self.extract(entry["url"], search=False)[0]
                            else:
                                # Get as much data as possible from all other items, set "research" flag to have bot lazily extract more info in background
                                with tracebacksuppressor:
                                    found = True
                                    if "title" in entry:
                                        title = entry["title"]
                                    else:
                                        title = entry["url"].rsplit("/", 1)[-1]
                                        if "." in title:
                                            title = title[:title.rindex(".")]
                                        found = False
                                    if "duration" in entry:
                                        dur = float(entry["duration"])
                                    else:
                                        dur = None
                                    url = entry.get("webpage_url", entry.get("url", entry.get("id")))
                                    if not url:
                                        continue
                                    temp = {
                                        "name": title,
                                        "url": url,
                                        "duration": dur,
                                    }
                                    if not is_url(url):
                                        if entry.get("ie_key", "").casefold() == "youtube":
                                            temp["url"] = f"https://www.youtube.com/watch?v={url}"
                                    temp["research"] = True
                            output.append(cdict(temp))
                else:
                    # Single item results must contain full data, we take advantage of that here
                    found = "duration" in resp
                    if found:
                        dur = resp["duration"]
                    else:
                        dur = None
                    temp = cdict({
                        "name": resp["title"],
                        "url": resp["webpage_url"],
                        "duration": dur,
                        "stream": get_best_audio(resp),
                        "icon": get_best_icon(resp),
                        "video": get_best_video(resp),
                    })
                    output.append(temp)
            return output
        except:
            if force != "spotify":
                raise
            print_exc()
            return 0

    def item_yt(self, item):
        video = next(iter(item.values()))
        if "videoId" not in video:
            return
        try:
            dur = time_parse(video["lengthText"]["simpleText"])
        except KeyError:
            dur = None
        try:
            title = video["title"]["runs"][0]["text"]
        except KeyError:
            title = video["title"]["simpleText"]
        try:
            tn = video["thumbnail"]
        except KeyError:
            thumbnail = None
        else:
            if type(tn) is dict:
                thumbnail = sorted(tn["thumbnails"], key=lambda t: t.get("width", 0) * t.get("height", 0))[-1]["url"]
            else:
                thumbnail = tn
        try:
            views = int(video["viewCountText"]["simpleText"].replace(",", "").replace("views", "").replace(" ", ""))
        except (KeyError, ValueError):
            views = 0
        return cdict(
            name=video["title"]["runs"][0]["text"],
            url=f"https://www.youtube.com/watch?v={video['videoId']}",
            duration=dur,
            icon=thumbnail,
            views=views,
        )

    def parse_yt(self, s):
        data = eval_json(s)
        results = alist()
        try:
            pages = data["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"]["sectionListRenderer"]["contents"]
        except KeyError:
            pages = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]["content"]["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"]
        for page in pages:
            try:
                items = next(iter(page.values()))["contents"]
            except KeyError:
                continue
            for item in items:
                if "promoted" not in next(iter(item)).casefold():
                    entry = self.item_yt(item)
                    if entry is not None:
                        results.append(entry)
        return sorted(results, key=lambda entry: entry.views, reverse=True)

    def search_yt(self, query):
        url = f"https://www.youtube.com/results?search_query={verify_url(query)}"
        self.youtube_x += 1
        resp = Request(url, timeout=12)
        result = None
        with suppress(ValueError):
            s = resp[resp.index(b"// scraper_data_begin") + 21:resp.rindex(b"// scraper_data_end")]
            s = s[s.index(b"var ytInitialData = ") + 20:s.rindex(b";")]
            result = self.parse_yt(s)
        with suppress(ValueError):
            s = resp[resp.index(b'window["ytInitialData"] = ') + 26:]
            s = s[:s.index(b'window["ytInitialPlayerResponse"] = null;')]
            s = s[:s.rindex(b";")]
            result = self.parse_yt(s)
        if result is None:
            raise NotImplementedError("Unable to read json response.")
        q = to_alphanumeric(full_prune(query))
        high = alist()
        low = alist()
        for entry in result:
            if entry.duration:
                name = full_prune(entry.name)
                aname = to_alphanumeric(name)
                spl = aname.split()
                if entry.duration < 960 or "extended" in q or "hour" in q or "extended" not in spl and "hour" not in spl and "hours" not in spl:
                    if fuzzy_substring(aname, q, match_length=False) >= 0.5:
                        high.append(entry)
                        continue
            low.append(entry)
        def key(entry):
            coeff = fuzzy_substring(to_alphanumeric(full_prune(entry.name)), q, match_length=False)
            if coeff < 0.5:
                coeff = 0
            return coeff
        out = sorted(high, key=key, reverse=True)
        out.extend(sorted(low, key=key, reverse=True))
        # print(out)
        return out

    # Performs a search, storing and using cached search results for efficiency.
    def search(self, item, force=False, mode=None, count=1):
        item = verify_search(item)
        if mode is None and count == 1 and item in self.searched:
            if utc() - self.searched[item].t < 18000:
                return self.searched[item].data
            else:
                self.searched.pop(item)
        while len(self.searched) > 262144:
            self.searched.pop(next(iter(self.searched)))
        with self.semaphore:
            try:
                obj = cdict(t=utc())
                obj.data = output = self.extract(item, force, mode=mode, count=count)
                self.searched[item] = obj
                return output
            except Exception as ex:
                print_exc()
                return repr(ex)

    # Gets the stream URL of a queue entry, starting download when applicable.
    def get_stream(self, entry, video=False, force=False, download=True, callback=None):
        if video:
            stream = entry.get("video", None)
        else:
            stream = entry.get("stream", None)
        icon = entry.get("icon", None)
        # Use SHA-256 hash of URL to avoid filename conflicts
        h = shash(entry["url"])
        fn = h + ".opus"
        # Use cached file if one already exists
        if self.cache.get(fn) or not download:
            if video:
                entry["video"] = stream
            else:
                entry["stream"] = stream
            entry["icon"] = icon
            # Files may have a callback set for when they are loaded
            if callback is not None:
                create_future_ex(callback)
            f = self.cache.get(fn)
            if f is not None:
                entry["file"] = f
                # Assign file duration estimate to queue entry
                # This could be done better, this current implementation is technically not thread-safe
                if f.loaded:
                    entry["duration"] = f.duration()
                else:
                    f.assign.append(entry)
                # Touch file to indicate usage
                f.ensure_time()
                while not f.stream:
                    time.sleep(0.1)
            if f or not force or not download:
                return f
        # "none" indicates stream is currently loading
        if stream == "none" and not force:
            return None
        entry["stream"] = "none"
        searched = False
        # If "research" tag is set, entry does not contain full data and requires another search
        if "research" in entry:
            try:
                self.extract_single(entry)
                searched = True
                entry.pop("research", None)
            except:
                print_exc()
                entry.pop("research", None)
                raise
            else:
                stream = entry.get("stream", None)
                icon = entry.get("icon", None)
        # If stream is still not found or is a soundcloud audio fragment playlist file, perform secondary youtube-dl search
        if stream in (None, "none"):
            data = self.search(entry["url"])
            stream = set_dict(data[0], "stream", data[0].url)
            icon = set_dict(data[0], "icon", data[0].url)
        elif not searched and (stream.startswith("https://cf-hls-media.sndcdn.com/") or stream.startswith("https://www.yt-download.org/download/")):
            data = self.extract(entry["url"])
            stream = set_dict(data[0], "stream", data[0].url)
            icon = set_dict(data[0], "icon", data[0].url)
        # Otherwise attempt to start file download
        try:
            self.cache[fn] = f = AudioFile(fn)
            if stream.startswith("ytsearch:") or stream in (None, "none"):
                self.extract_single(entry, force=True)
                stream = entry.get("stream")
                if stream in (None, "none"):
                    raise FileNotFoundError("Unable to locate appropriate file stream.")
            f.load(stream, check_fmt=entry.get("duration") is None, webpage_url=entry["url"], live=entry.get("duration") and not entry["duration"] < inf)
            # Assign file duration estimate to queue entry
            f.assign.append(entry)
            entry["stream"] = stream
            entry["icon"] = icon
            entry["file"] = f
            f.ensure_time()
            # Files may have a callback set for when they are loaded
            if callback is not None:
                create_future(callback)
            return f
        except:
            # Remove entry URL if loading failed
            print_exc()
            entry["url"] = ""

    # For ~download
    def download_file(self, url, fmt, start=None, end=None, auds=None):
        # Select a filename based on current time to avoid conflicts
        if fmt[:3] == "mid":
            mid = True
            fmt = "mp3"
        else:
            mid = False
        videos = ("webm", "mkv", "f4v", "flv", "mov", "qt", "wmv", "mp4", "m4v", "mpv")
        info = self.extract(url)[0]
        self.get_stream(info, video=fmt in videos, force=True, download=False)
        outf = f"{info['name']}.{fmt}"
        ts = ts_us()
        fn = f"cache/\x7f{ts}~" + outf.translate(filetrans)
        if fmt in videos:
            video = info["video"]
        else:
            video = None
        stream = info["stream"]
        if not stream:
            raise LookupError(f"No stream URLs found for {url}")
        args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
        if not video:
            args.append("-vn")
        if str(start) != "None":
            args.extend(("-ss", start))
        if str(end) != "None":
            args.extend(("-to", end))
        else:
            args.extend(("-to", "86400"))
        if video:
            args.extend(("-i", video))
        args.extend(("-i", stream))
        if auds is not None:
            args.extend(auds.construct_options(full=True))
        br = 196608
        if auds and br > auds.stats.bitrate:
            br = max(4096, auds.stats.bitrate)
        if fmt in ("vox", "adpcm"):
            args.extend(("-acodec", "adpcm_ms"))
            fmt = "wav" if fmt == "adpcm" else "vox"
            outf = f"{info['name']}.{fmt}"
            fn = f"cache/\x7f{ts}~" + outf.translate(filetrans)
        elif fmt == "pcm":
            fmt = "s16le"
        if not video:
            args.extend(("-ar", str(SAMPLE_RATE), "-b:a", str(br)))
        args.extend(("-f", fmt, fn))
        print(args)
        try:
            resp = subprocess.run(args)
            resp.check_returncode()
        except subprocess.CalledProcessError as ex:
            # Attempt to convert file from org if FFmpeg failed
            try:
                new = select_and_convert(stream)
            except ValueError:
                if resp.stderr:
                    raise RuntimeError(*ex.args, resp.stderr)
                raise ex
            # Re-estimate duration if file was successfully converted from org
            args[args.index("-i") + 1] = new
            try:
                resp = subprocess.run(args)
                resp.check_returncode()
            except subprocess.CalledProcessError as ex:
                if resp.stderr:
                    raise RuntimeError(*ex.args, resp.stderr)
                raise ex
            if not is_url(new):
                with suppress():
                    os.remove(new)
        if not mid:
            return fn, outf
        self.other_x += 1
        with open(fn, "rb") as f:
            resp = Request(
                "https://cts.ofoct.com/upload.php",
                method="post",
                files={"myfile": ("temp.mp3", f)},
                timeout=32,
                decode=True
            )
            resp_fn = ast.literal_eval(resp)[0]
        url = f"https://cts.ofoct.com/convert-file_v2.php?cid=audio2midi&output=MID&tmpfpath={resp_fn}&row=file1&sourcename=temp.ogg&rowid=file1"
        # print(url)
        with suppress():
            os.remove(fn)
        self.other_x += 1
        resp = Request(url, timeout=420)
        self.other_x += 1
        out = Request(f"https://cts.ofoct.com/get-file.php?type=get&genfpath=/tmp/{resp_fn}.mid", timeout=24)
        return out, outf[:-4] + ".mid"

    # Extracts full data for a single entry. Uses cached results for optimization.
    def extract_single(self, i, force=False):
        item = i.url
        if not force:
            if item in self.searched:
                if utc() - self.searched[item].t < 18000:
                    it = self.searched[item].data[0]
                    i.update(it)
                    if i.get("stream") not in (None, "none"):
                        return True
                else:
                    self.searched.pop(item, None)
            while len(self.searched) > 262144:
                self.searched.pop(next(iter(self.searched)))
        with self.semaphore:
            try:
                data = self.extract_true(item)
                if "entries" in data:
                    data = data["entries"][0]
                elif not issubclass(type(data), collections.abc.Mapping):
                    data = data[0]
                obj = cdict(t=utc())
                obj.data = out = [cdict(
                    name=data["name"],
                    url=data["url"],
                    stream=get_best_audio(data),
                    icon=get_best_icon(data),
                    video=get_best_video(data),
                )]
                try:
                    out[0].duration = data["duration"]
                except KeyError:
                    out[0].research = True
                self.searched[item] = obj
                it = out[0]
                i.update(it)
            except:
                i.url = ""
                print_exc(item)
                return False
        return True

ytdl = AudioDownloader()


class Queue(Command):
    server_only = True
    name = ["▶️", "P", "Q", "Play", "Enqueue"]
    alias = name + ["LS"]
    description = "Shows the music queue, or plays a song in voice."
    usage = "<search_links>* <force{?f}|budge{?b}|verbose{?v}|hide{?h}>*"
    flags = "hvfbz"
    no_parse = True
    directions = [b'\xe2\x8f\xab', b'\xf0\x9f\x94\xbc', b'\xf0\x9f\x94\xbd', b'\xe2\x8f\xac', b'\xf0\x9f\x94\x84']
    _timeout_ = 2
    rate_limit = (0.5, 3)
    typing = True
    slash = ("Play", "Queue")

    async def __call__(self, bot, user, perm, message, channel, guild, flags, name, argv, **void):
        # This command is a bit of a mess
        argv += " ".join(best_url(a) for a in message.attachments)
        if not argv:
            auds = await auto_join(guild, channel, user, bot)
            elapsed = auds.stats.position
            q = auds.queue
            v = "v" in flags
            if not v and len(q) and auds.paused & 1 and "p" in name:
                auds.paused &= -2
                auds.pausec = False
                auds.preparing = False
                if auds.stats.position <= 0:
                    if auds.queue:
                        auds.queue[0].pop("played", None)
                create_future_ex(auds.queue.update_play, timeout=120)
                create_future_ex(auds.ensure_play, timeout=120)
                return ini_md(f"Successfully resumed audio playback in {sqr_md(guild)}."), 1
            if not len(q):
                auds.preparing = False
                create_future_ex(auds.update, timeout=180)
            # Set callback message for scrollable list
            return (
                "*```" + "\n" * ("z" in flags) + "callback-voice-queue-"
                + str(user.id) + "_0_" + str(int(v))
                + "-\nLoading Queue...```*"
            )
        # Get audio player as fast as possible, scheduling it to join asynchronously if necessary
        try:
            auds = bot.data.audio.players[guild.id]
            auds.channel = channel
            future = None
        except KeyError:
            future = create_task(auto_join(guild, channel, user, bot, preparing=True))
        # Start typing event asynchronously to avoid delays
        async with emptyctx:
            # Perform search concurrently, may contain multiple URLs
            out = None
            urls = await bot.follow_url(argv, allow=True, images=False)
            if urls:
                if len(urls) == 1:
                    argv = urls[0]
                else:
                    out = [create_future(ytdl.search, url) for url in urls]
            if out is None:
                resp = await create_future(ytdl.search, argv, timeout=180)
            else:
                resp = deque()
                for fut in out:
                    temp = await fut
                    # Ignore errors when searching with multiple URLs
                    if type(temp) not in (str, bytes):
                        resp.extend(temp)
            # Wait for audio player to finish loading if necessary
            if future is not None:
                auds = await future
        if "f" in flags or "b" in flags:
            if not is_alone(auds, user) and perm < 1:
                raise self.perm_error(perm, 1, "to force play while other users are in voice")
        if auds.stats.quiet & 2:
            set_dict(flags, "h", 1)
        elapsed = auds.stats.position
        q = auds.queue
        # Raise exceptions returned by searches
        if type(resp) is str:
            raise evalEX(resp)
        # Assign search results to queue entries
        added = deque()
        names = []
        for i, e in enumerate(resp, 1):
            if i > 262144:
                break
            try:
                name = e.name
            except:
                print(e)
                raise
            url = e.url
            temp = {
                # "hash": e.hash,
                "name": name,
                "url": url,
                "duration": e.get("duration"),
                "u_id": user.id,
                "skips": deque(),
            }
            if "research" in e:
                temp["research"] = True
            added.append(cdict(temp))
            names.append(no_md(name))
            if not i & 16383:
                await asyncio.sleep(0.2)
        # Prepare to enqueue entries
        if "b" not in flags:
            total_duration = 0
            for e in q:
                total_duration += e_dur(e.duration)
            if auds.reverse and len(auds.queue):
                total_duration += elapsed - e_dur(q[0].duration)
            else:
                total_duration -= elapsed
        if auds.stats.shuffle:
            added = shuffle(added)
        tdur = 3
        if "f" in flags:
            # Force play moves currently playing item, which means we have to unset the "played" tag from currently playing entries to allow them to play again
            if auds.queue:
                auds.queue[0].pop("played", None)
            auds.queue.enqueue(added, 0)
            create_future_ex(auds.new, timeout=120)
            total_duration = tdur
        elif "b" in flags:
            auds.queue.enqueue(added, 1)
            total_duration = max(3, e_dur(q[0].duration) - elapsed if q else 0)
        else:
            auds.queue.enqueue(added, -1)
            total_duration = max(total_duration / auds.speed, tdur)
        if not names:
            raise LookupError(f"No results for {argv}.")
        if "v" in flags:
            names = no_md(alist(i.name + ": " + time_disp(e_dur(i.duration)) for i in added))
        elif len(names) == 1:
            names = names[0]
        else:
            names = f"{len(names)} items"
        if "h" not in flags:
            return ini_md(f"🎶 Added {sqr_md(names)} to the queue! Estimated time until playing: {sqr_md(time_until(utc() + total_duration))}. 🎶"), 1

    async def _callback_(self, bot, message, reaction, user, perm, vals, **void):
        u_id, pos, v = [int(i) for i in vals.split("_", 2)]
        if reaction not in (None, self.directions[-1]) and u_id != user.id and perm < 3:
            return
        if reaction not in self.directions and reaction is not None:
            return
        user = await bot.fetch_user(u_id)
        guild = message.guild
        auds = await auto_join(guild, message.channel, user, bot)
        q = auds.queue
        last = max(0, len(q) - 10)
        if reaction is not None:
            i = self.directions.index(reaction)
            if i == 0:
                new = 0
            elif i == 1:
                new = max(0, pos - 10)
            elif i == 2:
                new = min(last, pos + 10)
            elif i == 3:
                new = last
            else:
                new = pos
            pos = new
        content = message.content
        if not content:
            content = message.embeds[0].description
        i = content.index("callback")
        content = "*```" + "\n" * ("\n" in content[:i]) + (
            "callback-voice-queue-"
            + str(u_id) + "_" + str(pos) + "_" + str(int(v))
            + "-\nQueue for " + guild.name.replace("`", "") + ": "
        )
        elapsed = auds.stats.position if q else 0
        startTime = 0
        if not q:
            totalTime = 0
        elif auds.stats.loop or auds.stats.repeat:
            totalTime = inf
        else:
            if auds.reverse and q:
                totalTime = elapsed - e_dur(q[0].duration)
            else:
                totalTime = -elapsed
            i = 0
            for e in q:
                totalTime += e_dur(e.duration)
                if i < pos:
                    startTime += e_dur(e.duration)
                if not 1 + i & 32767:
                    await asyncio.sleep(0.1)
                i += 1
        cnt = len(q)
        info = (
            str(cnt) + " item" + "s" * (cnt != 1) + "\nEstimated total duration: "
            + time_until(utc() + totalTime / auds.speed) + "```*"
        )
        if not q:
            duration = 0
        else:
            duration = e_dur(q[0].duration)
        if duration == 0:
            elapsed = 0
            duration = 0.0001
        bar = await bot.create_progress_bar(18, elapsed / duration)
        if not q:
            countstr = "Queue is currently empty.\n"
        else:
            countstr = f'{"[`" + no_md(q[0].name) + "`]"}({q[0].url})'
        countstr += f"` ({uni_str(time_disp(elapsed))}/{uni_str(time_disp(duration))})`\n{bar}\n"
        emb = discord.Embed(
            description=content + info + countstr,
            colour=rand_colour(),
        )
        emb.set_author(**get_author(user))
        if q:
            icon = q[0].get("icon", "")
        else:
            icon = ""
        if icon:
            emb.set_thumbnail(url=icon)
        async with auds.semaphore:
            embstr = ""
            currTime = startTime
            i = pos
            maxlen = 48 - int(math.log10(len(q))) if q else 48
            while i < min(pos + 10, len(q)):
                e = q[i]
                space = int(math.log10(len(q))) - int(math.log10(max(1, i)))
                curr = "`" + " " * space
                ename = no_md(e.name)
                curr += f'【{i}】 `{"[`" + no_md(lim_str(ename + " " * (maxlen - len(ename)), maxlen)) + "`]"}({ensure_url(e.url)})` ({time_disp(e_dur(e.duration))})`'
                if v:
                    try:
                        u = bot.cache.users[e.u_id]
                        name = u.display_name
                    except KeyError:
                        name = "Deleted User"
                        with suppress():
                            u = await bot.fetch_user(e.u_id)
                            name = u.display_name
                    curr += "\n" + ini_md(sqr_md(name))
                if auds.reverse and len(auds.queue):
                    estim = currTime + elapsed - e_dur(auds.queue[0].duration)
                else:
                    estim = currTime - elapsed
                if v:
                    if estim > 0:
                        curr += "Time until playing: "
                        estimate = time_until(utc() + estim / auds.speed)
                        if i <= 1 or not auds.stats.shuffle:
                            curr += "[" + estimate + "]"
                        else:
                            curr += "{" + estimate + "}"
                    else:
                        curr += "Remaining time: [" + time_until(utc() + (estim + e_dur(e.duration)) / auds.speed) + "]"
                    curr += "```"
                curr += "\n"
                if len(embstr) + len(curr) > 2048 - len(emb.description):
                    break
                embstr += curr
                if i <= 1 or not auds.stats.shuffle:
                    currTime += e_dur(e.duration)
                if not 1 + 1 & 4095:
                    await asyncio.sleep(0.3)
                i += 1
        emb.description += embstr
        more = len(q) - i
        if more > 0:
            emb.set_footer(text=f"{uni_str('And', 1)} {more} {uni_str('more...', 1)}")
        create_task(message.edit(content=None, embed=emb))
        if reaction is None:
            for react in self.directions:
                async with delay(0.5):
                    create_task(message.add_reaction(as_str(react)))


class Playlist(Command):
    server_only = True
    name = ["DefaultPlaylist", "PL"]
    min_display = "0~2"
    description = "Shows, appends, or removes from the default playlist."
    usage = "(add|remove)? <search_links>*"
    flags = "aedzf"
    directions = [b'\xe2\x8f\xab', b'\xf0\x9f\x94\xbc', b'\xf0\x9f\x94\xbd', b'\xe2\x8f\xac', b'\xf0\x9f\x94\x84']
    rate_limit = 0.5
    typing = True
    slash = True

    async def __call__(self, user, argv, guild, flags, channel, perm, **void):
        update = self.bot.data.playlists.update
        bot = self.bot
        if argv or "d" in flags:
            req = 2
            if perm < req:
                reason = f"to modify default playlist for {guild.name}"
                raise self.perm_error(perm, req, reason)
        pl = set_dict(bot.data.playlists, guild.id, [])
        if not argv:
            if "d" in flags:
                # This deletes all default playlist entries for the current guild
                if "f" not in flags and len(pl) > 1:
                    return ini_md(sqr_md(f"WARNING: {len(pl)} ENTRIES TARGETED. REPEAT COMMAND WITH ?F FLAG TO CONFIRM."))
                bot.data.playlists.pop(guild.id)
                return italics(ini_md(f"Successfully removed all {sqr_md(len(pl))} entries from the default playlist for {sqr_md(guild)}."))
            # Set callback message for scrollable list
            return (
                "*```" + "\n" * ("z" in flags) + "callback-voice-playlist-"
                + str(user.id) + "_0"
                + "-\nLoading Playlist database...```*"
            )
        if "d" in flags:
            # Can only remove by index atm
            i = await bot.eval_math(argv, guild.id)
            temp = pl[i]
            pl.pop(i)
            update(guild.id)
            return italics(ini_md(f"Removed {sqr_md(temp.name)} from the default playlist for {sqr_md(guild)}."))
        lim = 8 << self.bot.is_trusted(guild.id) * 2 + 1
        if len(pl) >= lim:
            raise OverflowError(f"Playlist for {guild} has reached the maximum of {lim} items. Please remove an item to add another.")
        urls = await bot.follow_url(argv, allow=True, images=False)
        if urls:
            argv = urls[0]
        async with emptyctx:
        # Unlike ~queue this command only supports a single URL/search
            resp = await create_future(ytdl.search, argv, timeout=180)
        if type(resp) is str:
            raise evalEX(resp)
        # Assign search results to default playlist entries
        names = []
        for e in resp:
            name = e.name
            names.append(no_md(name))
            pl.append(cdict(
                name=name,
                url=e.url,
                duration=e.duration,
            ))
        if not names:
            raise LookupError(f"No results for {argv}.")
        pl.sort(key=lambda x: x["name"].casefold())
        update(guild.id)
        stuff = str(len(names)) + " items" if len(names) > 3 else ', '.join(names)
        return ini_md(f"Added {sqr_md(stuff)} to the default playlist for {sqr_md(guild)}.")
    
    async def _callback_(self, bot, message, reaction, user, perm, vals, **void):
        u_id, pos = [int(i) for i in vals.split("_", 1)]
        if reaction not in (None, self.directions[-1]) and u_id != user.id and perm < 3:
            return
        if reaction not in self.directions and reaction is not None:
            return
        guild = message.guild
        user = await bot.fetch_user(u_id)
        pl = bot.data.playlists.get(guild.id, [])
        page = 12
        last = max(0, len(pl) - page)
        if reaction is not None:
            i = self.directions.index(reaction)
            if i == 0:
                new = 0
            elif i == 1:
                new = max(0, pos - page)
            elif i == 2:
                new = min(last, pos + page)
            elif i == 3:
                new = last
            else:
                new = pos
            pos = new
        content = message.content
        if not content:
            content = message.embeds[0].description
        i = content.index("callback")
        content = "*```" + "\n" * ("\n" in content[:i]) + (
            "callback-voice-playlist-"
            + str(u_id) + "_" + str(pos)
            + "-\n"
        )
        if not pl:
            content += f"No currently enabled default playlist for {str(guild).replace('`', '')}.```*"
            msg = ""
        else:
            pl.sort(key=lambda x: x["name"].casefold())
            content += f"{len(pl)} items in default playlist for {str(guild).replace('`', '')}:```*"
            key = lambda x: lim_str(sqr_md(x["name"]) + "(" + x["url"] + ")", 1900 / page)
            msg = iter2str(pl[pos:pos + page], key=key, offset=pos, left="`【", right="】`")
        colour = await self.bot.data.colours.get(to_png_ex(guild.icon_url))
        emb = discord.Embed(
            description=content + msg,
            colour=colour,
        )
        emb.set_author(**get_author(user))
        more = len(pl) - pos - page
        if more > 0:
            emb.set_footer(text=f"{uni_str('And', 1)} {more} {uni_str('more...', 1)}")
        create_task(message.edit(content=None, embed=emb))
        if reaction is None:
            for react in self.directions:
                async with delay(0.5):
                    create_task(message.add_reaction(as_str(react)))
        

class Connect(Command):
    server_only = True
    name = ["📲", "🎤", "🎵", "🎶", "📴", "📛", "Summon", "Join", "DC", "Disconnect", "Leave", "Move", "Reconnect"]
    # Because Rythm also has this alias :P
    alias = name + ["FuckOff"]
    description = "Summons the bot into a voice channel."
    usage = "<channel>?"
    rate_limit = (3, 4)
    slash = ("Join", "Leave")

    async def __call__(self, user, channel, name="join", argv="", vc=None, **void):
        bot = self.bot
        if name in ("dc", "disconnect", "leave", "fuckoff", "📴", "📛"):
            vc_ = None
        elif argv or name == "move":
            c_id = verify_id(argv)
            if not c_id > 0:
                vc_ = None
            else:
                vc_ = await bot.fetch_channel(c_id)
        else:
            # If voice channel is already selected, use that
            if vc is not None:
                vc_ = vc
            else:
                # Otherwise attempt to match user's currently connected voice channel
                voice = user.voice
                member = user.guild.me
                if voice is None:
                    # Otherwise attempt to find closest voice channel to current text channel
                    catg = channel.category
                    if catg is not None:
                        channels = catg.voice_channels
                    else:
                        channels = None
                    if not channels:
                        pos = 0 if channel.category is None else channel.category.position
                        # Sort by distance from text channel
                        channels = sorted(tuple(channel for channel in channel.guild.voice_channels if channel.permissions_for(member).connect and channel.permissions_for(member).speak and channel.permissions_for(member).use_voice_activation), key=lambda channel: (abs(pos - (channel.position if channel.category is None else channel.category.position)), abs(channel.position)))
                    if channels:
                        vc_ = channels[0]
                    else:
                        raise LookupError("Unable to find voice channel.")
                else:
                    vc_ = voice.channel
        connecting = bot.data.audio.connecting
        # target guild may be different from source guild
        if vc_ is None:
            guild = channel.guild
        else:
            guild = vc_.guild
        # Use permission level in target guild to make sure user is able to perform command
        perm = bot.get_perms(user, guild)
        if perm < 0:
            raise self.perm_error(perm, 0, f"for command {self.name} in {guild}")
        # If no voice channel is selected, perform disconnect
        if vc_ is None:
            if argv:
                if perm < 2:
                    raise self.perm_error(perm, 2, f"for command {self.name} in {guild}")
                u_id = verify_id(argv)
                try:
                    t_user = await bot.fetch_user_member(u_id, guild)
                except (LookupError):
                    t_role = guild.get_role(u_id)
                    if t_role is None:
                        raise LookupError(f"No results for {u_id}.")
                    members = [member for member in t_role.members if member.voice is not None]
                    if not members:
                        return code_md("No members to disconnect.")
                    await disconnect_members(bot, guild, members)
                    if len(members) == 1:
                        return ini_md(f"Disconnected {sqr_md(members[0])} from {sqr_md(guild)}."), 1
                    return ini_md(f"Disconnected {sqr_md(str(members) + ' members')} from {sqr_md(guild)}."), 1
                member = guild.get_member(t_user.id)
                if not member or member.voice is None:
                    return code_md("No members to disconnect.")
                await disconnect_members(bot, guild, (member,))
                return ini_md(f"Disconnected {sqr_md(member)} from {sqr_md(guild)}."), 1
            try:
                auds = bot.data.audio.players[guild.id]
            except KeyError:
                raise LookupError("Unable to find voice channel.")
            auds.channel = channel
            if not is_alone(auds, user) and perm < 1:
                raise self.perm_error(perm, 1, "to disconnect while other users are in voice")
            auds.dead = True
            connecting.pop(guild.id, None)
            await bot.data.audio(guild=guild)
            return
        # Check if already in voice, move if that is the case
        joined = False
        for vc in bot.voice_clients:
            if vc.guild.id == guild.id:
                joined = True
                if vc.channel.id != vc_.id:
                    with suppress():
                        await vc.move_to(vc_)
                break
        if not joined:
            connecting[guild.id] = utc()
            vc = cdict(channel=vc_, is_playing=lambda: False, is_connected=lambda: None, guild=vc_.guild, disconnect=async_nop, move_to=async_nop, play=lambda *args, **kwargs: exec("raise RuntimeError"), stop=lambda: None, source=None)
        # Create audio source if none already exists
        if guild.id not in bot.data.audio.players:
            bot.data.audio.players[guild.id] = auds = CustomAudio(bot, vc, channel)
        if not joined:
            if not vc_.permissions_for(guild.me).connect:
                raise ConnectionError("Insufficient permissions to connect to voice channel.")
            if vc_.permissions_for(guild.me).manage_channels:
                bitrate = min(auds.stats.bitrate, guild.bitrate_limit)
                if vc_.bitrate < bitrate:
                    await vc_.edit(bitrate=bitrate, reason="I deliver maximum quality audio only! :3")
            create_task(auds.set_voice_client(vc_))
            check_if_connected = lambda: create_future(True if guild.me.voice else exec('raise ConnectionError("Connection timed out.")'))
            try:
                await aretry(check_if_connected, attempts=16, delay=0.125)
            except:
                connecting.pop(guild.id, None)
                bot.data.audio.players.pop(guild.id)
                raise
            joined = True
        if vc.is_connected():
            # Unset connecting tag
            connecting.pop(guild.id, None)
        member = guild.me
        if getattr(member, "voice", None) is not None:
            if member.voice.deaf or member.voice.mute or member.voice.afk:
                create_task(member.edit(mute=False, deafen=False))
        if joined:
            # Send update event to bot audio database upon joining
            create_task(bot.data.audio(guild=guild))
            return ini_md(f"Successfully joined {sqr_md(vc_)}! What a cozy place you got here! 😊"), 1


class Skip(Command):
    server_only = True
    name = ["⏭", "🚫", "S", "SK", "CQ", "Remove", "Rem", "ClearQueue", "Clear"]
    min_display = "0~1"
    description = "Removes an entry or range of entries from the voice channel queue."
    usage = "<queue_positions(0)>* <force{?f}|vote{?v}|hide{?h}>*"
    flags = "fhv"
    rate_limit = (0.5, 3)
    slash = True

    async def __call__(self, bot, user, perm, name, args, argv, guild, flags, message, **void):
        if guild.id not in bot.data.audio.players:
            raise LookupError("Currently not playing in a voice channel.")
        auds = bot.data.audio.players[guild.id]
        auds.channel = message.channel
        # ~clear is an alias for ~skip -f inf
        if name.startswith("c"):
            argv = "inf"
            args = [argv]
            flags["f"] = True
        if "f" in flags:
            if not is_alone(auds, user) and perm < 1:
                raise self.perm_error(perm, 1, "to force skip while other users are in voice")
        count = len(auds.queue)
        if not count:
            raise IndexError("Queue is currently empty.")
        # Default to currently playing item
        if not argv:
            elems = [0]
        # Accept range/slice inputs
        elif ":" in argv or ".." in argv:
            while "..." in argv:
                argv = regexp("\\.{3,}").sub("..", argv)
            l = argv.replace("..", ":").split(":")
            it = None
            if len(l) > 3:
                raise ArgumentError("Too many arguments for range input.")
            elif len(l) > 2:
                num = await bot.eval_math(l[0], user)
                it = int(round(num))
            if l[0]:
                num = await bot.eval_math(l[0], user)
                if num > count:
                    num = count
                else:
                    num = round(num) % count
                left = num
            else:
                left = 0
            if l[1]:
                num = await bot.eval_math(l[1], user)
                if num > count:
                    num = count
                else:
                    num = round(num) % count
                right = num
            else:
                right = count
            elems = xrange(left, right, it)
        else:
            # Accept multiple single indices
            elems = [0] * len(args)
            for i in range(len(args)):
                elems[i] = await bot.eval_math(args[i], user)
        if not "f" in flags:
            valid = True
            for e in elems:
                if not is_finite(e):
                    valid = False
                    break
            if not valid:
                elems = range(count)
        async with auds.semaphore:
            # Calculate required vote count based on amount of non-bot members in voice
            members = sum(1 for m in auds.vc.channel.members if not m.bot)
            required = 1 + members >> 1
            response = ""
            i = 1
            for pos in elems:
                pos = float(pos)
                try:
                    # If infinite entries are selected and force flag is set, remove all items
                    if not is_finite(pos):
                        if "f" in flags:
                            auds.queue.clear()
                            auds.paused &= -2
                            create_future_ex(auds.new, timeout=18)
                            if "h" not in flags:
                                return italics(fix_md("Removed all items from the queue.")), 1
                            return
                        raise LookupError
                    curr = auds.queue[pos]
                except LookupError:
                    response += "\n" + repr(IndexError(f"Entry {pos} is out of range."))
                    continue
                # Add skips if voting
                if issubclass(type(curr.skips), collections.abc.MutableSequence):
                    if "f" in flags or user.id == curr["u_id"] and not "v" in flags:
                        curr.skips = None
                    elif user.id not in curr.skips:
                        curr.skips.append(user.id)
                elif "v" in flags:
                    curr.skips = deque([user.id])
                else:
                    curr.skips = None
                if curr.skips is not None:
                    if len(response) > 1200:
                        response = lim_str(response, 1200)
                    else:
                        response += f"Voted to remove {sqr_md(curr.name)} from the queue.\nCurrent vote count: {sqr_md(len(curr.skips))}, required vote count: {sqr_md(required)}.\n"
                if not i & 8191:
                    await asyncio.sleep(0.2)
                i += 1
            # Get list of items to remove from the queue, based on whether they have sufficient amount of skips
            pops = set()
            count = 0
            i = 1
            while i < len(auds.queue):
                q = auds.queue
                song = q[i]
                if song.skips is None or len(song.skips) >= required:
                    if count <= 3:
                        q.pop(i)
                    else:
                        pops.add(i)
                        i += 1
                    if count < 4:
                        response += f"{sqr_md(song.name)} has been removed from the queue.\n"
                    count += 1
                else:
                    i += 1
            if pops:
                auds.queue.pops(pops)
            if auds.queue:
                # If first item is skipped, advance queue and update audio player
                song = auds.queue[0]
                if song.skips is None or len(song.skips) >= required:
                    song.played = True
                    auds.preparing = False
                    if auds.source is not None:
                        auds.source.advanced = True
                    await create_future(auds.stop, timeout=18)
                    r = not name.startswith("r")
                    create_future_ex(auds.queue.advance, looped=r, repeated=r, shuffled=r, timeout=18)
                    if count < 4:
                        response += f"{sqr_md(song.name)} has been removed from the queue.\n"
                    count += 1
            if "h" not in flags:
                if count >= 4:
                    return italics(ini_md(f"{sqr_md(count)} items have been removed from the queue."))
                return ini_md(response), 1


class Pause(Command):
    server_only = True
    name = ["⏸️", "⏯️", "Resume", "Unpause", "Stop"]
    min_display = "0~1"
    description = "Pauses, stops, or resumes audio playing."
    usage = "<hide{?h}>?"
    flags = "h"
    rate_limit = (0.5, 3)
    slash = True

    async def __call__(self, bot, name, guild, user, perm, channel, flags, **void):
        auds = await auto_join(guild, channel, user, bot)
        auds.preparing = False
        if name in ("pause", "stop", "⏸️", "⏯️"):
            if not is_alone(auds, user) and perm < 1:
                raise self.perm_error(perm, 1, f"to {name} while other users are in voice")
        elif auds.stats.position <= 0:
            if auds.queue:
                auds.queue[0].pop("played", None)
        # ~stop resets song position
        if name == "stop":
            auds.seek(0)
        if not auds.paused > 1:
            # ~pause and ~stop cause the audio player to stop
            if name == "⏯️":
                auds.paused ^= 1
            else:
                auds.paused = auds.pausec = name in ("pause", "stop", "⏸️")
            if auds.paused:
                create_future_ex(auds.vc.stop, timeout=18)
        if not auds.paused:
            # When resuming audio, ensure that the audio player starts up again
            create_future_ex(auds.queue.update_play, timeout=18)
            create_future_ex(auds.ensure_play, timeout=18)
        if auds.player is not None:
            auds.player.time = 1 + utc()
        # Send an update event
        await bot.data.audio(guild=guild)
        if "h" not in flags:
            if name in ("⏸️", "pause"):
                past = "paused"
            elif name == "⏯️":
                past = "paused" if auds.paused & 1 else "resumed"
            elif name == "stop":
                past = "stopped"
            else:
                past = name + "d"
            return italics(ini_md(f"Successfully {past} audio playback in {sqr_md(guild)}.")), 1


class Seek(Command):
    server_only = True
    name = ["↔️", "Replay"]
    min_display = "0~1"
    description = "Seeks to a position in the current audio file."
    usage = "<position(0)>? <hide{?h}>?"
    flags = "h"
    rate_limit = (0.5, 3)
    slash = True

    async def __call__(self, argv, bot, guild, user, perm, channel, name, flags, **void):
        auds = await auto_join(guild, channel, user, bot)
        if not is_alone(auds, user) and perm < 1:
            raise self.perm_error(perm, 1, "to seek while other users are in voice")
        # ~replay always seeks to position 0
        if name == "replay":
            num = 0
        elif not argv:
            return ini_md(f"Current audio position: {sqr_md(sec2time(auds.stats.position))}."), 1
        else:
            # ~seek takes an optional time input
            orig = auds.stats.position
            expr = argv
            num = await bot.eval_time(expr, user, orig)
        pos = auds.seek(num)
        if auds.player is not None:
            auds.player.time = 1 + utc()
        if "h" not in flags:
            return italics(ini_md(f"Successfully moved audio position to {sqr_md(sec2time(pos))}.")), 1


class Dump(Command):
    server_only = True
    time_consuming = True
    name = ["Save"]
    alias = name + ["Dujmpö"]
    min_display = "0~1"
    description = "Saves or loads the currently playing audio queue state."
    usage = "<data>? <append{?a}|song_positions{?x}|hide{?h}>*"
    flags = "ahx"
    rate_limit = (1, 2)
    slash = True

    async def __call__(self, guild, channel, user, bot, perm, name, argv, flags, message, vc=None, **void):
        auds = await auto_join(guild, channel, user, bot, vc=vc)
        # ~save is the same as ~dump without an argument
        if argv == "" and not message.attachments or name == "save":
            if name == "load":
                raise ArgumentError("Please input a file or URL to load.")
            async with emptyctx:
                resp, fn = await create_future(auds.get_dump, "x" in flags, js=True, timeout=18)
                f = CompatFile(io.BytesIO(resp), filename=fn)
            create_task(bot.send_with_file(channel, f"Queue data for {bold(str(guild))}:", f))
            return
        if not is_alone(auds, user) and perm < 1:
            raise self.perm_error(perm, 1, "to load new queue while other users are in voice")
        if type(argv) is str:
            if message.attachments:
                url = message.attachments[0].url
            else:
                url = argv
            urls = await bot.follow_url(argv, allow=True, images=False)
            url = urls[0]
            s = await self.bot.get_request(url)
            d = await create_future(select_and_loads, s, size=268435456)
        else:
            # Queue may already be in dict form if loaded from database
            d = argv
        if type(d) is list:
            d = dict(queue=d, stats={})
        q = d["queue"][:262144]
        async with emptyctx:
            # Copy items and cast to cdict queue entries
            for i, e in enumerate(q, 1):
                if type(e) is not cdict:
                    e = q[i - 1] = cdict(e)
                e.u_id = user.id
                e.skips = deque()
                if not i & 8191:
                    await asyncio.sleep(0.1)
            if auds.player is not None:
                auds.player.time = 1 + utc()
            # Shuffle newly loaded dump if autoshuffle is on
            if auds.stats.shuffle:
                shuffle(q)
            for k in d["stats"]:
                if k not in auds.stats:
                    d["stats"].pop(k)
                if k in "loop repeat shuffle quiet stay":
                    d["stats"][k] = bool(d["stats"][k])
                else:
                    d["stats"][k] = mpf(d["stats"][k])
        if "a" not in flags:
            # Basic dump, replaces current queue
            if auds.queue:
                auds.preparing = True
                await create_future(auds.stop, timeout=18)
                auds.queue.clear()
            auds.paused = False
            auds.stats.update(d["stats"])
            if "position" not in d["stats"]:
                auds.stats.position = 0
            position = auds.stats.position
            auds.queue.enqueue(q, -1)
            await create_future(auds.update, timeout=18)
            await create_future(auds.queue.update_play, timeout=18)
            if position:
                while not auds.is_playing:
                    await asyncio.sleep(0.2)
                print(position)
                auds.seek(position)
            if "h" not in flags:
                return italics(ini_md(f"Successfully loaded audio data for {sqr_md(guild)}.")), 1
        else:
            # append dump, adds items without replacing
            auds.queue.enqueue(q, -1)
            auds.stats.update(d["stats"])
            if "h" not in flags:
                return italics(ini_md(f"Successfully appended loaded data to queue for {sqr_md(guild)}.")), 1
            

class AudioSettings(Command):
    server_only = True
    # Aliases are a mess lol
    aliasMap = {
        "Volume": "volume",
        "Speed": "speed",
        "Pitch": "pitch",
        "Pan": "pan",
        "BassBoost": "bassboost",
        "Reverb": "reverb",
        "Compressor": "compressor",
        "Chorus": "chorus",
        "NightCore": "resample",
        "Resample": "resample",
        "Bitrate": "bitrate",
        "LoopQueue": "loop",
        "Repeat": "repeat",
        "ShuffleQueue": "shuffle",
        "Quiet": "quiet",
        "Stay": "stay",
        "Reset": "reset",
    }
    aliasExt = {
        "AudioSettings": None,
        "Audio": None,
        "A": None,
        "Vol": "volume",
        "V": "volume",
        "🔉": "volume",
        "🔊": "volume",
        "📢": "volume",
        "SP": "speed",
        "⏩": "speed",
        "rewind": "rewind",
        "⏪": "rewind",
        "PI": "pitch",
        "↕️": "pitch",
        "PN": "pan",
        "BB": "bassboost",
        "🥁": "bassboost",
        "RV": "reverb",
        "📉": "reverb",
        "CO": "compressor",
        "🗜": "compressor",
        "CH": "chorus",
        "📊": "chorus",
        "NC": "resample",
        # "Rate": "bitrate",
        "BPS": "bitrate",
        "BR": "bitrate",
        "LQ": "loop",
        "🔁": "loop",
        "LoopOne": "repeat",
        "🔂": "repeat",
        "L1": "repeat",
        "SQ": "shuffle",
        "🤫": "quiet",
        "🔕": "quiet",
        "24/7": "stay",
        "♻": "reset",
    }
    rate_limit = (0.5, 5)

    def __init__(self, *args):
        self.alias = list(self.aliasMap) + list(self.aliasExt)[1:]
        self.name = list(self.aliasMap)
        self.min_display = "0~2"
        self.description = "Changes the current audio settings for this server."
        self.usage = "<value>? <volume(?v)|speed(?s)|pitch(?p)|pan(?e)|bassboost(?b)|reverb(?r)|compressor(?c)|chorus(?u)|nightcore(?n)|bitrate(?i)|loop(?l)|repeat(?1)|shuffle(?x)|quiet(?q)|stay(?t)|force_permanent(?f)|disable(?d)|hide(?h)>*"
        self.flags = "vspebrcunil1xqtfdh"
        self.map = {k.casefold(): self.aliasMap[k] for k in self.aliasMap}
        add_dict(self.map, {k.casefold(): self.aliasExt[k] for k in self.aliasExt})
        super().__init__(*args)

    async def __call__(self, bot, channel, user, guild, flags, name, argv, perm, **void):
        auds = await auto_join(guild, channel, user, bot)
        ops = alist()
        op1 = self.map[name]
        if op1 == "reset":
            flags.clear()
            flags["d"] = True
        elif op1 is not None:
            ops.append(op1)
        disable = "d" in flags
        # yanderedev code moment 🙃🙃🙃
        if "v" in flags:
            ops.append("volume")
        if "s" in flags:
            ops.append("speed")
        if "p" in flags:
            ops.append("pitch")
        if "e" in flags:
            ops.append("pan")
        if "b" in flags:
            ops.append("bassboost")
        if "r" in flags:
            ops.append("reverb")
        if "c" in flags:
            ops.append("compressor")
        if "u" in flags:
            ops.append("chorus")
        if "n" in flags:
            ops.append("resample")
        if "i" in flags:
            ops.append("bitrate")
        if "l" in flags:
            ops.append("loop")
        if "1" in flags:
            ops.append("repeat")
        if "x" in flags:
            ops.append("shuffle")
        if "q" in flags:
            ops.append("quiet")
        if "t" in flags:
            ops.append("stay")
        # If no number input given, show audio setting
        if not disable and not argv and (len(ops) != 1 or ops[-1] not in "rewind loop repeat shuffle quiet stay"):
            if len(ops) == 1:
                op = ops[0]
            else:
                key = lambda x: x if type(x) is bool else round_min(100 * x)
                d = dict(auds.stats)
                d.pop("position", None)
                return f"Current audio settings for **{escape_markdown(guild.name)}**:\n{ini_md(iter2str(d, key=key))}"
            orig = auds.stats[op]
            num = round_min(100 * orig)
            return ini_md(f"Current audio {op} setting in {sqr_md(guild)}: [{num}].")
        if not is_alone(auds, user) and perm < 1:
            raise self.perm_error(perm, 1, "to modify audio settings while other users are in voice")
        # No audio setting selected
        if not ops:
            if disable:
                # Disables all audio settings
                pos = auds.stats.position
                res = False
                for k, v in auds.defaults.items():
                    if k != "volume" and auds.stats.get(k) != v:
                        res = True
                        break
                auds.stats = cdict(auds.defaults)
                if "f" in flags:
                    bot.data.audiosettings.pop(guild.id, None)
                if auds.queue and res:
                    await create_future(auds.new, auds.file, pos, timeout=18)
                succ = "Permanently" if "f" in flags else "Successfully"
                return italics(ini_md(f"{succ} reset all audio settings for {sqr_md(guild)}."))
            else:
                # Default to volume
                ops.append("volume")
        s = ""
        for op in ops:
            # These audio settings automatically invert when used
            if type(op) is str:
                if op in "loop repeat shuffle quiet stay" and not argv:
                    argv = str(not auds.stats[op])
                elif op == "rewind":
                    argv = "100"
            if op == "rewind":
                op = "speed"
                argv = "- " + argv
            # This disables one or more audio settings
            if disable:
                val = auds.defaults[op]
                if type(val) is not bool:
                    val *= 100
                argv = str(val)
            # Values should be scaled by 100 to indicate percentage
            origStats = auds.stats
            orig = round_min(origStats[op] * 100)
            num = await bot.eval_math(argv, user, orig)
            new = round_min(num)
            val = round_min(num / 100)
            if op in "loop repeat shuffle quiet stay":
                origStats[op] = new = bool(val)
                orig = bool(orig)
                if "f" in flags:
                    bot.data.audiosettings.setdefault(guild.id, {})[op] = new
            else:
                if op == "bitrate":
                    if val > 1966.08:
                        raise PermissionError("Maximum allowed bitrate is 196608.")
                    elif val < 5.12:
                        raise ValueError("Bitrate must be equal to or above 512.")
                elif op == "speed":
                    if abs(val * 2 ** (origStats.get("resample", 0) / 12)) > 16:
                        raise OverflowError("Maximum speed is 1600%.")
                elif op == "resample":
                    if abs(origStats.get("speed", 1) * 2 ** (val / 12)) > 16:
                        raise OverflowError("Maximum speed is 1600%.")
                origStats[op] = val
                if "f" in flags:
                    bot.data.audiosettings.setdefault(guild.id, {})[op] = val
            if auds.queue:
                if type(op) is str and op not in "loop repeat shuffle quiet stay":
                    # Attempt to adjust audio setting by re-initializing FFmpeg player
                    try:
                        await create_future(auds.new, auds.file, auds.stats.position, timeout=12)
                    except (TimeoutError, asyncio.exceptions.TimeoutError, concurrent.futures._base.TimeoutError):
                        if auds.source:
                            print(auds.args)
                        await create_future(auds.stop, timeout=18)
                        raise RuntimeError("Unable to adjust audio setting.")
            changed = "Permanently changed" if "f" in flags else "Changed"
            s += f"\n{changed} audio {op} setting from {sqr_md(orig)} to {sqr_md(new)}."
        if "h" not in flags:
            return ini_md(s), 1


class Rotate(Command):
    server_only = True
    name = ["🔄", "Jump"]
    min_display = "0~1"
    description = "Rotates the queue to the left by a certain amount of steps."
    usage = "<position>? <hide{?h}>?"
    flags = "h"
    rate_limit = (4, 9)

    async def __call__(self, perm, argv, flags, guild, channel, user, bot, **void):
        auds = await auto_join(guild, channel, user, bot)
        if not argv:
            amount = 1
        else:
            amount = await bot.eval_math(argv, user)
        if len(auds.queue) > 1 and amount:
            if not is_alone(auds, user) and perm < 1:
                raise self.perm_error(perm, 1, "to rotate queue while other users are in voice")
            async with auds.semaphore:
                # Clear "played" tag of current item
                auds.queue[0].pop("played", None)
                auds.queue.rotate(-amount)
                auds.seek(inf)
        if "h" not in flags:
            return italics(ini_md(f"Successfully rotated queue [{amount}] step{'s' if amount != 1 else ''}.")), 1


class Shuffle(Command):
    server_only = True
    name = ["🔀"]
    min_display = "0~1"
    description = "Shuffles the audio queue."
    usage = "<force_full_shuffle{?f}|hide{?h}>*"
    flags = "fsh"
    rate_limit = (4, 9)
    slash = True

    async def __call__(self, perm, flags, guild, channel, user, bot, **void):
        auds = await auto_join(guild, channel, user, bot)
        if len(auds.queue) > 1:
            if not is_alone(auds, user) and perm < 1:
                raise self.perm_error(perm, 1, "to shuffle queue while other users are in voice")
            async with auds.semaphore:
                if "f" in flags or "s" in flags:
                    # Clear "played" tag of current item
                    auds.queue[0].pop("played", None)
                    shuffle(auds.queue)
                    auds.seek(inf)
                else:
                    temp = auds.queue.popleft()
                    shuffle(auds.queue)
                    auds.queue.appendleft(temp)
        if "h" not in flags:
            return italics(ini_md(f"Successfully shuffled queue for {sqr_md(guild)}.")), 1


class Reverse(Command):
    server_only = True
    min_display = "0~1"
    description = "Reverses the audio queue direction."
    usage = "<hide{?h}>?"
    flags = "h"
    rate_limit = (4, 9)

    async def __call__(self, perm, flags, guild, channel, user, bot, **void):
        auds = await auto_join(guild, channel, user, bot)
        if len(auds.queue) > 1:
            if not is_alone(auds, user) and perm < 1:
                raise self.perm_error(perm, 1, "to reverse queue while other users are in voice")
            async with auds.semaphore:
                reverse(auds.queue)
                auds.queue.rotate(-1)
        if "h" not in flags:
            return italics(ini_md(f"Successfully reversed queue for {sqr_md(guild)}.")), 1


class UnmuteAll(Command):
    server_only = True
    time_consuming = True
    min_level = 3
    description = "Disables server mute/deafen for all members."
    usage = "<hide{?h}>?"
    flags = "h"
    rate_limit = 10

    async def __call__(self, guild, flags, **void):
        for vc in guild.voice_channels:
            for user in vc.members:
                if user.voice is not None:
                    if user.voice.deaf or user.voice.mute or user.voice.afk:
                        create_task(user.edit(mute=False, deafen=False))
        if "h" not in flags:
            return italics(ini_md(f"Successfully unmuted all users in voice channels in {sqr_md(guild)}.")), 1


class VoiceNuke(Command):
    server_only = True
    time_consuming = True
    min_level = 3
    name = ["☢️"]
    description = "Removes all users from voice channels in the current server."
    usage = "<hide{?h}>?"
    flags = "h"
    rate_limit = 10

    async def __call__(self, guild, flags, **void):
        connected = set()
        for vc in guild.voice_channels:
            for user in vc.members:
                if user.id != self.bot.id:
                    if user.voice is not None:
                        connected.add(user)
        await disconnect_members(self.bot, guild, connected)
        if "h" not in flags:
            return italics(ini_md(f"Successfully removed all users from voice channels in {sqr_md(guild)}.")), 1


class Radio(Command):
    name = ["FM"]
    description = "Searches for a radio station livestream on http://worldradiomap.com that can be played on ⟨MIZA⟩."
    usage = "<0:country>? <2:state>? <1:city>?"
    rate_limit = (2, 6)
    slash = True
    countries = fcdict()

    def country_repr(self, c):
        out = io.StringIO()
        start = None
        for w in c.split("_"):
            if len(w) > 1:
                if start:
                    out.write("_")
                if len(w) > 3 or not start:
                    if len(w) < 3:
                        out.write(w.upper())
                    else:
                        out.write(w.capitalize())
                else:
                    out.write(w.lower())
            else:
                out.write(w.upper())
            start = True
        out.seek(0)
        return out.read().strip("_")

    def get_countries(self):
        with tracebacksuppressor:
            resp = Request("http://worldradiomap.com", timeout=24)
            search = b'<option value="selector/_blank.htm">- Select a country -</option>'
            resp = resp[resp.index(search) + len(search):]
            resp = resp[:resp.index(b"</select>")]
            with suppress(ValueError):
                while True:
                    search = b'<option value="'
                    resp = resp[resp.index(search) + len(search):]
                    search = b'">'
                    href = as_str(resp[:resp.index(search)])
                    if not href.startswith("http"):
                        href = "http://worldradiomap.com/" + href.lstrip("/")
                    if href.endswith(".htm"):
                        href = href[:-4]
                    resp = resp[resp.index(search) + len(search):]
                    country = single_space(as_str(resp[:resp.index(b"</option>")]).replace(".", " ")).replace(" ", "_")
                    try:
                        self.countries[country].url = href
                    except KeyError:
                        self.countries[country] = cdict(url=href, cities=fcdict(), states=False)
                    data = self.countries[country]
                    alias = href.rsplit("/", 1)[-1].split("_", 1)[-1]
                    self.countries[alias] = data

                    def get_cities(country):
                        resp = Request(country.url, decode=True)
                        search = '<img src="'
                        resp = resp[resp.index(search) + len(search):]
                        icon, resp = resp.split('"', 1)
                        icon = icon.replace("../", "http://worldradiomap.com/")
                        country.icon = icon
                        search = '<option selected value="_blank.htm">- Select a city -</option>'
                        try:
                            resp = resp[resp.index(search) + len(search):]
                        except ValueError:
                            search = '<option selected value="_blank.htm">- State -</option>'
                            resp = resp[resp.index(search) + len(search):]
                            country.states = True
                            with suppress(ValueError):
                                while True:
                                    search = '<option value="'
                                    resp = resp[resp.index(search) + len(search):]
                                    search = '">'
                                    href = as_str(resp[:resp.index(search)])
                                    if not href.startswith("http"):
                                        href = "http://worldradiomap.com/selector/" + href
                                    if href.endswith(".htm"):
                                        href = href[:-4]
                                    search = "<!--"
                                    resp = resp[resp.index(search) + len(search):]
                                    city = single_space(resp[:resp.index("-->")].replace(".", " ")).replace(" ", "_")
                                    country.cities[city] = cdict(url=href, cities=fcdict(), icon=icon, states=False, get_cities=get_cities)
                        else:
                            resp = resp[:resp.index("</select>")]
                            with suppress(ValueError):
                                while True:
                                    search = '<option value="'
                                    resp = resp[resp.index(search) + len(search):]
                                    search = '">'
                                    href = as_str(resp[:resp.index(search)])
                                    if href.startswith("../"):
                                        href = "http://worldradiomap.com/" + href[3:]
                                    if href.endswith(".htm"):
                                        href = href[:-4]
                                    resp = resp[resp.index(search) + len(search):]
                                    city = single_space(resp[:resp.index("</option>")].replace(".", " ")).replace(" ", "_")
                                    country.cities[city] = href
                        return country
                    
                    data.get_cities = get_cities

        return self.countries

    async def __call__(self, bot, channel, message, args, **void):
        if not self.countries:
            await create_future(self.get_countries)
        path = deque()
        if not args:
            fields = msdict()
            for country in self.countries:
                if len(country) > 2:
                    fields.add(country[0].upper(), self.country_repr(country))
            return bot.send_as_embeds(channel, title="Available countries", fields={k: "\n".join(v) for k, v in fields.items()}, author=get_author(bot.user), reference=message)
        c = args.pop(0)
        if c not in self.countries:
            await create_future(self.get_countries)
            if c not in self.countries:
                raise LookupError(f"Country {c} not found.")
        path.append(c)
        country = self.countries[c]
        if not country.cities:
            await create_future(country.get_cities, country)
        if not args:
            fields = msdict()
            desc = deque()
            for city in country.cities:
                desc.append(self.country_repr(city))
            t = "states" if country.states else "cities"
            return bot.send_as_embeds(channel, title=f"Available {t} in {self.country_repr(c)}", thumbnail=country.icon, description="\n".join(desc), author=get_author(bot.user), reference=message)
        c = args.pop(0)
        if c not in country.cities:
            await create_future(country.get_cities, country)
            if c not in country.cities:
                raise LookupError(f"City/State {c} not found.")
        path.append(c)
        city = country.cities[c]
        if type(city) is not str:
            state = city
            if not state.cities:
                await create_future(state.get_cities, state)
            if not args:
                fields = msdict()
                desc = deque()
                for city in state.cities:
                    desc.append(self.country_repr(city))
                return bot.send_as_embeds(channel, title=f"Available cities in {self.country_repr(c)}", thumbnail=country.icon, description="\n".join(desc), author=get_author(bot.user), reference=message)
            c = args.pop(0)
            if c not in state.cities:
                await create_future(state.get_cities, state)
                if c not in state.cities:
                    raise LookupError(f"City {c} not found.")
            path.append(c)
            city = state.cities[c]
        resp = await Request(city, aio=True)
        title = "Radio stations in " + ", ".join(self.country_repr(c) for c in reversed(path)) + ", by frequency (MHz)"
        fields = deque()
        search = b"<div class=exp>Click on the radio station name to listen online"
        resp = as_str(resp[resp.index(search) + len(search):resp.index(b"</p></div><!--end rightcontent-->")])
        for section in resp.split("<td class=tr31><b>")[1:]:
            scale = section[section.index("</b>,") + 5:section.index("Hz</td>")].upper()
            coeff = 0.000001
            if "M" in scale:
                coeff = 1
            elif "K" in scale:
                coeff = 0.001
            with tracebacksuppressor:
                while True:
                    search = "<td class=freq>"
                    search2 = "<td class=dxfreq>"
                    i = j = inf
                    with suppress(ValueError):
                        i = section.index(search) + len(search)
                    with suppress(ValueError):
                        j = section.index(search2) + len(search2)
                    if i > j:
                        i = j
                    if type(i) is not int:
                        break
                    section = section[i:]
                    freq = round_min(round(float(section[:section.index("<")].replace("&nbsp;", "").strip()) * coeff, 6))
                    field = [freq, ""]
                    curr, section = section.split("</tr>", 1)
                    for station in regexp('(?:<td class=(?:dx)?fsta2?>|\s{2,})<a href="').split(curr)[1:]:
                        if field[1]:
                            field[1] += "\n"
                        href, station = station.split('"', 1)
                        if not href.startswith("http"):
                            href = "http://worldradiomap.com/" + href.lstrip("/")
                            if href.endswith(".htm"):
                                href = href[:-4]
                        search = "class=station>"
                        station = station[station.index(search) + len(search):]
                        name = station[:station.index("<")]
                        field[1] += f"[{name.strip()}]({href.strip()})"
                    fields.append(field)
        return bot.send_as_embeds(channel, title=title, thumbnail=country.icon, fields=sorted(fields), author=get_author(bot.user), reference=message)


# This whole thing is a mess, I can't be bothered cleaning this up lol
class Player(Command):
    server_only = True
    buttons = {
	b'\xe2\x8f\xb8': 0,
	b'\xf0\x9f\x94\x84': 1,
	b'\xf0\x9f\x94\x80': 2,
	b'\xe2\x8f\xae': 3,
	b'\xe2\x8f\xad': 4,
        b'\xf0\x9f\x94\x8a': 5,
        b'\xf0\x9f\xa5\x81': 6,
        b'\xf0\x9f\x93\x89': 7,
        b'\xf0\x9f\x93\x8a': 8,
        b'\xe2\x8f\xaa': 9,
        b'\xe2\x8f\xa9': 10,
        b'\xe2\x8f\xab': 11,
        b'\xe2\x8f\xac': 12,
        b'\xe2\x99\xbb': 13,
	b'\xe2\x8f\x8f': 14,
        b'\xe2\x9b\x94': 15,
        }
    barsize = 24
    name = ["NP", "NowPlaying", "Playing"]
    min_display = "0~3"
    description = "Creates an auto-updating virtual audio player for the current server."
    usage = "<enable{?e}|disable{?d}|controllable{?c}>*"
    flags = "cdez"
    rate_limit = (2, 7)

    async def showCurr(self, auds):
        q = auds.queue
        if q:
            s = q[0].skips
            if s is not None:
                skips = len(s)
            else:
                skips = 0
            output = "Playing " + str(len(q)) + " item" + "s" * (len(q) != 1) + " "
            output += skips * "🚫"
        else:
            output = "Queue is currently empty. "
        if auds.stats.loop:
            output += "🔄"
        if auds.stats.shuffle:
            output += "🔀"
        if auds.stats.quiet:
            output += "🔕"
        if q:
            p = [auds.stats.position, e_dur(q[0].duration)]
        else:
            p = [0, 1]
        output += "```"
        output += await self.bot.create_progress_bar(18, p[0] / p[1])
        if q:
            output += "\n[`" + no_md(q[0].name) + "`](" + ensure_url(q[0].url) + ")"
        output += "\n`"
        if auds.paused or not auds.stats.speed:
            output += "⏸️"
        elif auds.stats.speed > 0:
            output += "▶️"
        else:
            output += "◀️"
        if q:
            p = [auds.stats.position, e_dur(q[0].duration)]
        else:
            p = [0, 0.25]
        output += (
            " (" + time_disp(p[0])
            + "/" + time_disp(p[1]) + ")`\n"
        )
        if auds.has_options():
            v = abs(auds.stats.volume)
            if v == 0:
                output += "🔇"
            if v <= 0.5:
                output += "🔉"
            elif v <= 1:
                output += "🔊"
            elif v <= 5:
                output += "📢"
            else:
                output += "🌪️"
            b = auds.stats.bassboost
            if abs(b) > 1 / 6:
                if abs(b) > 5:
                    output += "💥"
                elif b > 0:
                    output += "🥁"
                else:
                    output += "🎻"
            r = auds.stats.reverb
            if r:
                if abs(r) >= 1:
                    output += "📈"
                else:
                    output += "📉"
            u = auds.stats.chorus
            if u:
                output += "📊"
            c = auds.stats.compressor
            if c:
                output += "🗜️"
            e = auds.stats.pan
            if abs(e - 1) > 0.25:
                output += "♒"
            s = auds.stats.speed * 2 ** (auds.stats.resample / 12)
            if s < 0:
                output += "⏪"
            elif s > 1:
                output += "⏩"
            elif s > 0 and s < 1:
                output += "🐌"
            p = auds.stats.pitch + auds.stats.resample
            if p > 0:
                output += "⏫"
            elif p < 0:
                output += "⏬"
        return output

    async def _callback_(self, message, guild, channel, reaction, bot, perm, vals, **void):
        if message is None:
            return
        if not guild.id in bot.data.audio.players:
            with suppress(discord.NotFound, discord.Forbidden):
                await message.clear_reactions()
            return
        auds = bot.data.audio.players[guild.id]
        if reaction is None:
            auds.player = cdict(
                time=inf,
                message=message,
                type=int(vals),
                events=0,
            )
            if auds.player.type:
                auds.stats.quiet |= 2
        elif auds.player is None or auds.player.message.id != message.id:
            with suppress(discord.NotFound, discord.Forbidden):
                await message.clear_reactions()
            return
        if perm < 1:
            return
        if message.content:
            content = message.content
        else:
            content = message.embeds[0].description
        orig = "\n".join(content.splitlines()[:1 + ("\n" == content[3])]) + "\n"
        if reaction is None and auds.player.type:
            for b in self.buttons:
                async with delay(0.5):
                    create_task(message.add_reaction(as_str(b)))
        else:
            if not auds.player.type:
                emoji = bytes()
            elif type(reaction) is bytes:
                emoji = reaction
            else:
                try:
                    emoji = reaction.emoji
                except:
                    emoji = str(reaction)
            if type(emoji) is str:
                emoji = reaction.encode("utf-8")
            if emoji in self.buttons:
                i = self.buttons[emoji]
                if i == 0:
                    auds.paused ^= 1
                elif i == 1:
                    auds.stats.loop = bool(auds.stats.loop ^ 1)
                elif i == 2:
                    auds.stats.shuffle = bool(auds.stats.shuffle ^ 1)
                elif i == 3 or i == 4:
                    if i == 3:
                        pos = 0
                    else:
                        pos = inf
                    auds.seek(pos)
                    if pos:
                        return
                elif i == 5:
                    v = abs(auds.stats.volume)
                    if v < 0.25 or v >= 2:
                        v = 1 / 3
                    elif v < 1:
                        v = 1
                    else:
                        v = 2
                    auds.stats.volume = v
                elif i == 6:
                    b = auds.stats.bassboost
                    if abs(b) < 1 / 3:
                        b = 1
                    elif b < 0:
                        b = 0
                    else:
                        b = -1
                    auds.stats.bassboost = b
                elif i == 7:
                    r = auds.stats.reverb
                    if r:
                        r = 0
                    else:
                        r = 0.5
                    auds.stats.reverb = r
                elif i == 8:
                    c = abs(auds.stats.chorus)
                    if c:
                        c = 0
                    else:
                        c = 1 / 3
                    auds.stats.chorus = c
                    await create_future(auds.new, auds.file, auds.stats.position, timeout=18)
                elif i == 9 or i == 10:
                    s = (i * 2 - 19) * 2 / 11
                    auds.stats.speed = round(auds.stats.speed + s, 5)
                    await create_future(auds.new, auds.file, auds.stats.position, timeout=18)
                elif i == 11 or i == 12:
                    p = i * 2 - 23
                    auds.stats.pitch -= p
                    await create_future(auds.new, auds.file, auds.stats.position, timeout=18)
                elif i == 13:
                    pos = auds.stats.position
                    auds.stats = cdict(auds.defaults)
                    await create_future(auds.new, auds.file, pos, timeout=18)
                elif i == 14:
                    auds.dead = True
                    auds.player = None
                    await bot.silent_delete(message)
                    return
                else:
                    auds.player = None
                    await bot.silent_delete(message)
                    return
        other = await self.showCurr(auds)
        text = lim_str(orig + other, 2000)
        last = message.channel.last_message
        emb = discord.Embed(
            description=text,
            colour=rand_colour(),
            timestamp=utc_dt(),
        ).set_author(**get_author(self.bot.user))
        if last is not None and (auds.player.type or message.id == last.id):
            auds.player.events += 1
            await message.edit(
                content=None,
                embed=emb,
            )
        else:
            auds.player.time = inf
            auds.player.events += 2
            channel = message.channel
            temp = message
            message = await channel.send(
                content=None,
                embed=emb,
            )
            auds.player.message = message
            await bot.silent_delete(temp, no_log=True)
        if auds.queue and not auds.paused & 1:
            maxdel = e_dur(auds.queue[0].duration) - auds.stats.position + 2
            delay = min(maxdel, e_dur(auds.queue[0].duration) / self.barsize / abs(auds.stats.speed))
            if delay > 10:
                delay = 10
            elif delay < 5:
                delay = 5
        else:
            delay = inf
        auds.player.time = utc() + delay

    async def __call__(self, guild, channel, user, bot, flags, perm, **void):
        auds = await auto_join(channel.guild, channel, user, bot)
        if "c" in flags or auds.stats.quiet & 2:
            req = 3
            if perm < req:
                if auds.stats.quiet & 2:
                    if "d" in flags:
                        reason = "delete"
                    else:
                        reason = "override"
                else:
                    reason = "create controllable"
                raise self.perm_error(perm, req, f"to {reason} virtual audio player for {guild}")
        if "d" in flags:
            auds.player = None
            return italics(ini_md(f"Disabled virtual audio players in {sqr_md(channel.guild)}.")), 1
        await create_player(auds, p_type="c" in flags, verbose="z" in flags)


# Small helper function to fetch song lyrics from json data, because sometimes genius.com refuses to include it in the HTML
def extract_lyrics(s):
    s = s[s.index("JSON.parse(") + len("JSON.parse("):]
    s = s[:s.index("</script>")]
    if "window.__" in s:
        s = s[:s.index("window.__")]
    s = s[:s.rindex(");")]
    data = ast.literal_eval(s)
    d = eval_json(data)
    lyrics = d["songPage"]["lyricsData"]["body"]["children"][0]["children"]
    newline = True
    output = ""
    while lyrics:
        line = lyrics.pop(0)
        if type(line) is str:
            if line:
                if line.startswith("["):
                    output += "\n"
                    newline = False
                if "]" in line:
                    if line == "]":
                        if output.endswith(" ") or output.endswith("\n"):
                            output = output[:-1]
                    newline = True
                output += line + ("\n" if newline else (" " if not line.endswith(" ") else ""))
        elif type(line) is dict:
            if "children" in line:
                # This is a mess, the children objects may or may not represent single lines
                lyrics = line["children"] + lyrics
    return output


# Main helper function to fetch song lyrics from genius.com searches
async def get_lyrics(item):
    url = "https://api.genius.com/search"
    for i in range(2):
        header = {"Authorization": f"Bearer {genius_key}"}
        if i == 0:
            search = item
        else:
            search = "".join(shuffle(item.split()))
        data = {"q": search}
        resp = await Request(url, data=data, headers=header, aio=True, timeout=18)
        rdata = await create_future(json.loads, resp, timeout=18)
        hits = rdata["response"]["hits"]
        name = None
        path = None
        for h in hits:
            with tracebacksuppressor:
                name = h["result"]["title"]
                path = h["result"]["api_path"]
                break
        if path and name:
            s = "https://genius.com" + path
            page = await Request(s, headers=header, decode=True, aio=True)
            text = page
            html = await create_future(BeautifulSoup, text, "html.parser", timeout=18)
            lyricobj = html.find('div', class_='lyrics')
            if lyricobj is not None:
                lyrics = lyricobj.get_text().strip()
                print("lyrics_html", s)
                return name, lyrics
            try:
                lyrics = extract_lyrics(text).strip()
                print("lyrics_json", s)
                return name, lyrics
            except:
                if i:
                    raise
                print_exc()
                print(s)
                print(text)
    raise LookupError(f"No results for {item}.")


class Lyrics(Command):
    time_consuming = True
    name = ["SongLyrics"]
    description = "Searches genius.com for lyrics of a song."
    usage = "<search_link>* <verbose{?v}>?"
    flags = "v"
    rate_limit = (2, 6)
    typing = True

    async def __call__(self, bot, guild, channel, message, argv, flags, user, **void):
        for a in message.attachments:
            argv = a.url + " " + argv
        if not argv:
            try:
                auds = bot.data.audio.players[guild.id]
                if not auds.queue:
                    raise LookupError
                argv = auds.queue[0].name
            except LookupError:
                raise IndexError("Queue not found. Please input a search term, URL, or file.")
        # Extract song name if input is a URL, otherwise search song name directly
        urls = await bot.follow_url(argv, allow=True, images=False)
        if urls:
            resp = await create_future(ytdl.search, urls[0], timeout=18)
            search = resp[0].name
        else:
            search = argv
        search = search.translate(self.bot.mtrans)
        # Attempt to find best query based on the song name
        item = verify_search(to_alphanumeric(lyric_trans.sub("", search)))
        if not item:
            item = verify_search(to_alphanumeric(search))
            if not item:
                item = search
        with emptyctx:
            name, lyrics = await get_lyrics(item)
        # Escape colour markdown because that will interfere with the colours we want
        text = clr_md(lyrics.strip()).replace("#", "♯")
        msg = f"Lyrics for **{escape_markdown(name)}**:"
        s = msg + ini_md(text)
        # Directly return lyrics in a code box if it fits
        if "v" not in flags and len(s) <= 2000:
            return s
        title = f"Lyrics for {name}:"
        if len(text) > 54000:
            return (title + "\n\n" + text).strip()
        bot.send_as_embeds(channel, text, author=dict(name=title), colour=(1024, 128), md=ini_md, reference=message)


class Download(Command):
    time_consuming = True
    _timeout_ = 20
    name = ["📥", "Search", "YTDL", "Youtube_DL", "AF", "AudioFilter", "Trim", "ConvertORG", "Org2xm", "Convert"]
    description = "Searches and/or downloads a song from a YouTube/SoundCloud query or audio file link."
    usage = "<0:search_links>* <trim{?t}>? <-3:trim_start|->? <-2:trim_end|->? <-1:out_format(mp4)>? <apply_settings{?a}|verbose_search{?v}>*"
    flags = "avtz"
    rate_limit = (7, 16)
    typing = True
    slash = True

    async def __call__(self, bot, channel, guild, message, name, argv, flags, user, **void):
        fmt = default_fmt = "mp4" if name == "trim" else "mp3"
        if name in ("af", "audiofilter"):
            set_dict(flags, "a", 1)
        # Prioritize attachments in message
        for a in message.attachments:
            argv = a.url + " " + argv
        direct = getattr(message, "simulated", None)
        start = end = None
        # Attempt to download items in queue if no search query provided
        if not argv:
            try:
                auds = await auto_join(guild, channel, user, bot)
                if not auds.queue:
                    raise EOFError
                res = [{"name": e.name, "url": e.url} for e in auds.queue[:10]]
                fmt = "mp3"
                desc = f"Current items in queue for {guild}:"
            except:
                raise IndexError("Queue not found. Please input a search term, URL, or file.")
        else:
            # Parse search query, detecting file format selection if possible
            if " " in argv:
                try:
                    spl = shlex.split(argv)
                except ValueError:
                    spl = argv.split(" ")
                if len(spl) >= 1:
                    fmt = spl[-1].lstrip(".")
                    if fmt.casefold() not in ("mp3", "ogg", "opus", "m4a", "flac", "wav", "wma", "mp2", "vox", "adpcm", "pcm", "mid", "midi", "webm", "mp4", "avi", "mov", "m4v", "mkv", "f4v", "flv", "wmv"):
                        fmt = default_fmt
                    else:
                        if spl[-2] in ("as", "to"):
                            spl.pop(-1)
                        argv = " ".join(spl[:-1])
            if name == "trim" or "t" in flags:
                argv, start, end = argv.rsplit(None, 2)
                if start == "-":
                    start = None
                else:
                    start = await bot.eval_time(start, user)
                if end == "-":
                    end = None
                else:
                    end = await bot.eval_time(end, user)
            argv = verify_search(argv)
            res = []
            # Input may be a URL or set of URLs, in which case we attempt to find the first one
            urls = await bot.follow_url(argv, allow=True, images=False)
            if urls:
                direct = True
                temp = await create_future(ytdl.extract, urls[0], timeout=120)
                res.extend(temp)
            if not res:
                # 2 youtube results per soundcloud result, increased with verbose flag
                sc = min(4, flags.get("v", 0) + 1)
                yt = min(6, sc << 1)
                res = []
                temp = await create_future(ytdl.search, argv, mode="yt", count=yt)
                res.extend(temp)
                temp = await create_future(ytdl.search, argv, mode="sc", count=sc)
                res.extend(temp)
            if not res:
                raise LookupError(f"No results for {argv}.")
            res = res[:10]
            desc = f"Search results for {argv}:"
        a = flags.get("a", 0)
        if getattr(message, "simulated", None):
            try:
                if a:
                    auds = bot.data.audio.players[guild.id]
                else:
                    auds = None
            except LookupError:
                auds = None
            f, out = await create_future(
                ytdl.download_file,
                res[0]["url"],
                fmt=fmt,
                start=start,
                end=end,
                auds=auds,
                timeout=540,
            )
            return await bot.send_with_file(
                channel=channel,
                msg="",
                file=f,
                filename=out,
                rename=False,
            )
        desc += "\nDestination format: {." + fmt + "}"
        if start is not None or end is not None:
            desc += f"\nTrim: [{'-' if start is None else start} ~> {'-' if end is None else end}]"
        if a:
            desc += ", Audio settings: {ON}"
        desc += "```*"
        # Encode URL list into bytes and then custom base64 representation, hide in code box header
        url_bytes = bytes(repr([e["url"] for e in res]), "utf-8")
        url_enc = as_str(bytes2b64(url_bytes, True))
        vals = f"{user.id}_{len(res)}_{fmt}_{int(bool(a))}_{start}_{end}"
        msg = "*```" + "\n" * ("z" in flags) + "callback-voice-download-" + vals + "-" + url_enc + "\n" + desc
        emb = discord.Embed(colour=rand_colour())
        emb.set_author(**get_author(user))
        emb.description = "\n".join((f"`【{i}】` [{escape_markdown(e['name'])}]({ensure_url(e['url'])})" for i in range(len(res)) for e in [res[i]]))
        sent = await send_with_reply(channel, message, msg, embed=emb)
        if direct:
            # Automatically proceed to download and convert immediately
            create_task(self._callback_(
                message=sent,
                guild=guild,
                channel=channel,
                reaction=b"0\xef\xb8\x8f\xe2\x83\xa3",
                bot=bot,
                perm=3,
                vals=vals,
                argv=url_enc,
                user=user
            ))
        else:
            # Add reaction numbers corresponding to search results for selection
            for i in range(len(res)):
                async with delay(0.5):
                    create_task(sent.add_reaction(str(i) + as_str(b"\xef\xb8\x8f\xe2\x83\xa3")))
        # await sent.add_reaction("❎")

    async def _callback_(self, message, guild, channel, reaction, bot, perm, vals, argv, user, **void):
        if reaction is None or user.id == bot.id:
            return
        spl = vals.split("_")
        u_id = int(spl[0])
        if user.id == u_id or not perm < 3:
            # Make sure reaction is a valid number
            if b"\xef\xb8\x8f\xe2\x83\xa3" in reaction:
                async with ExceptionSender(channel):
                    # Make sure selected index is valid
                    num = int(as_str(reaction)[0])
                    if num <= int(spl[1]):
                        # Reconstruct list of URLs from hidden encoded data
                        data = ast.literal_eval(as_str(b642bytes(argv, True)))
                        url = data[num]
                        # Perform all these tasks asynchronously to save time
                        with emptyctx:
                            create_task(message.edit(
                                content=ini_md(f"Downloading and converting {sqr_md(ensure_url(url))}..."),
                                embed=None,
                            ))
                            try:
                                if int(spl[3]):
                                    auds = bot.data.audio.players[guild.id]
                                else:
                                    auds = None
                            except LookupError:
                                auds = None
                            start = end = None
                            if len(spl) >= 6:
                                start, end = spl[4:]
                            f, out = await create_future(
                                ytdl.download_file,
                                url,
                                fmt=spl[2],
                                start=start,
                                end=end,
                                auds=auds,
                                timeout=540,
                            )
                            create_task(message.edit(
                                content=ini_md(f"Uploading {sqr_md(out)}..."),
                                embed=None,
                            ))
                            create_task(channel.trigger_typing())
                        resp = await bot.send_with_file(
                            channel=channel,
                            msg="",
                            file=f,
                            filename=out,
                            rename=False,
                        )
                        if resp.attachments and type(f) is str:
                            create_future_ex(os.remove, f, timeout=18)
                        create_task(bot.silent_delete(message, no_log=True))


class UpdateAudio(Database):
    name = "audio"

    def __load__(self):
        self.players = cdict()
        self.audiocache = cdict()
        self.connecting = cdict()

    def is_connecting(self, g):
        if g in self.connecting:
            if utc() - self.connecting[g] < 12:
                return True
            self.connecting.pop(g)
        return False

    # Searches for and extracts incomplete queue entries
    async def research(self, auds):
        if auds.searching >= 1:
            return
        auds.searching += 1
        searched = 0
        q = auds.queue
        async with delay(2):
            for i, e in enumerate(q, 1):
                if searched >= 32 or i > 128:
                    break
                if "research" in e:
                    try:
                        await create_future(ytdl.extract_single, e, timeout=18)
                        e.pop("research", None)
                        searched += 1
                    except:
                        e.pop("research", None)
                        print_exc()
                        break
                    e.pop("id", None)
                if not i & 7:
                    await asyncio.sleep(0.4)
        auds.searching = max(auds.searching - 1, 0)

    # Delays audio player display message by 15 seconds when a user types in the target channel
    async def _typing_(self, channel, user, **void):
        if getattr(channel, "guild", None) is None:
            return
        if channel.guild.id in self.players and user.id != self.bot.id:
            auds = self.players[channel.guild.id]
            if auds.player is not None and channel.id == auds.channel.id:
                t = utc() + 15
                if auds.player.time < t:
                    auds.player.time = t

    # Delays audio player display message by 10 seconds when a user sends a message in the target channel
    async def _send_(self, message, **void):
        if message.guild.id in self.players and message.author.id != self.bot.id:
            auds = self.players[message.guild.id]
            if auds.player is not None and message.channel.id == auds.channel.id:
                t = utc() + 10
                if auds.player.time < t:
                    auds.player.time = t

    # Makes 1 attempt to disconnect a single member from voice.
    async def _dc(self, member):
        with tracebacksuppressor(discord.Forbidden):
            await member.move_to(None)

    async def update_vc(self, guild):
        m = guild.me
        if not self.is_connecting(guild.id) and guild.id not in self.players:
            vc = guild.voice_client
            if vc is not None:
                return await vc.disconnect(force=True)
            if m.voice is not None:
                return await guild.change_voice_state(channel=None)
            if m.guild_permissions.move_members:
                for c in guild.voice_channels:
                    for m in c.members:
                        if m.id == self.bot.id:
                            return await self._dc(m)
        else:
            if m.voice is not None:
                perm = m.permissions_in(m.voice.channel)
                if perm.mute_members and perm.deafen_members:
                    if m.voice.deaf or m.voice.mute or m.voice.afk:
                        return await m.edit(mute=False, deafen=False)

    # Updates all voice clients
    async def __call__(self, guild=None, **void):
        bot = self.bot
        bot = bot
        with tracebacksuppressor(SemaphoreOverflowError):
            async with self._semaphore:
                # Ensure all voice clients are not muted, disconnect ones without matching audio players
                if guild is not None:
                    create_task(self.update_vc(guild))
                else:
                    [create_task(self.update_vc(g)) for g in bot.cache.guilds.values()]
            # Update audio players
            if guild is not None:
                if guild.id in self.players:
                    auds = self.players[guild.id]
                    create_future_ex(auds.update, priority=True)
            else:
                a = 1
                async with delay(0.5):
                    for g in tuple(self.players):
                        with tracebacksuppressor(KeyError):
                            auds = self.players[g]
                            create_future_ex(auds.update, priority=True)
                            create_task(self.research(auds))
                            if auds.queue and not auds.paused and "dailies" in bot.data:
                                if auds.ts is None:
                                    auds.ts = utc()
                                for member in auds.vc.channel.members:
                                    if member.id != bot.id:
                                        vs = member.voice
                                        if vs is not None and not vs.deaf and not vs.self_deaf:
                                            bot.data.dailies.progress_quests(member, "music", utc() - auds.ts)
                                auds.ts = utc()
                            else:
                                auds.ts = None
                        if not a & 15:
                            await asyncio.sleep(0.2)
                        a += 1
                for item in tuple(ytdl.cache.values()):
                    await create_future(item.update)
            create_future_ex(ytdl.update_dl, priority=True)

    def _announce_(self, *args, **kwargs):
        for auds in self.players.values():
            auds.announce(*args, sync=False, **kwargs)

    # Stores all currently playing audio data to temporary database when bot shuts down
    async def _destroy_(self, **void):
        for auds in tuple(self.players.values()):
            d, _ = await create_future(auds.get_dump, True)
            self.data[auds.vc.channel.id] = {"dump": d, "channel": auds.channel.id}
            await create_future(auds.kill, reason="")
            self.update(auds.vc.channel.id)
        for file in tuple(ytdl.cache.values()):
            if not file.loaded:
                await create_future(file.destroy)
        await create_future(self.update, force=True, priority=True)

    # Restores all audio players from temporary database when applicable
    async def _bot_ready_(self, bot, **void):
        ytdl.bot = bot
        for file in os.listdir("cache"):
            if file.endswith(".opus") and file not in ytdl.cache:
                ytdl.cache[file] = f = AudioFile(file, "cache/" + file)
                f.wasfile = True
                f.loading = f.buffered = f.loaded = True
                f.proc = cdict(is_running=lambda: False, kill=lambda: None)
                f.ensure_time()
                print("reinstating audio file", file)
        for k, v in self.data.items():
            with tracebacksuppressor:
                vc = await bot.fetch_channel(k)
                channel = await bot.fetch_channel(v["channel"])
                guild = channel.guild
                bot = bot
                user = bot.user
                perm = inf
                name = "dump"
                argv = v["dump"]
                flags = "h"
                message = cdict(attachments=None)
                for dump in bot.commands.dump:
                    print("auto-loading queue of", len(argv["queue"]), "items to", guild)
                    create_task(dump(guild, channel, user, bot, perm, name, argv, flags, message, vc=vc))
        self.data.clear()


class UpdatePlaylists(Database):
    name = "playlists"


class UpdateAudioSettings(Database):
    name = "audiosettings"
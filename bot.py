import discord
from discord.ext import commands
import asyncio
import yt_dlp
import os
from flask import Flask
from threading import Thread

# Flask (Render için)
app = Flask(__name__)

@app.route('/')
def home():
    return "🎵 Kross Music Bot - Aktif"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# -------------------- AYARLAR --------------------
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='.', intents=intents, help_command=None)

music_queues = {}
loop_modes = {}

# -------------------- YT-DLP AYARLARI (ÇALIŞAN) --------------------
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': False,
    'quiet': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extract_flat': False,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web'],
            'skip': ['webpage'],
        }
    },
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url') or data.get('url')
        self.thumbnail = data.get('thumbnail')
        self.duration = data.get('duration')
        self.uploader = data.get('uploader') or 'Bilinmiyor'
        if self.duration is None:
            self.duration = 0

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        
        if 'entries' in data:
            entries = [e for e in data['entries'] if e]
            if not entries:
                raise Exception("Sonuç bulunamadı!")
            sources = []
            for entry in entries:
                try:
                    filename = entry['url'] if stream else ytdl.prepare_filename(entry)
                    sources.append(cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=entry))
                except:
                    continue
            if not sources:
                raise Exception("Hiçbir şarkı çalınamadı!")
            return sources
        
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)

# -------------------- YARDIMCI --------------------
async def play_next(guild_id, voice_client):
    loop_mode = loop_modes.get(guild_id, 'none')
    
    if loop_mode == 'song' and voice_client.source:
        current_url = voice_client.source.url
        try:
            new_source = await YTDLSource.from_url(current_url, loop=bot.loop, stream=True)
            voice_client.play(new_source, after=lambda e: asyncio.run_coroutine_threadsafe(
                play_next(guild_id, voice_client), bot.loop).result())
        except:
            await voice_client.disconnect()
        return
    
    queue = music_queues.get(guild_id, [])
    
    if queue:
        next_song = queue.pop(0)
        voice_client.play(next_song, after=lambda e: asyncio.run_coroutine_threadsafe(
            play_next(guild_id, voice_client), bot.loop).result())
    else:
        if loop_mode == 'queue':
            return
        await asyncio.sleep(300)
        if guild_id in music_queues and not music_queues[guild_id]:
            if voice_client.is_connected():
                await voice_client.disconnect()

# -------------------- HAZIR --------------------
@bot.event
async def on_ready():
    print(f"🎵 {bot.user} aktif!")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, name=".yardim | Kross Music"))

# -------------------- PLAY --------------------
@bot.command(name='play', aliases=['p'])
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        return await ctx.send("❌ Önce bir ses kanalına katıl!")
    
    voice_client = ctx.voice_client
    
    if not voice_client:
        voice_client = await ctx.author.voice.channel.connect()
    elif voice_client.channel != ctx.author.voice.channel:
        return await ctx.send("❌ Başka bir kanaldayım, önce beni çağır!")
    
    async with ctx.typing():
        try:
            result = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
            
            if isinstance(result, list):
                if ctx.guild.id not in music_queues:
                    music_queues[ctx.guild.id] = []
                music_queues[ctx.guild.id].extend(result)
                
                embed = discord.Embed(
                    title="📋 Kuyruğa Eklendi",
                    description=f"**{len(result)}** şarkı eklendi!",
                    color=0x5865F2
                )
                embed.set_footer(text=f"İsteyen: {ctx.author.name}")
                await ctx.send(embed=embed)
                
                if not voice_client.is_playing():
                    await play_next(ctx.guild.id, voice_client)
            else:
                if ctx.guild.id not in music_queues:
                    music_queues[ctx.guild.id] = []
                music_queues[ctx.guild.id].append(result)
                
                embed = discord.Embed(
                    title="🎵 Kuyruğa Eklendi",
                    description=f"**{result.title}**",
                    color=0x5865F2
                )
                embed.add_field(name="🎤 Yükleyen", value=result.uploader, inline=True)
                if result.duration:
                    mins, secs = divmod(result.duration, 60)
                    embed.add_field(name="⏱️ Süre", value=f"{mins}:{secs:02d}", inline=True)
                if result.thumbnail:
                    embed.set_thumbnail(url=result.thumbnail)
                embed.set_footer(text=f"İsteyen: {ctx.author.name}")
                await ctx.send(embed=embed)
                
                if not voice_client.is_playing():
                    await play_next(ctx.guild.id, voice_client)
                    
        except Exception as e:
            await ctx.send(f"❌ Hata: {str(e)[:100]}")

# -------------------- DİĞER KOMUTLAR --------------------
@bot.command(name='skip', aliases=['s'])
async def skip(ctx):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_playing():
        return await ctx.send("❌ Çalan şarkı yok!")
    voice_client.stop()
    await ctx.send(f"⏭️ **Geçildi** - {ctx.author.mention}")

@bot.command(name='stop')
async def stop(ctx):
    voice_client = ctx.voice_client
    if not voice_client:
        return await ctx.send("❌ Zaten bir kanalda değilim!")
    if ctx.guild.id in music_queues:
        music_queues[ctx.guild.id] = []
    if ctx.guild.id in loop_modes:
        loop_modes[ctx.guild.id] = 'none'
    voice_client.stop()
    await voice_client.disconnect()
    await ctx.send("⏹️ **Durduruldu ve çıkıldı!**")

@bot.command(name='queue', aliases=['q'])
async def queue(ctx):
    queue = music_queues.get(ctx.guild.id, [])
    if not queue:
        return await ctx.send("📭 **Kuyruk boş!**")
    
    embed = discord.Embed(title="🎵 Müzik Sırası", color=0x5865F2)
    for i, song in enumerate(queue[:10], 1):
        embed.add_field(name=f"#{i}", value=f"**{song.title}** - {song.uploader}", inline=False)
    if len(queue) > 10:
        embed.set_footer(text=f"...ve {len(queue) - 10} şarkı daha")
    await ctx.send(embed=embed)

@bot.command(name='loop', aliases=['l'])
async def loop(ctx, mode: str = None):
    if mode is None:
        current = loop_modes.get(ctx.guild.id, 'none')
        return await ctx.send(f"🔁 Loop: **{current}**")
    
    mode = mode.lower()
    if mode == 'song':
        loop_modes[ctx.guild.id] = 'song'
        await ctx.send("🔁 **Şarkı tekrarlanıyor**")
    elif mode in ['queue', 'sıra']:
        loop_modes[ctx.guild.id] = 'queue'
        await ctx.send("🔁 **Kuyruk tekrarlanıyor**")
    elif mode == 'off':
        loop_modes[ctx.guild.id] = 'none'
        await ctx.send("🔁 **Loop kapandı**")
    else:
        await ctx.send("❌ `.loop song` / `.loop queue` / `.loop off`")

@bot.command(name='volume', aliases=['vol', 'v'])
async def volume(ctx, vol: int = None):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_playing():
        return await ctx.send("❌ Çalan şarkı yok!")
    if vol is None:
        return await ctx.send(f"🔊 Ses: **%{int(voice_client.source.volume * 100)}**")
    if 1 <= vol <= 100:
        voice_client.source.volume = vol / 100
        await ctx.send(f"🔊 Ses: **%{vol}**")
    else:
        await ctx.send("❌ 1-100 arası gir!")

@bot.command(name='nowplaying', aliases=['np'])
async def now_playing(ctx):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_playing():
        return await ctx.send("❌ Çalan şarkı yok!")
    
    source = voice_client.source
    embed = discord.Embed(title="🎵 Şimdi Çalıyor", description=f"**{source.title}**", color=0x5865F2)
    embed.add_field(name="🎤 Yükleyen", value=source.uploader, inline=True)
    embed.add_field(name="🔊 Ses", value=f"%{int(source.volume * 100)}", inline=True)
    if source.duration:
        mins, secs = divmod(source.duration, 60)
        embed.add_field(name="⏱️ Süre", value=f"{mins}:{secs:02d}", inline=True)
    if source.thumbnail:
        embed.set_thumbnail(url=source.thumbnail)
    await ctx.send(embed=embed)

@bot.command(name='pause')
async def pause(ctx):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_playing():
        return await ctx.send("❌ Çalan şarkı yok!")
    voice_client.pause()
    await ctx.send("⏸️ **Duraklatıldı!**")

@bot.command(name='resume')
async def resume(ctx):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_paused():
        return await ctx.send("❌ Duraklatılmış şarkı yok!")
    voice_client.resume()
    await ctx.send("▶️ **Devam ediyor!**")

@bot.command(name='remove')
async def remove(ctx, index: int):
    queue = music_queues.get(ctx.guild.id, [])
    if not queue:
        return await ctx.send("📭 Kuyruk boş!")
    if 1 <= index <= len(queue):
        removed = queue.pop(index - 1)
        await ctx.send(f"🗑️ Silindi: **{removed.title}**")
    else:
        await ctx.send(f"❌ 1-{len(queue)} arası gir!")

@bot.command(name='clearqueue', aliases=['cq'])
async def clear_queue(ctx):
    if ctx.guild.id in music_queues:
        music_queues[ctx.guild.id] = []
    await ctx.send("🗑️ **Kuyruk temizlendi!**")

# -------------------- YARDIM --------------------
@bot.command(name='yardim', aliases=['h', 'help'])
async def yardim(ctx):
    embed = discord.Embed(
        title="🎵 KROSS MUSIC BOT",
        description="`.play şarkı/link` ile başla!",
        color=0x5865F2
    )
    embed.add_field(name="🎵 Çal", value="`.play` `.p`", inline=True)
    embed.add_field(name="⏭️ Geç", value="`.skip` `.s`", inline=True)
    embed.add_field(name="⏹️ Durdur", value="`.stop`", inline=True)
    embed.add_field(name="📋 Sıra", value="`.queue` `.q`", inline=True)
    embed.add_field(name="🔁 Loop", value="`.loop song/queue/off`", inline=True)
    embed.add_field(name="🔊 Ses", value="`.volume 1-100`", inline=True)
    embed.add_field(name="🎵 Bilgi", value="`.nowplaying` `.np`", inline=True)
    embed.add_field(name="⏸️ Pause", value="`.pause` `.resume`", inline=True)
    embed.add_field(name="🗑️ Sil", value="`.remove` `.clearqueue`", inline=True)
    embed.set_footer(text="Prefix: . | YouTube, Spotify, SoundCloud")
    await ctx.send(embed=embed)

# -------------------- BAŞLAT --------------------
if __name__ == "__main__":
    os.makedirs("cache", exist_ok=True)
    Thread(target=run_flask).start()
    print("🎵 Kross Music Bot başlatılıyor...")
    TOKEN = os.environ.get('DISCORD_TOKEN')
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ DISCORD_TOKEN ortam değişkeni bulunamadı!")

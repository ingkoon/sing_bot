import discord
from discord.ext.commands import Bot
from dico_token import Token
 
client = discord.Client()
# 사용자가 명령어 입력 시 ./를 입력하고 명령어 입력
client = commands.Bot(command_prefix='./')
 
# on_ready는 시작할 때 한번만 실행.
@client.event
async def on_ready():
    print('Login...')
    print(f'{client.user}에 로그인하였습니다.')
    print(f'ID: {client.user.name}')
    await client.change_presence(status=discord.Status.online, activity=discord.Game('VS Code로 개발'))
 
@client.event
async def on_message(message):
	# message.content.startswith()는 해당 문자로 시작하는 단어에 대해서
	# 인식하여 메시지 전송. ==로 비교 시 해당 문자만 인식
	if message.content.startswith('테스트'):
		await message.channel.send("{} | {}, 안녕!".format(message.author, message.author.mention))
 
	if message.content == '테스트':
 		# 채널에 메시지 전송
 		await message.channel.send("{} | {}, 어서오세요!".format(message.author, message.author.mention))
        
 	# 아래 코드는 개인 메시지로 전송
    # await message.author.send("{} | {} 유저님, 환영합니다.".format(message.author, message.author.mention))
 
# 아래 코드들은 client.event의 on_message를 주석 처리하고 실행
@client.command(aliases=['hi'])
async def hello(ctx):
    await ctx.send("안녕하세요!")
 
@client.command(aliases=['로그인', '접속하기'])
async def login(ctx):
    await ctx.channel.send("{} | {}님, 어서오세요!".format(ctx.author, ctx.author.mention))
 
client.run(Token)
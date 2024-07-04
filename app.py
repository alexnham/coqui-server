import asyncio
import websockets
import sys
import json
import base64
import ssl
import time
from dotenv import load_dotenv
import os
from runGroq import runGroq
from coqui_tts import tts_to_file
from pydub import AudioSegment
from scipy.io.wavfile import write
import subprocess
import time




async def toMulaw8000():
    # Load and preprocess audio
    sox_command = 'sox output.wav -t wav -r 8000 -e mu-law -b 8 audio_mulaw_8000.wav'
    process = await asyncio.create_subprocess_shell(
        sox_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        print(f"Failed to convert audio: {stderr.decode('utf-8')}")
        return None
    else:
        print("Audio converted")
    
    # Read and encode the saved file
    with open("audio_mulaw_8000.wav", "rb") as audio_file:
        print('returning')
        return base64.b64encode(audio_file.read()).decode('utf-8')



load_dotenv()
def deepgram_connect():
    # Replace with your Deepgram API key.
    extra_headers = {
        'Authorization': f'Token {os.getenv("DEEPGRAM")}'
    }
    
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    deepgram_ws = websockets.connect("wss://api.deepgram.com/v1/listen?encoding=mulaw&sample_rate=8000&endpointing=300", extra_headers=extra_headers, ssl=ssl_context)

    return deepgram_ws

async def proxy(client_ws, path):
    inbox = asyncio.Queue()
    outbox = asyncio.Queue()

    print('started proxy')
    conversation = []

    # use these for timing
    audio_cursor = 0.
    conn_start = time.time()
    streamSid = None
    conversation = []
    async with deepgram_connect() as deepgram_ws:
        async def deepgram_sender(deepgram_ws):
            print('started deepgram sender')
            while True:
                chunk = await outbox.get()
                await deepgram_ws.send(chunk)
            print('finished deepgram sender')

        async def deepgram_receiver(deepgram_ws):
            print('started deepgram receiver')
            nonlocal audio_cursor
            async for message in deepgram_ws:
              #  try:
                dg_json = json.loads(message)

                # print the results from deepgram!
                #print(dg_json)

                # do this logic for timing
                # NOTE: it only makes sense to measure timing for interim results, see this doc for more details: https://docs.deepgram.com/streaming/tutorials/latency.html
                if(dg_json["speech_final"] and dg_json["channel"]["alternatives"][0]["transcript"] != ""):
                    content = dg_json["channel"]["alternatives"][0]["transcript"]
                    print(dg_json["channel"]["alternatives"][0]["transcript"])
                    start = time.time()

                    #llm
                    conversation.append({'role':'user', 'content':content})
                    llmResponse = runGroq(conversation)
                    print(llmResponse)
                    conversation.append({'role':'assistant', 'content': llmResponse})
                    #tts
                    await tts_to_file(llmResponse)
                    #conversion
                    
                    payload = await toMulaw8000()
                    #send back
                    media_response = {
                        'event':'media',
                        'streamSid': streamSid,
                        'media': {
                            'payload':payload
                        }
                    }
                    end = time.time()
                    print(f"Time taken to run the code was {end-start} seconds")
                    await client_ws.send(json.dumps(media_response))  

               # except Exception as e:
                #    print(e)
                 #   print('was not able to parse deepgram response as json')
                  #  continue
            print('finished deepgram receiver')

        async def client_receiver(client_ws):
            print('started client receiver')
            json_string = client_ws.messages[1]
            message_dict = json.loads(json_string)
            nonlocal audio_cursor, streamSid
            streamSid = message_dict.get('streamSid')

            # we will use a buffer of 20 messages (20 * 160 bytes, 0.4 seconds) to improve throughput performance
            # NOTE: twilio seems to consistently send media messages of 160 bytes
            BUFFER_SIZE = 20 * 160
            buffer = bytearray(b'')
            empty_byte_received = False
            async for message in client_ws:
                try:
                    data = json.loads(message)
                    if data["event"] in ("connected", "start"):
                        print("Media WS: Received event connected or start")
                        continue
                    if data["event"] == "media":
                        media = data["media"]
                        chunk = base64.b64decode(media["payload"])
                        time_increment = len(chunk) / 8000.0
                        audio_cursor += time_increment
                        buffer.extend(chunk)
                        if chunk == b'':
                            empty_byte_received = True
                    if data["event"] == "stop":
                        print("Media WS: Received event stop")
                        break

                    # check if our buffer is ready to send to our outbox (and, thus, then to deepgram)
                    if len(buffer) >= BUFFER_SIZE or empty_byte_received:
                        outbox.put_nowait(buffer)
                        buffer = bytearray(b'')
                except:
                    print('message from client not formatted correctly, bailing')
                    break

            # if the empty byte was received, the async for loop should end, and we should here forward the empty byte to deepgram
            # or, if the empty byte was not received, but the WS connection to the client (twilio) died, then the async for loop will end and we should forward an empty byte to deepgram
            outbox.put_nowait(b'')
            print('finished client receiver')

        await asyncio.wait([
            asyncio.ensure_future(deepgram_sender(deepgram_ws)),
            asyncio.ensure_future(deepgram_receiver(deepgram_ws)),
            asyncio.ensure_future(client_receiver(client_ws))
        ])

        client_ws.close()
        print('finished running the proxy')

def main():
    print('begin')
    proxy_server = websockets.serve(proxy, 'localhost', 5000)
    asyncio.get_event_loop().run_until_complete(proxy_server)
    asyncio.get_event_loop().run_forever()
    print('running')

if __name__ == '__main__':
    sys.exit(main() or 0)

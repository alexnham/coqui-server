from TTS.api import TTS
import asyncio


async def tts_to_file(text):

    if not text:
        return jsonify({"error": "No text provided"}), 400
    try:
        tts = TTS("tts_models/en/jenny/jenny")
        tts.tts_to_file(text=text)
        return 'output.wav'
    except Exception as e:
        return e

import os
from groq import Groq
from dotenv import load_dotenv
load_dotenv()
def runGroq(content):
    client = Groq(
        api_key=os.getenv('GROQ_API_KEY'),
    )

    chat_completion = client.chat.completions.create(
        messages=content,
        model="llama3-8b-8192"
    )
    return chat_completion.choices[0].message.content

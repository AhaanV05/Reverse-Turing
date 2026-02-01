from openai import OpenAI
from config import APIKEY, APIKEY1

# client = OpenAI(
#   base_url="https://openrouter.ai/api/v1",
#   api_key=APIKEY,
# )
# completion = client.chat.completions.create(
#     model="meta-llama/llama-3.3-70b-instruct:free",
#     messages=[]
# )




      
# import asyncio
# asyncio.run(get_completion(new_messages))
# while 1:
#     msg = input("You: ")
#     messages.append(
#         {
#             "role": "user",
#             "content": msg
#         }
#     )
#     completion = client.chat.completions.create(
#         model="meta-llama/llama-3.3-70b-instruct:free",
#         messages=messages
#     )

#     print("AI: ", completion.choices[0].message.content)
#     messages.append(
#         {
#             "role": "assistant",
#             "content": completion.choices[0].message.content
#         }
#     )

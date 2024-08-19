import json

import requests
from openai import OpenAI
import time
import random
import openai
import anthropic
import os
import yaml


# ./tools.py
def load_json_file(json_path):
  with open(json_path) as f:
    data = json.load(f)
  return data


def dump_json_file(json_path, data):
  with open(json_path, 'w') as f:
    json.dump(data, f)


def dump_jsonl_file(jsonl_path, data):
  with open(jsonl_path, 'a') as f:
    json.dump(data, f)
    f.write('\n')


def debug_query_gptv2(prompt: str, model_name: str):
  client = OpenAI(base_url='https://chat1.plus7.plus/v1',
                  api_key='sk-gRHvMVThd4k5T7ch9dB90f54DcA74926A9C938C5088d7bFe')
  completion = client.chat.completions.create(messages=[{
      "role": "user",
      "content": prompt,
  }],
                                              model=model_name,
                                              timeout=60)
  res = completion.choices[0].message.content
  return res


def escape_xml_chars(input_str):
  """
    Escapes special characters in a string for XML compatibility.

    Args:
        input_str (str): The input string to be escaped.

    Returns:
        str: The escaped string suitable for XML use.
    """
  if not input_str:
    return input_str
  return (input_str.replace("&", "&amp;").replace("<", "&lt;").replace(
      ">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


def load_txt_file(txt_path):
  with open(txt_path, 'r', encoding='utf-8') as f:
    data = f.read()
  return data


def write_txt_file(txt_path, data):
  with open(txt_path, 'w') as f:
    f.write(data)


def load_yaml_file(yaml_path):
  with open(yaml_path, 'r') as f:
    data = yaml.safe_load(f)
  return data


def dump_yaml_file(yaml_path, data):
  with open(yaml_path, 'w', encoding='utf-8') as f:
    yaml.dump(data, f)


def load_jsonl_file(jsonl_path):
  data = []
  with open(jsonl_path, 'r') as f:
    for line in f:
      data.append(json.loads(line))
  return data


def dump_jsonl_file(dict_list, filename):
  with open(filename, 'w') as file:
    for dict_item in dict_list:
      json_str = json.dumps(dict_item)
      file.write(json_str + '\n')


def query_gpt(prompt, model="gpt-3.5-turbo"):
  '''
  @param model:
    claude-3-opus-20240229
    gpt-3.5-turbo
    gpt-4
  '''
  max_retry = 8
  if model.startswith("gpt"):
    cli = OpenAI(base_url=os.environ['OPENAI_API_URL'],
                 api_key=os.environ['OPENAI_API_KEY'])
    retry = 0
    err = None
    while retry < max_retry:
      try:
        completion = cli.chat.completions.create(messages=[{
            "role": "user",
            "content": prompt,
        }],
                                                 model=model,
                                                 timeout=60)
        break
      except Exception as e:
        print(f'retrying {retry} times...')
        retry += 1
        err = e
        continue

    if retry == max_retry:
      raise err

    usage = {
      "prompt_tokens": response['usage']['prompt_tokens'],
      "completion_tokens": response['usage']['completion_tokens']
    }
    # "usage": {
    #   "prompt_tokens": 9,
    #   "completion_tokens": 12,
    #   "total_tokens": 21
    # }
    res = completion.choices[0].message.content

  elif model.startswith("claude"):
    url = os.environ['ANTHROPIC_API_URL']

    headers = {
        'x-api-key': os.environ['ANTHROPIC_API_KEY'],
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
    }

    data = {
        "model": "claude-3-opus-20240229",
        "max_tokens": 1024,
        "stream": False,
        "messages": [{
            "role": "user",
            "content": prompt
        }]
    }

    retry = 0
    err = None
    while retry < max_retry:
      try:
        response = requests.post(
            url,
            headers=headers,
            data=json.dumps(data),
            timeout=30,
        )
        break
      except Exception as e:
        retry += 1
        err = e
        continue

    if retry == max_retry:
      raise err

    usage = {
      "prompt_tokens": response.json()['usage']['input_tokens'],
      "completion_tokens": response.json()['usage']['output_tokens']
    }
    # "usage": 
    #   {
    #     "input_tokens": 12,
    #     "output_tokens": 6
    #   }
    res = response.json()['content'][0]['text']

  return res, usage


def convert_gpt_answer_to_json(answer,
                               model_name,
                               default_value={'default': 'format wrong'},
                               query_func=query_gpt):
  import ast
  convert_prompt = f'''
Convert the following data into JSON dict format. Return only the dict. Ensuring it's valid for Python parsing (pay attention to single/double quotes in the strings).

data:
{answer}

**Please do not output any content other than the JSON dict format.**
'''
  try:
    answer = answer.replace('```json', '').replace('```dict', '').replace(
        '```list', '').replace('```python', '')
    answer = answer.replace('```', '').strip()

    converted_answer = ast.literal_eval(answer)
    usage = None
  except:
    print('*' * 10, 'converting', '*' * 10, '\n', answer, '\n', '*' * 50)
    converted_answer, usage = query_func(convert_prompt, model_name)
    print('*' * 10, 'converted v1', '*' * 10, '\n', converted_answer, '\n',
          '*' * 10)
    if isinstance(converted_answer, str):
      try:
        converted_answer = converted_answer.replace('```json', '').replace(
            '```dict', '').replace('```list', '').replace('```python', '')
        converted_answer = converted_answer.replace('```', '').strip()
        converted_answer = ast.literal_eval(converted_answer)
      except:
        new_convert = f'''
Convert the following data into JSON dict format. Return only the JSON dict. Ensuring it's valid for Python parsing (pay attention to single/double quotes in the strings).
data:
{answer}

The former answer you returned:
{converted_answer}
is wrong and can not be parsed in python. Please check it and convert it properly!

**Please do not output any content other than the JSON dict format!!!**
'''
        converted_answer, usage1 = query_func(new_convert, model_name)
        print('*' * 10, 'converted v2', '*' * 10, '\n', converted_answer, '\n',
              '*' * 10)
        
        usage = {
          "prompt_tokens": usage['prompt_tokens'] + usage1['prompt_tokens'],
          "completion_tokens": usage['completion_tokens'] + usage1['completion_tokens']
        }
        if isinstance(converted_answer, str):
          try:
            converted_answer = converted_answer.replace('```json', '').replace(
                '```dict', '').replace('```list', '').replace('```python', '')
            converted_answer = converted_answer.replace('```', '').strip()
            converted_answer = ast.literal_eval(converted_answer)
          except:
            return default_value, usage
  return converted_answer, usage


def get_combined_code(pre_code_path, code):
  preparation_code = load_txt_file(pre_code_path)
  combined_code = preparation_code + '\n' + code
  return combined_code


def get_code_without_prefix(pre_code_path, code):
  preparation_code = load_txt_file(pre_code_path)
  stripped_code = code.replace(f'{preparation_code}\n', '')
  return stripped_code


def get_leading_tabs(string):
  '''
    extract the tabs at the beginning of a string
    '''
  space_num = len(string) - len(string.lstrip(' '))
  tabs_num = len(string) - len(string.lstrip('\t'))
  return space_num * ' ' + tabs_num * '\t'


def get_all_error_file_names(dir_path):
  json_files = []
  for root, dirs, files in os.walk(dir_path):
    for file in files:
      if file.endswith(".json") and 'error_' in file:
        json_files.append(os.path.join(root, file))
  return json_files


def write_dict_to_txt(file_path, data):
  dict_str = ''
  for k, v in data.items():
    dict_str += f'{k}: \n' + '=' * 100 + f'\n{v}' + '\n' + '-' * 100 + '\n'
  write_txt_file(file_path, dict_str)


def load_txt_to_dict(file_path):

  def remove_n(string):
    while string[0] == '\n' or string[0] == ' ':
      string = string[1:]
    while string[-1] == '\n' or string[-1] == ' ':
      string = string[:-1]
    return string

  result_dict = {}
  dict_str = load_txt_file(file_path)
  k_v_pairs = dict_str.split('\n' + '-' * 100 + '\n')
  for k_v in k_v_pairs:
    k_v_pair = k_v.split(': \n' + '=' * 100)

    if len(k_v_pair) < 2:
      continue
    result_dict[remove_n(k_v_pair[0])] = remove_n(k_v_pair[1])
  return result_dict


# ./taskbot/tools.py
class Tools:

  def __init__(self):
    pass

  @staticmethod
  def load_json(file_path):
    with open(file_path, 'r') as file:
      data = json.load(file)
    return data

  @staticmethod
  def save_json(data, file_path):
    with open(file_path, 'w') as file:
      json.dump(data, file, indent=4)

  @staticmethod
  def load_txt_file(file_path):
    with open(file_path, 'r') as file:
      data = file.read()
    return data

  @staticmethod
  def write_to_txt_file(data, file_path):
    with open(file_path, 'w') as file:
      file.write(data)

  @staticmethod
  def debug_query_gptv2(prompt: str, model_name: str):
    client = OpenAI(base_url=os.environ['OPENAI_API_URL'],
                    api_key=os.environ['OPENAI_API_KEY'])
    completion = client.chat.completions.create(messages=[{
        "role": "user",
        "content": prompt,
    }],
                                                model=model_name,
                                                timeout=60)
    res = completion.choices[0].message.content
    return res

  @staticmethod
  def query_gpt(prompt: str, model_name="gpt-3.5-turbo", retry_times=6):
    client = OpenAI(base_url=os.environ['OPENAI_API_URL'],
                    api_key=os.environ['OPENAI_API_KEY'])
    retry = 0
    err = 0
    while retry < retry_times:
      try:
        completion = client.chat.completions.create(messages=[{
            "role": "user",
            "content": prompt,
        }],
                                                    model=model_name,
                                                    timeout=60)
        res = completion.choices[0].message.content
        break
      except Exception as e:
        retry += 1
        time.sleep(random.uniform(0.5 + 1 * retry, 1.5 + 1 * retry))
        print(f'retrying {retry} times...')
        err = e
    else:
      raise err

    print(f'GPT answer: {res}')
    return res

  @staticmethod
  def debug_query_gpt(prompt: str, model_name="gpt-3.5-turbo", retry_times=6):
    client = OpenAI(base_url=os.environ['OPENAI_API_URL'],
                    api_key=os.environ['OPENAI_API_KEY'])

    completion = client.chat.completions.create(messages=[{
        "role": "user",
        "content": prompt,
    }],
                                                model=model_name,
                                                timeout=60)
    res = completion.choices[0].message.content
    return res

  @staticmethod
  def debug_query_claude(prompt: str,
                         identifier="",
                         model_name="claude-3-haiku-20240307"):
    client = anthropic.Anthropic(base_url=os.environ.get('ANTHROPIC_API_URL'),
                                 api_key=os.environ.get('ANTHROPIC_API_KEY'))
    message = client.messages.create(model=model_name,
                                     max_tokens=4096,
                                     messages=[{
                                         "role": "user",
                                         "content": prompt
                                     }])
    return message.content[0].text

  @staticmethod
  def query_claude(prompt: str,
                   model_name="claude-3-haiku-20240307",
                   retry_times=6):
    client = anthropic.Anthropic(base_url=os.environ.get('ANTHROPIC_API_URL'),
                                 api_key=os.environ.get('ANTHROPIC_API_KEY'))
    retry = 0
    while retry < retry_times:
      try:
        message = client.messages.create(model=model_name,
                                         max_tokens=4096,
                                         messages=[{
                                             "role": "user",
                                             "content": prompt
                                         }])
        res = message.content[0].text
        break
      except Exception as e:
        retry += 1
        time.sleep(random.uniform(0.5 + 1 * retry, 1.5 + 1 * retry))
        print(f'retrying {retry} times...')
        err = e
    else:
      raise err

    print(f'Claude answer: {res}')
    return res

  def query_llm(prompt: str, model_name="", retry_times=6):
    openai.base_url = os.environ.get('LLM_API_URL')
    openai.api_key = os.environ.get('LLM_API_KEY')

    # create a completion
    retry = 0
    err = None
    while retry < retry_times:
      try:
        completion = openai.completions.create(model=model_name,
                                               prompt=prompt,
                                               max_tokens=4096)

        # create a chat completion
        completion = openai.chat.completions.create(model=model_name,
                                                    messages=[{
                                                        "role": "user",
                                                        "content": prompt
                                                    }],
                                                    timeout=120)
        res = completion.choices[0].message.content
        break
      except Exception as e:
        retry += 1
        time.sleep(random.uniform(0.5 + 1 * retry, 1.5 + 1 * retry))
        print(f'retrying {retry} times...')
        err = e
    else:
      raise err

    print(f'{model_name} answer: {res}')
    return res


if __name__ == '__main__':
  prompt = '''Suppose you are using a Notes app where you can complete tasks by interacting with the app. Here are some simple tasks you can perform:

'Create a new note with the title "Grocery List"'
- 'Export the note titled "Meeting Notes" as a file'
- 'Rename the note titled "Old Title" to "New Title"'
- 'Delete the note titled "Unwanted Note"'
- 'Lock the note titled "Private Note"'
- 'Close the search box'
- 'Create a shortcut for the current note'
- 'Edit the content of the current note to "Discuss budget allocations"'
- 'Open the about page of the app'
- 'Delete the current note'
- 'Scroll to the next note or checklist item'
- 'Print the current note'
- 'Lock the current note with a password'
- 'Save the edits made to the current note'
- 'Scroll down the settings page''
- 'Set the font size of the note to 175%'
- 'Switch to the next checklist item'
- 'Increase the font size to 250%'
- 'Add a new checklist item titled "Grocery Shopping"'
- 'Search for the word "meeting" in the current note'
- 'Print the note titled "To Print"'
- 'Remove done items from the checklist titled "To Do"'
- 'Scroll down the settings page'
- 'Exit the settings page'
- 'Create a shortcut for the note titled "Frequently Used"'
- "Set the place cursor to the end of the note."
- "Open the note titled 'Grocery List'."
- "Make links and emails clickable in the settings."
- "Create a new note titled 'Meeting Agenda'."
- "Exit the settings page."

Please think of some complex tasks by combining the above tasks or creating more complex control flows. Use the following JSON format:
```json
{
    'complex task 1': {
        'task': '<task description 1, should be a sentence>',
        'solution': '<a simple guideline about how to complete complex task 1>'
    }, 
    'complex task 2': {
        'task': '<task description 2, should be a sentence>',
        'solution': '<a simple guideline about how to complete complex task 2>'
    },
    ...
}
```

When generating the specific tasks, ensure the following:
- You should be specific and avoid vague tasks. for example, you are forbidden to give tasks like "Send a message", instead, you should say "Send a message 'good morning' to Alice". Namely, you should be ensure your task descriptions are detailed, incorporating elements like names, accounts, phone numbers, and addresses.
- Focus on end-user actions rather than detailing every step or UI element involved. Your tasks should mimic natural language commands that a user might give to a virtual assistant like Siri, but should be more complex. 
- **Please do not output anything else but the JSON content**'''
  Tools.query_gpt(prompt, model_name='gpt-4o')

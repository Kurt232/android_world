import json
import os
import multiprocessing

from android_world.script_utils.tools import Tools


class MultiProcessingQuery:

  gpt_models = [
      "gpt-3.5-turbo", "gpt-3.5-turbo-16k", "gpt-4", "gpt-4-32k", "gpt-4o",
      "gpt-4-turbo"
  ]
  claude_models = [
      "claude-3-haiku-20240307", "claude-3-opus-20240229",
      "claude-3-sonnet-20240229"
  ]

  def __init__(self,
               output_file,
               model="claude-3-haiku-20240307",
               is_json=False):
    '''
    model:
      claude-3-haiku-20240307
      claude-3-opus-20240229
      claude-3-sonnet-20240229
      gpt-3.5-turbo
      gpt-3.5-turbo-16k
      gpt-4
      gpt-4-32k
    is_json: whether to save the results in json format
    '''
    self.model = model
    self.output_file = output_file
    self.is_json = is_json
    self.json_retry = 3

  def read_from_json(self, file_path):
    results = {}
    try:
      with open(file_path, 'r') as file:
        for line in file:
          result = json.loads(line.strip())
          results.update(result)
    except FileNotFoundError:
      print("The file was not found.")
    except json.JSONDecodeError:
      print("Error decoding JSON.")
    return results

  def query_llm(self, prompt):
    try:
      if self.model in self.gpt_models:
        answer = Tools.query_gpt(prompt, model_name=self.model)
      elif self.model in self.claude_models:
        answer = Tools.query_claude(prompt, model_name=self.model)
      else:
        answer = Tools.query_llm(prompt, model_name=self.model)
      return answer
    except Exception as e:
      raise e

  def save_to_json(self, key, result):
    with open(self.output_file, "a") as f:
      json.dump({key: result}, f)
      f.write("\n")

  def process_func(self, key_value):
    key, value = key_value

    if self.is_json:
      retry = 0
      err = None
      while retry < self.json_retry:
        try:
          res = self.query_llm(value)
          result = json.loads(res)
          break
        except json.JSONDecodeError as e:
          retry += 1
          err = e
          continue
        except Exception as e:
          err = e
          break
      else:
        print(f"Error processing {key=}: {err}")
        result = None

    else:
      try:
        result = self.query_llm(value)
      except Exception as err:
        print(f"Error processing {key=}: {err}")
        result = None

    self.save_to_json(key, result)

  def query_all_dicts(self, dict_questions, worker_num=4):
    pool = multiprocessing.Pool(processes=worker_num)
    try:
      with pool:
        pool.map(self.process_func, dict_questions.items())
    except KeyboardInterrupt:
      pool.close()
      pool.terminate()
      pool.join()
      exit(1)  # still need to exit the program by ps -a and kill -9

  def convert_list_to_dict(self, list_questions):
    return {str(i): question for i, question in enumerate(list_questions)}

  def convert_json_to_dict(self, json_file):
    results = self.read_from_json(json_file)
    result_list = [0 for _ in range(len(list(results.values())))]
    for key, value in results.items():
      result_list[int(key)] = value
    return result_list

  def query_a_list(self, list_questions, worker_num=4):
    dict_questions = self.convert_list_to_dict(list_questions)
    self.query_all_dicts(dict_questions, worker_num)
    return self.convert_json_to_dict(self.output_file)


if __name__ == "__main__":
  sample_dict = {
      "key1": "What is the capital of France?",
      "key2": "Where is Beijing",
      "key3": "how are you?",
      "key4": "good morning",
      "key5": "good evening",
  }

  llm = MultiProcessingQuery('test.json', 'gpt-4o', is_json=False)
  llm.query_all_dicts(sample_dict)

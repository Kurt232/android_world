import json
import os
import tools
import copy
import ast
from itertools import combinations
import logging
import sys
import re
from argparse import ArgumentParser

from android_world.script_utils.parallel_query import MultiProcessingQuery as mtp


def parseargs():
  parser = ArgumentParser()
  parser.add_argument(
      '--mode',
      type=str,
      required=True,
      choices=['doc_format', 'task', 'solution', 'format_solution_output'],
      help=
      'doc_format: format the api paths for raw api document; task: generate tasks for apps; solution: generate solutions for apps'
  )
  return parser.parse_args()


class APIPathSolver:

  def __init__(self, apis_folder_path):
    self.apis_folder_path = apis_folder_path
    self.all_api_paths = []
    self.unique_apis = self.solve_all_api_paths(apis_folder_path)

  def load_data(self, path):
    # eles_data = json.load(open(os.path.join(path, 'ele.json')))
    apis_data = json.load(open(os.path.join(path, 'apis.json')))
    # tree_data = json.load(open(os.path.join(path, 'tree.json')))

    apis = {}
    dep_in = set()  # roots of the dependency tree(forrest)
    dpe_edge = {}
    for _, v in apis_data.items():
      for e in v:
        if e["name"] == "":
          continue
        name = e["name"]
        apis[name] = apis.get(name, e)
        dep = apis[name]["dependency"]
        if len(dep) == 0:
          dep_in.add(name)
        for d in dep:
          if d == '':
            dep_in.add(name)
            continue
          p_name = d[0:-1].split('(')[-1]
          if d.startswith('window'):
            dep_in.add(name)
            continue
          dpe_edge[p_name] = dpe_edge.get(p_name, [])
          dpe_edge[p_name].append(name)

    dep_tree = {
        "name": "root",
        "children": [{
            "name": n,
            "children": [],
        } for n in dep_in]
    }

    queue: list = dep_tree['children'].copy()
    while len(queue) > 0:
      cur = queue.pop(0)
      edge = dpe_edge.get(cur["name"], [])
      for n in edge:
        tmp = {"name": n, "children": []}
        cur['children'].append(tmp)
        queue.append(tmp)

    return apis, dep_tree

  def dfs(self, node, p: list):
    p.append(node['name'])
    if len(node['children']) == 0:
      self.all_api_paths.append(p)
      return
    for n in node['children']:
      self.dfs(n, p.copy())

  def solve_all_api_paths(self, apis_folder_path):
    apis, dep_tree = self.load_data(apis_folder_path)
    self.dfs(dep_tree, [])
    return apis

  def get_path_by_api_name(self, api_name):
    # search the dependency path of the given api_name in the given paths
    all_paths_to_api = []
    for path in self.all_api_paths:
      if api_name in path:
        api_name_index = path.index(api_name)
        path_to_api = path[:api_name_index + 1]
        if path_to_api not in all_paths_to_api:
          all_paths_to_api.append(path_to_api)
    return all_paths_to_api

  def _search_dependency_in_original_apis_json(self, apis, api_name):
    for time_tag, state_data in apis.items():
      for ele in state_data:
        if ele['name'] == api_name:
          return ele['dependency']
    return []

  def _get_api_action_type(self, dependency):
    if 'tap(' in dependency.lower() or 'touch(' in dependency.lower():
      return 'touch'
    elif 'long_touch' in dependency.lower() or 'long_press' in dependency.lower(
    ) or 'long_tap' in dependency.lower():
      return 'long_touch'
    elif 'scroll up' in dependency.lower():
      return 'scroll up'
    elif 'scroll down' in dependency.lower():
      return 'scroll down'
    elif 'input(' in dependency.lower() or 'set_text(' in dependency.lower():
      return 'set_text'
    elif 'select(' in dependency.lower():
      return 'select'
    elif 'match(' in dependency.lower():
      return 'match'
    else:
      return 'unknown'

  def get_path_with_action_type_by_api_name(self, api_name):
    '''
        search the dependency path of the given api_name in the given paths
        '''
    apis_data = json.load(open(os.path.join(self.apis_folder_path,
                                            'apis.json')))

    all_paths_to_api = []
    for path in self.all_api_paths:
      if api_name in path:
        api_name_index = path.index(api_name)
        path_to_api = path[:api_name_index + 1]
        if path_to_api not in all_paths_to_api:
          # add action type for each api in the path
          for i in range(len(path_to_api) - 1):
            if path_to_api[i] == 'root':
              continue
            current_dependency = path_to_api[i]
            # search the dependency data of the next api, match the current api, then get the action type
            original_dependency_data = self._search_dependency_in_original_apis_json(
                apis_data, path_to_api[i + 1])

            for d in original_dependency_data:
              if current_dependency in d:
                current_dependency_action_type = self._get_api_action_type(d)

            path_to_api[i] = {
                'name': path_to_api[i],
                'action_type': current_dependency_action_type
            }
          if path_to_api not in all_paths_to_api:
            all_paths_to_api.append(path_to_api)
    return all_paths_to_api

  def get_path_for_all_apis(self):
    api_paths = {}
    for api_name in self.unique_apis:
      api_paths[api_name] = self.get_path_by_api_name(api_name)
    return api_paths

  def add_action_type_for_dependencies(self):
    api_paths = {}
    for api_name in self.unique_apis:
      api_paths[api_name] = self.get_path_with_action_type_by_api_name(api_name)
    return api_paths


def get_semantic_dependencies(dep_list):
  if len(dep_list) == 0:
    return 'No dependency, this UI element is in the main screen of the app'
  semantic_dependencies = ''
  for dependency_id, dependency in enumerate(dep_list):
    if 'window(' in dependency:
      element_window = dependency.split('(')[-1][:-1]
      semantic_dependency = f'this UI element could be reached in the {element_window} screen of the app'
    elif dependency == '':
      semantic_dependency = 'this UI element could be interacted in the main screen'
    else:
      semantic_dependency = f'this UI element could be interacted after {dependency}'
    semantic_dependencies += f'{semantic_dependency}'
    if dependency_id != len(dep_list) - 1:
      semantic_dependencies += ' or '
  return semantic_dependencies


class TaskGenerator:

  def __init__(self, apis_path, api_tree_paths_path, app_name):
    self.name_to_desc = {}
    self.name_to_func = {}
    self.dependencies = {}
    self.all_prompts = {}

    self.apis_path = apis_path
    self.api_tree_paths_path = api_tree_paths_path
    self.app_name = app_name

  def init_construct_map(self):

    with open(self.apis_path, 'r', encoding='utf-8') as file:
      data = json.load(file)

    for timestamp, elements in data.items():
      # 每个时间戳对应的 element
      for element in elements:
        name = element['name']
        desc = element['desc']
        func = element['func']

        self.name_to_desc[name] = desc
        self.name_to_func[name] = func

  def extract_dependencies(self, data):
    cnt = 0
    for key, value in data.items():
      if isinstance(value, list):
        tmp = []
        for item in value:
          if isinstance(item, list) and len(item) >= 3:
            father_node = item[-2]
            action = father_node['action_type'] + '(' + father_node['name'] + ')'
            tmp.append(action)
        if tmp:
          self.dependencies[key] = tmp
        else:
          self.dependencies[key] = []

  def add_prompt(self, element_name):
    if element_name == '':
      print("element_name is empty")
      return ""

    sub_prompt = ""

    ele = "element: "
    ele += element_name
    ele += '\n'
    sub_prompt += ele

    desc = "Description: "
    desc += self.name_to_desc[element_name]
    desc += '\n'
    sub_prompt += desc

    # func = "Function: "
    # func += name_to_func[element_name]
    # func += '\n'
    # sub_prompt += func

    dependency_list = self.dependencies[element_name]
    if not dependency_list:  # dependency 列表为空
      depe = "Dependency: No dependency, this UI element is in the main screen of the app. \n\n"
      sub_prompt += depe
    else:
      depe = "Dependency: this UI element could be interacted after "
      for i, element in enumerate(dependency_list):
        depe += element
        if i < len(dependency_list) - 1:
          depe += " or "
      #print(depe)
      sub_prompt += depe
      sub_prompt += '\n\n'

    return sub_prompt

  def generate_prompts(self,
                       prompts_path,
                       use_comb=False,
                       ele_group_strides=[2, 4, 6]):
    self.init_construct_map()  # 每个 element 的 name、description、function 存在字典中

    #print(len(name_to_desc)) # 一共 145 个不同的 element

    with open(self.api_tree_paths_path, 'r', encoding='utf-8') as file:
      data = json.load(file)

    self.extract_dependencies(data)  # 提取并存储每个 element 的上一级 dependency

    name_to_desc_list = list(self.name_to_desc.keys())

    if use_comb:
      # 生成所有 C(145, 2) 的组合
      ele_groups = list(combinations(name_to_desc_list, 2))
    else:
      ele_groups = []
      for stride in ele_group_strides:
        for i in range(len(name_to_desc_list) - (stride - 1)):
          ele_groups.append(name_to_desc_list[i:i + stride])

    cnt = 0
    for ele_group in ele_groups:
      # print(f"-------------------------group_id = {cnt}-------------------------")
      # choice1, choice2 = pair
      # if choice1 == '' or choice2 == '':
      if '' in ele_group:
        print(f"one of the elements in {ele_group} is empty, continue")
        continue
      now_prompt_element = {}  # 存储当前的这个 prompt 写了哪些 element，避免重复写
      #print({f"cnt = {cnt}--------------------choice: {choice1}, {choice2}----------"})

      # prompt_prefix  共 C(145,2) 条 prompt
      prompt = f"Suppose you are a dataset annotator who is working on generating a series of tasks about the {self.app_name} APP on a smartphone. You are given a series of UI elements in this APP, which you could interact with by tapping, long tapping, edit, scroll, etc. You should generate as many specific tasks that could be executed by a virtual assistant on a smartphone as possible. Note that the tasks you generate must only involve these elements. \n\nUI elements in the {self.app_name} APP: \n\n"

      prompt_end = '''Please write down the tasks you would like to generate. You must use the following JSON format:

["<Task 1>", "<Task 2>", "<Task 3>"...]

Now please generate the specifc tasks. Notice that:
- You should be specific and avoid vague tasks. for example, you are forbidden to give tasks like "Send a message", instead, you should say "Send a message 'good morning' to Alice". Namely, you should be ensure your task descriptions are detailed, incorporating elements like names, accounts, phone numbers, and addresses.
- Focus on end-user actions rather than detailing every step or UI element involved. Your tasks should mimic natural language commands that a user might give to a virtual assistant like Siri. 
- **Please do not output anything else but the JSON content**'''
      for choice in ele_group:
        if choice not in now_prompt_element:
          now_prompt_element[choice] = 1
          prompt += self.add_prompt(choice)
          #print(f"把 {choice1} 加入 prompt 的 element 中，开始添加从 root 到 {choice1} 路径上的所有 element")

          value = data[choice]  # 当前 element 在 api_paths 中的值
          for item in value:  # 遍历当前元素中的路径
            for sub_item in item:  # 遍历路径中的每个元素
              if isinstance(
                  sub_item,
                  dict) and 'name' in sub_item:  # 判断元素是否为字典且包含'name'字段
                name = sub_item['name']  # 获取'name'字段的值
                if name not in now_prompt_element:
                  now_prompt_element[name] = 1
                  prompt += self.add_prompt(name)
                #print("now prompt: {prompt}")

      prompt += prompt_end
      # group = {"id": cnt, "prompt": prompt}
      self.all_prompts[cnt] = prompt
      cnt += 1

    with open(prompts_path, 'w', encoding='utf-8') as f:
      json.dump(self.all_prompts, f, ensure_ascii=False, indent=4)

    print(f"数据已写入 json 文件中")

  def query_all_task_prompts(self,
                             prompts_path,
                             answers_path,
                             model='gpt-3.5-turbo'):
    # all_prompts = tools.load_json_file(prompts_path)
    gpt = mtp.MultiProcessingQuery(answers_path, model=model, is_json=False)
    gpt.query_all_dicts(self.all_prompts, worker_num=8)


class SolutionGenerator:

  def __init__(self, apis_folder_path, api_paths_file_path):
    self.apis_folder_path = apis_folder_path
    self.api_paths = tools.load_json_file(api_paths_file_path)

  def get_all_tasks(self, tasks_path):
    raw_task_answers = tools.load_jsonl_file(tasks_path)
    all_tasks = []
    for task_answer_data in raw_task_answers:

      if 'group_id' in task_answer_data.keys():
        # formats for file like data/tasks/q_a_task_05311700.jsonl
        task_id = task_answer_data['group_id']
        task_answer = task_answer_data['answer']
      else:
        # formats for file like data/tasks/tasks_0611.json
        task_id = list(task_answer_data.keys())[0]
        task_answer = list(task_answer_data.values())[0]
        task_answer = task_answer.replace('```json', '').replace('```', '')
        while task_answer.startswith('\n'):
          task_answer = task_answer[1:]
        while task_answer.endswith('\n'):
          task_answer = task_answer[:-1]
      try:
        task_list = ast.literal_eval(task_answer)
        if isinstance(task_list, dict):
          task_list = list(task_list.values())[0]
          task_list = ast.literal_eval(task_list)
      except:
        print(task_id, 'format error')
        continue
      all_tasks.extend(task_list)
    return all_tasks

  def format_all_apis(self):
    apis_data = json.load(open(os.path.join(self.apis_folder_path,
                                            'apis.json')))
    apis_description = ''
    api_names = []
    for _, v in apis_data.items():
      for e in v:
        if e["name"] == "" or e["name"] in api_names:
          continue
        api_names.append(e["name"])
        name = e["name"]
        dep = e['dependency']
        desc = e["desc"]
        func = e["func"]
        semantic_dep = get_semantic_dependencies(dep)
        apis_description += f'element: {name}\n\tDescription: {desc}\n\t Function: {func} \n\tDependency: {semantic_dep}. \n\n'
    print(f'Generated description for {len(api_names)} APIs')
    return apis_description

  def make_prompt(self, tasks, formatted_apis, app_name):

    formatted_tasks = '\n'.join(
        [f'Task {i}: {tasks[i]}' for i in range(len(tasks))])

    prompt = f'''A {app_name} app in smartphone has the following important UI elements:

{formatted_apis}

You will be asked to complete tasks by writing scripts to manipulate the above elements.
In the script, except for the common python control flow (for, if-else, function def/calls, etc.), you can use the following APIs:
- tap(<element_selector>): tap on the element. Almost all elements can be taped. If an element's attribute checked=false or selected=false, tapping it can make it checked or selected, vice versa.
- long_tap(<element_selector>): long tap the element. 
- set_text(<element_selector>, <text>): set the text of the element to <text>. Only editable text fields can be set text.
- scroll(<element_selector>, <direction>): scroll the UI element in the specified direction, and direction is a str from "up", 'down", "left", "right". e.g. scroll($scroll_settings_page, "down"
- get_text(<element_selector>): return the text of the element as a string.
- get_attributes(<element_selector>): return the attributes of the element as a dict, dict keys include "selected", "checked", "scrollable", dict values are boolean. eg. get_attributes($files[3])["selected"].
- back(): close the current window


The <element_selector> primitive is used to select an element, possible ways of selection include:
- $<element id>, eg. $settings_button
- <element_list>[<idx>]: the idx-th in the element list. eg. $my_items[1]

The <element_list> primitive is used to select a list of elements, possible ways of selection include:
- <element_selector>: the items in the list element identified by <element_selector>. eg. $my_items
- <element_list>.match(<text or attribute dict>): the elements in the element list that match the given text or attribute dict. eg. $my_items.match("key words") or $my_items.match({{"selected": true}})
You can use len(<element_list>) to get the total number of items in an element list.


Now I will give you some tasks, you should return the python scripts to complete each task.
The tasks are:

{formatted_tasks}

Your answer should follow this JSON format:

{{
    "<task1>": "<script1>",
    "<task2>": "<script2>",
    ...
}}

**Note that the script is a string of python code and should only output the JSON content.**
'''
    return prompt

  def get_all_solution_query_prompts(self,
                                     app_name,
                                     tasks_path,
                                     solution_prompt_path,
                                     max_task_per_prompt=8):
    all_tasks = self.get_all_tasks(tasks_path)
    formatted_apis = self.format_all_apis()
    all_prompts = {}
    for i in range(0, len(all_tasks), max_task_per_prompt):
      if i + max_task_per_prompt > len(all_tasks):
        tasks = all_tasks[i:]
      else:
        tasks = all_tasks[i:i + max_task_per_prompt]

      prompt = self.make_prompt(tasks, formatted_apis, app_name)
      all_prompts[i] = prompt
    tools.dump_json_file(solution_prompt_path, all_prompts)
    print(
        f'**Loaded {len(all_tasks)} tasks. Generated {len(all_prompts)} prompts, {max_task_per_prompt} tasks per prompt.**'
    )
    return all_prompts

  def query_all_solution_prompts(self,
                                 app_name,
                                 tasks_path,
                                 solution_prompt_path,
                                 solution_answers_path,
                                 max_task_per_prompt=5,
                                 model='gpt-3.5-turbo'):
    all_prompts = self.get_all_solution_query_prompts(app_name, tasks_path,
                                                      solution_prompt_path,
                                                      max_task_per_prompt)
    gpt = mtp.MultiProcessingQuery(solution_answers_path,
                                   model=model,
                                   is_json=False)
    gpt.query_all_dicts(all_prompts, worker_num=8)


class FormatOrganizer:

  def __init__(self) -> None:
    pass

  @staticmethod
  def convert_str_to_dict(str_data):
    if isinstance(str_data, dict):
      return str_data
    str_data = str_data.replace('```json', '').replace('```', '')
    str_data = str_data.replace('```dict', '').replace('```', '')
    str_data = str_data.replace('```python', '').replace('```', '')
    while str_data.startswith('\n'):
      str_data = str_data[1:]
    while str_data.endswith('\n'):
      str_data = str_data[:-1]
    try:
      dict_data = ast.literal_eval(str_data)
    except:
      print(f'format error, {str_data} can not be converted to dict.')
      dict_data = {}
    return dict_data

  @staticmethod
  def form_task_solution_jsonl(solution_prompts_path, solution_json_path,
                               output_jsonl_path):
    solution_prompts = tools.load_json_file(solution_prompts_path)
    solutions = tools.load_jsonl_file(solution_json_path)
    output_jsonl = []
    for solution_data in solutions:
      if not list(solution_data.values())[0]:
        print(f'{solution_data} Empty solution')
        continue
      solution_dict = FormatOrganizer.convert_str_to_dict(
          list(solution_data.values())[0])
      if solution_dict == {}:
        continue
      solutions = list(solution_dict.values())

      prompt_id = list(solution_data.keys())[0]
      prompt = solution_prompts[prompt_id]
      pattern = r'Task \d+: ([^\n]+)'
      matches = re.findall(pattern, prompt)
      tasks = [match.strip() for match in matches]
      if len(tasks) != len(solutions):
        print(
            f'Error: prompt {prompt_id} has {len(tasks)} tasks but {len(solutions)} solutions'
        )
        # import pdb;pdb.set_trace()
        continue
      output_jsonl.extend([{
          'task': task,
          'solution': solution
      } for task, solution in zip(tasks, solutions)])

    tools.dump_jsonl_file(output_jsonl, output_jsonl_path)
    print(
        f'**Formated {len(output_jsonl)} tasks and solutions into {output_jsonl_path}**'
    )


if __name__ == '__main__':
  args = parseargs()
  if args.mode == 'doc_format':
    solver = APIPathSolver('output/notes0503')
    api_paths = solver.add_action_type_for_dependencies()
    # print(json.dumps(api_paths, indent=4))
    tools.dump_json_file('tmp/api_paths.json', api_paths)
  if args.mode == 'task':
    task_generator = TaskGenerator(app_name='Notes',
                                   apis_path='output/notes0503/apis.json',
                                   api_tree_paths_path='tmp/api_paths.json')
    task_generator.generate_prompts('data/tasks/qa_task_0612.json',
                                    use_comb=False,
                                    ele_group_strides=[2, 4, 6, 8])
    task_generator.query_all_task_prompts('data/tasks/qa_task_0612.json',
                                          'data/tasks/tasks_0612.jsonl',
                                          model='gpt-4o')
  if args.mode == 'solution':
    solution_generator = SolutionGenerator(
        apis_folder_path='output/notes0503',
        api_paths_file_path='tmp/api_paths.json')
    solution_generator.query_all_solution_prompts(
        app_name='Notes',
        tasks_path='data/tasks/tasks_0612.jsonl',
        solution_prompt_path='data/solutions/solution_prompts_0612.json',
        solution_answers_path='data/solutions/solution_answers_0612.jsonl',
        model='gpt-4o')

  if args.mode == 'format_solution_output':
    FormatOrganizer.form_task_solution_jsonl(
        'data/solutions/solution_prompts_0612.json',
        'data/solutions/solution_answers_0612.jsonl',
        'data/notes_train_data0612.jsonl')
  # solution_generator.get_all_solution_query_prompts('Notes', 'data/tasks/q_a_task_05311700.jsonl', 'data/solutions/q_a_sol_0609.json')
  # print(len(solution_generator.get_all_tasks('data/tasks/q_a_task_05311700.jsonl')))
  # print(solution_generator.format_all_apis())
